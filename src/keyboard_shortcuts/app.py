import argparse
from dataclasses import replace
import json
from pathlib import Path
import os
import sys

from PyQt5.QtCore import QLockFile, Qt
from PyQt5.QtGui import QFont, QImage, QPainter
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QMessageBox

from . import NAME
from .capture_windows import enable_physical_dpi
from .editor import RuleEditor
from .engine import EngineController, EngineError
from .store import Config, load_config
from .window import MainWindow
from .windows import is_elevated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--handoff", action="store_true")
    parser.add_argument("--smoke", type=Path, metavar="SCREENSHOT_DIR")
    args = parser.parse_args()
    enable_physical_dpi()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication([NAME])
    app.setApplicationName(NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setQuitOnLastWindowClosed(False)
    if not args.smoke and is_elevated():
        QMessageBox.warning(None, NAME, "请从普通权限的 Windows 会话启动 Keyboard Manager。")
        return 1

    data = args.smoke.resolve() if args.smoke else Path(os.environ["LOCALAPPDATA"]) / "Keyboard Manager"
    data.mkdir(parents=True, exist_ok=True)
    config_path = data / "config.json"
    lock = QLockFile(str(data / "instance.lock"))
    lock.setStaleLockTime(0)
    socket_name = f"KeyboardManager-{os.environ.get('USERNAME', 'current')}"
    server = QLocalServer()
    if not args.smoke:
        if not lock.tryLock(0):
            client = QLocalSocket()
            client.connectToServer(socket_name)
            if client.waitForConnected(1000):
                client.write(b"show")
                client.waitForBytesWritten(1000)
                client.disconnectFromServer()
            return 0
        QLocalServer.removeServer(socket_name)
        server.listen(socket_name)

    engine = EngineController(data)
    try:
        config = load_config(config_path)
    except (OSError, ValueError) as error:
        QMessageBox.critical(None, "无法读取配置", str(error))
        return 1
    if not args.smoke:
        try:
            engine.apply(config.rules)
        except EngineError as error:
            engine.error = str(error)

    window = MainWindow(engine, config_path, config, smoke=bool(args.smoke))
    if args.smoke:
        window.show()
        for index, name in enumerate(("mapping", "settings", "backup")):
            window.go(index)
            app.processEvents()
            if not window.grab().save(str(data / (name + ".png"))):
                return 2
        window.go(0)
        editor = RuleEditor(window, engine, config.rules[0] if config.rules else None)
        editor.show()
        app.processEvents()
        if not editor.grab().save(str(data / "editor.png")):
            return 2
        editor.close()
        window.config = replace(config, settings=replace(config.settings, theme="dark"))
        window.refresh()
        app.processEvents()
        if not window.grab().save(str(data / "dark.png")):
            return 2
        from .capture_text import extract_text, models_dir, translate_text
        from .capture_translation import translate_selection
        sample = QImage(760, 250, QImage.Format_RGB32)
        sample.fill(Qt.white)
        painter = QPainter(sample)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(32)
        painter.setFont(font)
        painter.setPen(Qt.black)
        painter.drawText(30, 55, "Hello world 2026")
        painter.drawText(30, 112, "今天天气很好")
        painter.drawText(30, 164, "Bonjour et bienvenue à Paris.")
        font.setFamily("Yu Gothic UI")
        painter.setFont(font)
        painter.drawText(30, 216, "日本の首都は東京です。")
        painter.end()
        try:
            report = {
                "ocr": extract_text(sample),
                "en_zh": translate_text("The weather is nice today.")[1],
                "zh_en": translate_text("北京是中国的首都。")[1],
            }
            if getattr(sys, "frozen", False) or (models_dir() / "nllb" / "model.bin").is_file():
                translation = translate_selection(sample)
                report["multilingual"] = translation.text
                if (not translation.changed or "巴黎" not in translation.text or "东京" not in translation.text
                        or "今天天气很好" not in translation.text):
                    raise ValueError(f"多语言截图翻译未通过：{translation.text}")
                if not translation.image.save(str(data / "translated-selection.png")):
                    raise OSError("无法保存截图翻译验证图片。")
        except Exception as error:
            (data / "capture-check.txt").write_text(str(error), encoding="utf-8")
            return 3
        (data / "capture-check.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return 0

    def show_instance():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            client.disconnectFromServer()
            client.deleteLater()
        window.open()

    server.newConnection.connect(show_instance)
    app.aboutToQuit.connect(engine.stop)
    app.aboutToQuit.connect(window.release_capture)
    if not args.tray or not window.tray:
        window.show()
    result = app.exec_()
    server.close()
    lock.unlock()
    return result




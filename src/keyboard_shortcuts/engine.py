import atexit
from pathlib import Path
import subprocess
import sys
import time

from .rules import Rule, compile_config
from .store import atomic_write

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EngineError(RuntimeError):
    pass


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "keymapper"
    root = Path(__file__).resolve().parents[2]
    patched = root / ".build-tools" / "patched-engine"
    if (patched / "keymapperctl.exe").is_file():
        return patched
    return root / "keymapper-runtime" / "keymapper-5.8.1-Windows-x86_64"


class EngineController:
    def __init__(self, directory: Path):
        self.directory = directory
        self.runtime = runtime_dir()
        self.children: list[subprocess.Popen] = []
        self.active: Path | None = None
        self.error = ""
        self.paused = False
        atexit.register(self.stop)

    @property
    def running(self) -> bool:
        return len(self.children) == 2 and all(child.poll() is None for child in self.children)

    def _run(self, name: str, *args: str, timeout: float = 3) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([str(self.runtime / (name + ".exe")), *args],
                                  capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EngineError("无法访问 keymapper 引擎，或引擎响应超时。") from error

    def check(self, rules: list[Rule]) -> Path:
        first = self.directory / "engine-0.conf"
        candidate = self.directory / "engine-1.conf" if self.active == first else first
        atomic_write(candidate, compile_config(rules))
        result = self._run("keymapper", "--check", "-c", str(candidate))
        if result.returncode:
            raise EngineError("keymapper 拒绝了生成的映射配置。")
        return candidate

    def _start(self, config: Path) -> None:
        from .windows import engine_present
        try:
            if engine_present():
                raise EngineError("检测到其他 keymapper 实例。请先退出该实例，再重试。")
            for name, args in (
                ("keymapperd", []),
                ("keymapper", ["--no-tray", "--no-notify", "-c", str(config)]),
            ):
                child = subprocess.Popen([str(self.runtime / (name + ".exe")), *args],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=NO_WINDOW)
                self.children.append(child)
            deadline = time.monotonic() + 2.5
            while self.running and time.monotonic() < deadline:
                if self._set_config(config):
                    return
                time.sleep(.1)
            raise EngineError("映射引擎启动失败。请检查权限或重试。")
        except (OSError, EngineError) as error:
            self.stop()
            raise EngineError(str(error)) from error

    def _set_config(self, path: Path) -> bool:
        return self._run("keymapperctl", "--timeout", "350", "--set-config", str(path),
                         timeout=1.5).returncode == 0

    def apply(self, rules: list[Rule]) -> None:
        try:
            candidate = self.check(rules)
            if not self.paused:
                if not self.running:
                    self.stop()
                    self._start(candidate)
                else:
                    self._replace_running_config(candidate)
            self.active = candidate
            self.error = ""
        except (OSError, EngineError) as error:
            self.error = str(error)
            raise EngineError(self.error) from error

    def _replace_running_config(self, candidate: Path) -> None:
        try:
            if self._set_config(candidate):
                return
            raise EngineError("未能应用映射配置。")
        except EngineError:
            if self.active is not None:
                try:
                    restored = self._set_config(self.active)
                except EngineError:
                    restored = False
                if not restored:
                    self.stop()
            raise

    def pause(self) -> None:
        self.stop()
        self.paused = True
        self.error = ""

    def resume(self) -> None:
        if self.active is None:
            raise EngineError("没有可应用的映射配置。")
        try:
            if not self.running:
                self.stop()
                self._start(self.active)
            self.paused = False
            self.error = ""
        except EngineError as error:
            self.error = str(error)
            raise

    def stop(self) -> None:
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            if child is not self.children[0]:
                time.sleep(.12)
        self.children.clear()


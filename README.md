# Keyboard Manager

Keyboard Manager 是面向 Windows 10/11 x64 的键盘映射和截图工具。它支持全局及按应用设置的按键映射、截图标注、离线文字提取和翻译。

## 下载与使用

在 GitHub Releases 中选择安装版 `Keyboard-Manager-Setup-1.0.0.exe` 或便携版 `Keyboard-Manager-Portable-1.0.0.zip`。安装版从开始菜单启动。便携版需要完整解压，再运行解压目录中的 `Keyboard Manager.exe`。操作说明随包附带。

默认截图键为 `Ctrl+S`。默认方向映射为左 Shift 加 `D`、`F`、`J`、`K`，分别对应左、上、下、右。已有用户配置可通过应用内「备份与恢复」导出。

## 从源码构建

在 Windows x64 上安装 Python 3.12、Git、MinGW-w64 和 NSIS。将 keymapper 的 `5.8.1` 标签检出到项目下的 `keymapper-upstream/`。创建 `.buildenv` 虚拟环境，并安装 `packaging/requirements-build.txt` 中的依赖。

从项目根目录依次运行 `tools/build-engine.ps1`、`tools/fetch-capture-models.py` 和 `tools/fetch-multilingual-models.py`。最后运行 `packaging/build.ps1`，必要时通过其 `-Python` 和 `-Nsis` 参数指定工具路径。Windows 运行库的版本要求见构建脚本。

## 第三方组件

映射引擎基于 keymapper 5.8.1。对应上游源码及项目补丁工具包含在发布的源码归档中。程序包附有第三方许可证和模型来源。NLLB 模型采用 CC BY-NC 4.0，适用其非商业使用条款。

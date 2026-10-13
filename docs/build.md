# 从源码开发与构建

在仓库根目录执行本文命令。测试入口见 [testing.md](testing.md)，完整发行与部署顺序见 [releasing.md](releasing.md)。首次接手先读 [handoff.md](handoff.md)。项目不使用 GitHub/Gitea Actions；推送代码或标签不会构建、测试或发布。

## 前置条件

| 用途 | 环境 |
| --- | --- |
| CLI 开发 | Git、uv、Python 3.11 或更新版本 |
| GUI 开发 | 上述工具与 `gui` extra；离线测试另需 `gui-test` 组 |
| Windows 冻结构建 | Windows x64、CPython 3.14.8、Visual Studio 2022 C++ 工具链；GUI 安装器另需 Inno Setup 7.1.0 |
| Linux 冻结构建 | Ubuntu 22.04 amd64、CPython 3.14.8、编译器、dpkg-dev、binutils、FFmpeg 和 Qt/X11 运行库 |
| 合成媒体测试 | 完整 FFmpeg：lavfi、libx264/libx265、ffprobe；用 `BILIX_TEST_FFMPEG` 指定测试编码器 |

`pyproject.toml` 定义支持范围与依赖，`uv.lock` 固定解析结果，`.python-version` 选定默认构建解释器。当前锁定 PySide6-Essentials/Qt 6.11.2、cryptography 50.0.2、Nuitka 4.2.2；CLI 环境不安装 Qt/cryptography。工具链升级须更新锁文件并重新验证受影响的原生产物。若 uv 找不到指定解释器，用已安装的 Python 完整路径传给 `--python`；Linux 可使用仓库内 [install-python3148.sh](../tests/vm/install-python3148.sh)。

## 获取源码并运行

```powershell
git clone https://github.com/Koril33/bilix.git
cd bilix
uv sync --locked
uv run --locked blx --help
uv run --locked python scripts/validate.py --profile cli
```

GUI：

```powershell
uv sync --locked --extra gui --group gui-test
uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui
uv run --locked --extra gui bilix-gui
```

统一验证脚本使用独立配置/下载/临时目录和 Qt offscreen，不读取日常登录凭据。交互 GUI 需要可见桌面；基础离线自检可单独运行 `uv run --locked --extra gui bilix-gui --smoke-test`。

合成媒体可用外部完整 FFmpeg；被测扫描/合并仍使用项目实际 FFmpeg，skip 逐项审查。`pytest --basetemp` 会清理指定目录，仅使用本轮专用目录。

## Python wheel 与源码包

先冻结候选版本、源码与文档，再运行：

```powershell
$version = uv run --locked python -c "from djhx_bilix import __version__; print(__version__)"
uv build --out-dir "dist/python-$version"
```

版本来自 [src/djhx_bilix/__init__.py](../src/djhx_bilix/__init__.py)。wheel 包含统一实现、Windows FFmpeg 与许可；sdist 还含测试、脚本、文档、页面和锁文件，排除 build/dist、凭据、VM 状态与缓存。候选 wheel 在隔离环境安装验证，见 [发布流程](releasing.md#2-python-包与最低版本验证)。

## Windows CLI EXE

CLI 在独立、未安装 GUI extra 的环境构建，防止将 Qt/更新器依赖带入 CLI 包：

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'build/venv-cli-build'
uv sync --python 3.14.8 --locked --group build
uv run --locked --group build python scripts/build_windows.py
$version = uv run --locked python -c "from djhx_bilix import __version__; print(__version__)"
uv run --locked --group build python scripts/package_windows.py `
  build/windows/bilix.exe "dist/cli/bilix-$version-windows-x64.zip"
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

`build_windows.py` 默认 onefile 输出 `build/windows/bilix.exe`；`--mode standalone` 输出目录，必须分发整个目录。脚本包含 Windows runtime DLL 和仓库 FFmpeg，禁用 LTO，缓存位于 `build/nuitka-cache`。编译报告应无 PySide6、shiboken6、GUI 与 updater。

构建后自动在中文/空格目录、最小 PATH、非 UTF-8 环境和重定向输出中检查启动、帮助、版本、doctor、参数错误与补全，日志、报告与 `smoke.json` 留在输出目录。打包脚本收集运行依赖许可、FFmpeg 对应源码和构建材料。源码与许可来源见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 和 [vendor/ffmpeg/README.md](../vendor/ffmpeg/README.md)。

## GUI 原生产物

Windows 绿色版、安装版及 Linux deb 的命令、输出与平台要求见 [gui-build-and-release.md](gui-build-and-release.md)。各平台必须原生构建和验收；Windows 检查不能证明 Linux deb 可运行。

完整发行使用 `dist/gui/` 的两平台清单、`dist/python-<版本>/` 和 `dist/cli/` 集合八项产物，按 [releasing.md](releasing.md) 签名、上传与公开回验。

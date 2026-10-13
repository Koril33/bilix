# GUI 原生构建与打包

开发环境与统一测试见 [build.md](build.md)、[testing.md](testing.md)。本文负责生成平台产物；八项集合、签名、上传和官网/APT 部署统一见 [releasing.md](releasing.md)。GUI 与 CLI 共用 `src/djhx_bilix` 内核。

## 构建契约

| 项目 | 当前要求 |
| --- | --- |
| 解释器 | CPython 3.14.8 x86-64；Python 包最低支持 3.11 |
| GUI / 签名 | PySide6-Essentials/Qt 6.11.2、shiboken6 6.11.2、cryptography 50.0.2 |
| 冻结器 | Nuitka 4.2.2；依赖由 `uv.lock` 固定 |
| Windows | Visual Studio 2022 C++ 工具链、Inno Setup 7.1.0；仓库内 FFmpeg 7.1.5 |
| Linux | Ubuntu 22.04 amd64 原生构建；系统 FFmpeg，由 deb 依赖安装 |

产物绑定同一产品源码、版本与锁文件；冻结构建嵌入发行身份和更新公钥，普通 wheel 不带冻结身份。工具链变化重验受影响平台；安装、桌面和更新事务另做验收。

当前原生目标为 Windows 10 x64、Ubuntu 22.04/24.04 和 Debian 12/13 amd64。Windows 11 完整独立验收、macOS/ARM GUI 留在 [backlog.md](backlog.md)。各版实测范围见 [文档索引](README.md#版本验收)。

## Windows

在 GUI/build 环境安装编译工具和 Inno Setup。打包脚本查找 PATH 或标准安装位置的 `ISCC.exe`，可用 `BILIX_ISCC` 指定路径；必须为 7.1.0。

```powershell
$env:UV_PROJECT_ENVIRONMENT = 'build/venv-gui-build'
uv sync --python 3.14.8 --locked --extra gui --group gui-test --group build
uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui
uv run --locked --extra gui --group build python scripts/build_gui_windows.py
uv run --locked --extra gui --group build python scripts/package_gui_windows.py
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

构建默认 `--mode both`，输出：

- `build/gui/windows/onefile/BiliX-GUI.exe`。
- `build/gui/windows/standalone/gui_entry.dist/` 完整运行目录。
- 构建日志、Nuitka 报告与 `smoke.txt`；中文/空格路径自检失败会阻止成功。

打包在 `dist/gui/` 生成 Portable EXE、Setup EXE、许可证/对应源码 ZIP、`release-manifest-windows.json`、`SHA256SUMS-windows.txt`。绿色 EXE 必须与源码/许可 ZIP 一并提供；安装器将这些材料放入安装目录。`--portable-only` 仅用于绿色版调试，不能当作完整发行。

安装器按当前用户安装至 `%LOCALAPPDATA%\Programs\BiliX`，有稳定 AppId；Preview 身份与目录独立。配置、登录与下载保留在用户目录，卸载不删除它们。手动替换前从菜单真正退出；标题栏关闭默认进入托盘。安装/升级/降级保护/卸载与更新事务按 [Windows 验收](gui-win10-validation.md) 执行。

## Linux

只在 Ubuntu 22.04 amd64 编译，避免在更新系统生成不可用于最低目标的 glibc 依赖。仓库 VM 入口会复制 Git 可见源码至 ext4 后构建，详见 [Linux 验收](gui-vm-validation.md)；直接构建使用下列 Bash 命令：

```bash
uv sync --python 3.14.8 --locked --extra gui --group gui-test --group build
uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui
uv run --locked --extra gui --group build python scripts/build_gui_linux.py
uv run --locked --extra gui --group build python scripts/package_gui_deb.py \
  --maintainer 'Koril <dingjinghui33@163.com>'
```

环境需编译器、dpkg-dev、binutils、系统 FFmpeg、X11/Qt 运行库；自动准备见 [provision.sh](../tests/vm/provision.sh)。解释器可通过 [install-python3148.sh](../tests/vm/install-python3148.sh) 校验官方源码后编译。

构建输出 `build/gui/linux/gui_entry.dist/`，做中文/空格路径离线自检。打包从实际 ELF 推导系统共享库依赖，在 `dist/gui/` 生成：

- `djhx-bilix-gui_<应用版本>-<Debian修订>_amd64.deb`。
- `djhx-bilix-gui_<应用版本>_source.tar.gz`。
- `release-manifest-linux.json`、`SHA256SUMS-linux.txt`。

预发布 `.dev0` 映射为 Debian `~dev0-1`。当前默认修订由 [gui_release.py](../scripts/gui_release.py) 的 `deb_version()` 定义，文件名以脚本实际输出为准。

deb 安装私有 Python/Qt 至 `/usr/lib/djhx-bilix-gui/`，提供 `/usr/bin/bilix-gui`、桌面入口、图标、许可和固定更新授权入口。FFmpeg 由系统包管理器提供。GUI 以普通用户运行，安装更新通过系统授权。Qt compose/IBus 后端和 DBus 库显式收集；插件存在不证明真实 IME 提交通过。

同一 deb 在四目标执行安装/启动/重装/真实旧版升级/卸载与数据保留。offscreen、Xvfb、真实 X11、无头 Weston、完整 GNOME/KDE Wayland 分别记录，不能互相替代。用户安装与 APT 源见 [gui-updating.md](gui-updating.md)。

## 图标、许可和源码

应用图标源为 [bilix.svg](../src/djhx_bilix/assets/bilix.svg)。修改后运行 `uv run --locked --extra gui python scripts/generate_icons.py`，提交多尺寸 PNG/ICO；Windows EXE/Inno、Linux 桌面和窗口同步使用派生资源。`action-*.svg` 由 QtSvg 按主题渲染，两平台均收集。

[gui_release.py](../scripts/gui_release.py) 从构建环境收集 Python、Qt/PySide6、Nuitka runtime、cryptography 与 FFmpeg 的许可/源码材料，缺必要信息拒绝打包。Qt for Python 社区版采用 GPL-3.0-only 选项；Linux wheel 无独立 notice 时保留 METADATA 许可表达式与 GPL 全文，Windows 保留 wheel 原 notice。最终构建清单决定实际分发材料，详见 [第三方声明](../THIRD_PARTY_NOTICES.md)。

公开二进制须同时提供当前 Qt 与 Qt for Python 的准确源码入口；当前为 [Qt 6.11.2](https://download.qt.io/archive/qt/6.11/6.11.2/single/qt-everywhere-src-6.11.2.tar.xz)、[Qt for Python 6.11.2](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz)。上游停止提供时由维护者保持可用镜像。Windows 内置 FFmpeg 的源码和构建材料必须与二进制对应。

## 集合

两个平台文件与各自清单齐备后：

```powershell
uv run --locked --extra gui python scripts/assemble_gui_release.py
```

脚本核对两平台清单、版本、大小和 SHA256，生成五项 GUI 合并清单；只有当前清单列出的文件进入集合。随后按 [releasing.md](releasing.md) 集合 Python/CLI 为八项并只读复核。

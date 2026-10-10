# GUI 本地构建、安装与发布

GUI 与 CLI 共用 Python 下载内核。本文件说明首个图形界面版本 `1.6.0` 的构建方式；正式发行须完成下述跨平台安装验证并发布准确的哈希。1.5.0 不包含 GUI。

后续版本沿用[持续测试规范](testing.md)和[验收模板](validation-template.md)，将结果保存在独立版本记录。1.6.0 已发布的文件不可重包/覆盖；最终证据与范围见[首版复核](validation-1.6.0.md)。工具链表是首版基线，升级 Qt/Python/Nuitka 后须重新验收完整平台矩阵。

## 版本与支持范围

1.7.2 统一应用图标，源稿为 `src/djhx_bilix/assets/bilix.svg`。修改源稿后在 GUI 环境运行 `python scripts/generate_icons.py`，生成 16/24/32/48/64/128/256/512 像素 PNG 和包含前七档的 ICO，并提交派生文件。Windows GUI/CLI EXE 和 Inno Setup 使用同一 ICO；GUI 使用 PNG 设置运行时窗口图标，两套 GUI 构建均显式收集 PNG。Linux deb 安装 SVG 与多尺寸 PNG，并将 Qt desktopFileName 与 `djhx-bilix-gui.desktop` 对应。

按维护者 2026-10-10 的要求，1.7.2 仅执行图标、构建启动及发行材料定向验证，不重复多系统 IME/DPI、性能、账号/下载或安装异常矩阵；实际结果见 [1.7.2 记录](validation-1.7.2.md)。

| 部件 | 首版构建基线 |
| --- | --- |
| 构建解释器 | CPython **3.14.8** x86-64 |
| GUI | PySide6-Essentials / Qt **6.11.2**、shiboken6 **6.11.2** |
| 冻结构建 | Nuitka **4.2.2** |
| Windows 安装器 | Inno Setup **7.1.0** |
| Windows FFmpeg | 仓库内 `src/djhx_bilix/assets/ffmpeg.exe`（7.1.5）；同时提供对应源码与许可材料 |
| Linux FFmpeg | 系统 `ffmpeg` 包；deb 声明依赖，普通用户无需自行编译 |

本轮验收目标是 Windows 10 22H2 x64，以及 Ubuntu 22.04/24.04 与 Debian 12/13 的 amd64 桌面。Linux 在 Ubuntu 22.04 amd64 构建，以该系统作为 glibc 基线；仍需在每个目标发行版做干净环境安装测试。Windows 11、macOS、ARM、MSI 与自动更新留待后续。CLI 的 Python 最低要求仍为 3.11；只有 GUI **发行构建**固定 3.14.8。GUI 的 PySide6 依赖放在可选 `gui` extra，普通 CLI 安装不会额外安装 Qt。

所有发行操作由维护者在本地执行，推送提交或标签不会自动构建、上传或部署。运行构建脚本前先检查 Git 工作树、版本、许可材料和凭据；不要把本地账号配置目录放进构建输入。

## 源码开发与测试

在项目根目录使用 uv，并显式选择 3.14.8。2026-10-03 时 `uv python install 3.14.8` 尚无可下载的独立解释器；Windows 可从 [Python 官方 3.14.8 发行页](https://www.python.org/downloads/release/python-3148/)取得 64 位安装器并核对公布的 SHA256，再把下面 `--python` 的值替换为实际 `python.exe` 完整路径。仓库的 [Linux VM 构建脚本](../tests/vm/install-python3148.sh)从官方源码校验后编译同一版本：

```shell
uv sync --python 3.14.8 --locked --extra gui --group gui-test --group build
uv run --locked --extra gui --group gui-test python -m pytest -q
uv run --locked --extra gui --group gui-test ruff check src tests scripts
uv run --locked --extra gui --group gui-test ruff format --check src tests scripts
uv run --locked --extra gui bilix-gui --smoke-test
uv run --locked --extra gui bilix-gui
```

无显示器的测试环境可设置 `QT_QPA_PLATFORM=offscreen`，但发行前仍应在真实桌面验证字体、缩放、输入法、文件选择器与二维码窗口。`--smoke-test` 只构造 GUI 并离线检查 FFmpeg；它不验证账号、真实下载或安装器行为。测试固定使用虚构凭据与本地模拟网络；需要 Bilibili 账号的在线验证应单独执行并保护凭据。

自检还会验证内存中的测试二维码 PNG 可加载，这不代表真实登录已成功。完整离线回归使用 `scripts/validate.py --profile gui`，实际扫码与下载按测试规范单独记录。

## Windows：单文件绿色版与安装版

在 Windows x64 的 3.14.8 GUI/build 环境安装 Visual Studio 2022 C++ 编译工具与 Inno Setup 7.1.0。打包脚本查找 PATH 或标准安装位置的 `ISCC.exe`；便携安装可用 `BILIX_ISCC` 指向编译器，脚本会核对版本为 7.1.0。默认构建两种 Nuitka 形式：

```powershell
uv run --locked --extra gui --group build python scripts/build_gui_windows.py
uv run --locked --extra gui --group build python scripts/package_gui_windows.py
```

也可分别运行 `scripts/build_gui_windows.py --mode onefile` 与 `--mode standalone` 做调试。第一步输出 `build/gui/windows/onefile/BiliX-GUI.exe` 和完整的 `build/gui/windows/standalone/gui_entry.dist/` 目录；脚本会在含中文和空格的路径下启动冻结程序并检查内置 FFmpeg，记录 `build.log`、编译报告与 `smoke.txt`。只有两个启动检查都通过，第二步才可制作完整发行组合。

第二步在 `dist/gui/` 生成单文件绿色 EXE、Inno Setup 安装器 EXE、许可证和对应源码 ZIP，以及 `SHA256SUMS-windows.txt`、`release-manifest-windows.json`。**单文件 EXE 与许可证/源码 ZIP 必须一并提供**；安装器将这些材料纳入安装目录。若暂时没有 Inno Setup，可用 `scripts/package_gui_windows.py --portable-only` 先生成绿色版及其配套材料，这不等于安装版已经完成。

绿色版无需安装 Python/Qt。关闭程序后替换 EXE 即为手动升级；默认账号、设置与下载目录在用户目录，不随 EXE 移动。安装版按当前用户安装到 `%LOCALAPPDATA%\Programs\BiliX`，建立开始菜单项，可选桌面快捷方式与系统卸载项；开发预发布使用单独的 `BiliX Preview` 身份和目录，避免覆盖稳定版。升级安装版前先结束下载任务并退出应用，再运行新版安装器。卸载保留用户配置和已下载文件。

发行前应在无 Python、Qt 和构建工具的干净 Windows x64 用户环境检查：绿色版冷启动与重复启动、中文/空格路径、二维码与取消、批量/多 P 下载、账号状态、FFmpeg、文件校验、旧版本升级、安装/卸载及配置保留。安装版还需执行真实安装、升级、降级阻止与卸载流程；只编译出 Setup EXE 不等于这些场景已通过。

## Linux：Ubuntu/Debian deb

在 **Ubuntu 22.04 amd64** 构建机中安装编译器、`dpkg-dev`、`binutils`、系统 `ffmpeg` 与图形运行库；X11 所需库可按 [Qt 官方 Linux 依赖表](https://doc.qt.io/qt-6/linux-requirements.html)核对。使用锁定的 Python 3.14.8 GUI/build 环境：

```shell
uv sync --python 3.14.8 --locked --extra gui --group gui-test --group build
QT_QPA_PLATFORM=offscreen uv run --locked --extra gui --group gui-test python -m pytest -q
uv run --locked --extra gui --group build python scripts/build_gui_linux.py
uv run --locked --extra gui --group build python scripts/package_gui_deb.py --maintainer 'Koril <dingjinghui33@163.com>'
```

构建脚本输出 `build/gui/linux/gui_entry.dist/` 并在中文/空格路径做无网络启动检查；打包脚本为包内共享库生成构建期映射，再从实际 ELF 文件计算系统共享库依赖，制作 `dist/gui/djhx-bilix-gui_<版本>_amd64.deb`、对应源码包、`SHA256SUMS-linux.txt` 与 `release-manifest-linux.json`。预发布 Debian 版本把 `.dev0` 映射为 `~dev0-1`，排序低于同号正式版。deb 包在 `/usr/lib/djhx-bilix-gui/` 放置私有 Python/Qt 运行时，提供 `/usr/bin/bilix-gui`、桌面入口、图标、许可和源码获取说明。FFmpeg 由发行版 `ffmpeg` 依赖提供；GUI 应以普通用户运行，不应以 root 启动。

1.7.0 起构建脚本显式复制 Qt 的 compose/IBus 输入后端及所需 Qt DBus 库。Nuitka 默认插件族不会自动包含 `platforminputcontexts`；整个目录中的虚拟键盘插件依赖 Essentials 未提供的 Qt Quick，因此只选择桌面需要的两个后端。插件文件和动态依赖检查通过仍不等于中文 IME 提交已经验收，T5 须在真实会话操作。传输库锁定为 curl-cffi 0.16.3，项目依赖范围为 `>=0.16.3,<0.17`；此前候选在 0.13.0 发现流式关闭竞态，修复与回归见 [1.7.0 验收记录](validation-1.7.0.md)。

用户可通过 `sudo apt install ./djhx-bilix-gui_<版本>_amd64.deb` 本地安装或升级。把 deb 上传到网页/GitHub 不会自动生成 APT 更新源；自建 APT 仓库的签名、索引与轮换方案见[发行与升级调研](gui-distribution-and-updates.md)。首版 GUI 不内置自动更新。使用 `apt` 升级时程序文件交给包管理器管理，账号配置与下载文件保留在用户目录。

正式发布前须在干净的 Ubuntu 22.04/24.04 与 Debian 12/13 amd64 桌面上实际测试 deb 安装、运行、X11、FFmpeg、中文路径、卸载及数据保留。Wayland、真实账号下载和跨版本升级应分别记录实际执行的系统与范围；未执行时明确列为未验证。本机若无 Linux 构建/测试环境，不能把 Windows 检查记作 deb 已通过。

## 发行检查与许可

`scripts/gui_release.py` 从锁定运行环境收集 Python、PySide6/shiboken6、Qt 相关 wheel、Nuitka runtime 和 FFmpeg 的声明与源代码材料；缺少必要许可信息会拒绝打包。Linux 的 PySide6-Essentials/shiboken6 wheel 未附单独许可文件时，发行包会明确记录 wheel METADATA 中的许可表达式并附 GPL-3.0 全文，Windows wheel 则复制其原有 notice。Qt for Python 社区版按其 GPL-3.0-only 选项与 BiliX 的 GPL-3.0-only 一起分发，具体模块与第三方代码仍须按最终构建清单核对。公开二进制时，发行说明与配套源码包须给出可用的[Qt 6.11.2 对应源码](https://download.qt.io/archive/qt/6.11/6.11.2/single/qt-everywhere-src-6.11.2.tar.xz)及[Qt for Python 6.11.2 对应源码](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz)直链；若上游停止提供，应以自有镜像维持获取。参见[第三方声明](../THIRD_PARTY_NOTICES.md)。

两个平台的最终文件放在同一 `dist/gui/` 后，运行 `python scripts/assemble_gui_release.py`。该脚本逐个校验平台清单、文件大小与 SHA256，并生成合并的 `release-manifest.json` 和 `SHA256SUMS.txt`；任何缺失、旧版本或篡改都会使汇总失败。公开上传应使用合并清单列出的五个文件和配套平台源码包，不把仅含一部分平台产物的清单当成完整发行。

同一版本的 Python wheel/sdist 放在 `dist/python-<版本>/`，Windows CLI ZIP 放在 `dist/cli/bilix-<版本>-windows-x64.zip`；然后运行 `python scripts/assemble_release.py`。它再次核验两个平台的 GUI 清单、wheel/sdist、CLI ZIP 内容与哈希，在 `dist/release-<版本>/` 集合八个文件，并生成覆盖全部八项的最终 `release-manifest.json`、`SHA256SUMS.txt`。GitHub 发行页应上传该目录中列出的文件与校验清单；PyPI 上传同一目录中的 wheel/sdist。旧版本文件即使留在 `dist/gui/`，也不会进入新版本清单。

发行前还应运行 `python scripts/check_secrets.py --scope working-tree` 并复核历史，核对合并清单、完整源码、版本号、系统最低要求与实际通过的测试。源码变更后重新编译二进制；只更新文档和许可材料时也应重新打包并复验最终哈希。先上传不可变的版本化文件与配套材料，再发布发行说明；未完成的操作系统、安装器或在线权限测试要在记录中列为未验证。新版本不得覆盖既有发行文件。

## 验证记录

每次发行的实际检查结果分别记录于 [Windows 10 VM 流程](gui-win10-validation.md)与 [Ubuntu/Debian VM 矩阵](gui-vm-validation.md)。记录应标明测试系统、候选文件哈希、安装和卸载结果，以及可见桌面与真实账号检查的范围。离线回归使用虚构账号和本地服务，不能替代真实权限验证；首次稳定 GUI 版本也没有可供跨稳定版升级测试的旧 GUI 安装包。

从下一版开始，实际结果统一另存 `validation-<版本>.md`，平台文件仅维护可重复操作与历史备注。旧版升级、降级策略、IME、完整 Wayland 和性能必须逐项填写，不能沿用首版的“未验证”说明作为永久豁免。

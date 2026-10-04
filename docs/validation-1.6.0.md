# 1.6.0 完成情况与复核

复核日期：2026-10-04（Asia/Shanghai）。1.6.0 是首个 GUI 正式版，GitHub 与 PyPI 均已发布。公开标签 `v1.6.0` 对应提交 `3499963ce252556aec9645df7e14df4bfd63d656`。本文补记最终发行证据与发布后的维护检查；新增的测试规范/脚本尚未进入该标签或公开发行包。

结论：首版 CLI/GUI 的离线功能、下载事务、发行材料和已列明平台的安装生命周期已完成；以下在线业务及桌面/升级缺口仍未验证，不能据此声称首版全部场景通过。

## 功能核对

| 范围 | 1.6.0 实现与证据 |
| --- | --- |
| 共用业务内核 | CLI/GUI 共用解析、选集、权限、规划、传输、媒体校验与原子提交；无第二套下载器 |
| CLI | 信息/JSON、批量、多 P、strict、音轨、旧入口、退出码、补全、相近指令、doctor 保留 |
| GUI | 下载/账号/设置/诊断四页；信息、计划、下载、失败/取消重试、任务阶段、输出目录 |
| 生命周期 | 单活动 worker，批量串行、音视频并行；关闭窗口协作取消并等待线程，取消终止 FFmpeg |
| 文件安全 | 普通失败保留临时材料，取消清理本次临时目录；提交前保护原目标，完成后不能撤销 |
| 配置/凭据 | CLI/GUI 共用用户目录；环境优先；Qt 为可选依赖；安全异常、二维码清理回归 |
| 发行 | Windows CLI ZIP、GUI portable/Setup/源码许可 ZIP、amd64 deb/源码、wheel/sdist、统一校验清单 |

GUI 不持久化队列/历史，不支持任务级暂停/续传、运行中追加任务或应用内自动更新；没有速度/剩余时间、缩略图、可视选集勾选和完整快捷键体系。它们属于后续改进，不应写成首版已有功能。

## 最终发行文件

下表来自最终 `dist/release-1.6.0/release-manifest.json`，本次再次与公开 GitHub asset digest、PyPI JSON 元数据及本地回下载文件对照。GitHub 于 2026-10-04 13:51:16（北京时间）发布稳定版。

| 文件 | 大小（bytes） | SHA256 |
| --- | ---: | --- |
| BiliX-GUI-Portable-1.6.0-windows-x64.exe | 32549376 | `bde402cf11aa912bf0c07b2f55976d83d2639e48bd37ee4a0afab57830cf99a1` |
| BiliX-GUI-Setup-1.6.0-windows-x64.exe | 43948906 | `45940d30610e674c49f463f6cf3474614284ed17ac496c703ca6cdfb61f7adb3` |
| BiliX-GUI-licenses-and-source-1.6.0-windows-x64.zip | 13132626 | `543a38aba2ebce3398f2b16a1d96ac9d530896a36f47591588ce6080f125a449` |
| bilix-1.6.0-windows-x64.zip | 29486729 | `aef72715d565da388f14d905c2fb3d108a2c2e476d32b344f52a156da80c9d6a` |
| djhx-bilix-gui_1.6.0-1_amd64.deb | 62286850 | `d6ba0f21662b924559eae4be045eeeb454866941c326601ae2e558419a500f26` |
| djhx-bilix-gui_1.6.0_source.tar.gz | 247314 | `4cbf21c85990b9d8c4d7b477019bb4e81ccf71027abf41b3c98ed7521240cf93` |
| djhx_bilix-1.6.0-py3-none-any.whl | 1778281 | `03af80e771e5d709de20eb6f6d25da711509968f0cf0323459041e68d0d4f836` |
| djhx_bilix-1.6.0.tar.gz | 13247912 | `ca500855757f54cee586f272eaa189fae6af7286176a5b4429b45d0b8f4b66c0` |

GitHub 的上述八项、manifest、SHA256SUMS 共十个文件已有完整回下载验证（`build/release-1.6.0/github-verification.json`）；PyPI 两项哈希一致，`Requires-Python >=3.11`（`pypi-verification.json`）。公开入口：[GitHub 1.6.0](https://github.com/Koril33/bilix/releases/tag/v1.6.0)、[PyPI 1.6.0](https://pypi.org/project/djhx-bilix/1.6.0/)。网站页面源码随仓库维护；本轮复核未部署网站，Git/GitHub/PyPI 的发布不代表网站已部署。

## 发行时已执行

| 检查 | 环境与结果 | 本地证据 |
| --- | --- | --- |
| 全量离线回归 | Windows / CPython 3.14.8：248 passed；Ruff 通过 | 原发行构建/测试日志 |
| Linux 回归 | Ubuntu 22.04 / CPython 3.14.8：243 passed，5 项 Windows 专用 skip | `dist/gui/validation/ubuntu2204-build/pytest-final.log` |
| Windows 最终包 | Win10 22H2 x64 build 19045：最终哈希、两次启动、安装、自检、锁释放、卸载及数据保留 15 项通过 | `dist/gui/validation/win10/final-result.json` |
| Linux 最终 deb | 四发行版安装、offscreen/Xvfb、重装、卸载、用户标记保留通过 | `dist/gui/validation/final-matrix.json` 与各发行版日志 |
| 最低 Python | 3.11 隔离 CLI/GUI 最终 wheel，19 项入口/纠错/补全/doctor/GUI 检查通过；CLI 无 Qt | `build/release-1.6.0/python311-validation-public-pypi-artifact.json` |
| 元数据/源码 | Twine 通过；Windows 源码包、wheel、Linux 源码包、sdist 分别核对 105/25/93/112 个对应文件 | `build/release-1.6.0/source-validation.json` |
| 凭据与材料 | 当前工作树扫描 0；历史失效凭据由维护者确认，未重写历史；许可/FFmpeg 对应源码随包提供 | 脱敏扫描与发行记录 |

Windows 中文字体、拼音输入与原生目录选择器在 GUI 代码未变的较早候选完成；最终包重新执行安装/启动验收。四 Linux 目标在 XFCE/X11 完成中文显示/路径粘贴/目录选择；Ubuntu 24.04、Debian 13 的无头 Weston/Wayland 自检通过。这些结论分别绑定候选/会话，不能扩大为全部最终包桌面操作或 GNOME/KDE 支持。

## 未完成的验证与发现

| 项目 | 状态与影响 | 后续处理 |
| --- | --- | --- |
| 真实账号扫码/权限/下载 | 未验证；模拟二维码和合成响应不能证明平台当前接口有效 | 下版安排受保护测试账号，CLI/GUI 同样本对照 |
| Linux 中文 IME | 未验证；粘贴中文路径不等于输入法提交 | 四目标可见桌面输入/提交、文件对话框复测 |
| 完整 Wayland 桌面 | 未验证；Weston 无头仅启动检查 | GNOME/KDE 会话分别验收剪贴板/对话框/缩放 |
| 跨稳定 GUI 版本升级 | 不适用：首版无旧稳定包 | 下版以 1.6.0 为基线测试两个安装渠道 |
| Windows 安装器降级保护 | 代码核对发现 `.iss` 无显式已安装版本比较；尚未做实际低版安装验证 | 下版先实现并验证拒绝覆盖较新稳定版 |
| DPI/键盘/低分辨率/性能 | 本轮未提供完整测量证据；现有最小窗口为 760×590 | 下版建立标准场景与相同机器的性能基线 |
| Python 3.12/3.13、macOS CLI | 本轮无独立新验证记录；元数据支持范围不能代替实测 | 补解释器/系统安装与入口矩阵 |
| Windows 11/macOS GUI/ARM | 首版未纳入原生 GUI 支持 | 在目标系统构建和验收后扩展 |
| Vagrant box 原文件哈希 | 本轮未留存；固定 box 版本仍依赖外部供给 | 留许可允许的镜像与 box 哈希，验证离线重建 |
| 镜像发行页/网站部署 | 本轮复核仅确认主 GitHub/PyPI；网站未部署 | 发布记录按渠道分别填写 |

## 本次维护完成项

- 重新运行当前源码全量回归，检查公开文件元数据、最终包哈希/归档及历史最终 VM 证据。
- 新增[持续测试规范](testing.md)、[版本模板](validation-template.md)、只读最终包复核入口和独立运行记录；GUI 测试依赖缺失不再能在统一入口中静默通过。
- Linux 按 manifest 精确选择候选 deb，支持多版本文件并存，每轮证据不覆盖；Windows/Linux 数据保留检查扩展到非默认配置与下载标记。
- 同步开发/发布/使用/平台文档，明确选型资料中的计划与已实现功能；[下一版建议](roadmap.md)单独维护。

| 本次重新执行的检查 | 结果与范围 | 证据 |
| --- | --- | --- |
| 当前源码 GUI profile | Windows / Python 3.14.8：252 passed，0 failed，0 skip；Ruff、文档相对文件链接、CLI 入口与 GUI 自检通过 | `build/validation/1.6.0/gui-*/result.json`（选择完整 GUI 环境的通过记录） |
| 隔离 CLI profile | Python 3.14.8，无 Qt/pytest-qt 的独立锁定环境：232 passed，0 skip；CLI 检查通过 | `build/validation/1.6.0/cli-20261004T113625Z-d59c089f/result.json` |
| GUI 缺依赖检查 | 无 Qt 环境运行 GUI profile 返回 1，按预期拒绝，未把 GUI importorskip 当作通过 | `build/validation/1.6.0/gui-20261004T113625Z-01b4c67c/result.json` |
| 已安装公开 wheel | Python 3.11 CLI/GUI 隔离环境的 19 项检查重新通过 | `build/validation/1.6.0/python311-recheck.json` |
| Windows 绿色版 | 宿主机 Win10，按分平台及完整清单各通过 8 项哈希/来源/两次启动检查；未在宿主安装 | `build/validation/1.6.0/windows-portable*/` |
| 更新后的 Linux 验收 | 四个原有专用 VM 上公开最终 deb 的安装、offscreen/Xvfb、重装、卸载及配置/下载标记保留通过；此次未重建 VM 或重新验证干净依赖解析 | `build/validation/1.6.0/linux-recheck.json` 与所引用的四个独立目录 |
| Linux 驱动脚本 | PowerShell/Bash 语法检查通过；空目标列表下 Vagrant 配置、完整清单选包与哈希预检查通过，未执行 VM 销毁 | 平台脚本检查输出 |
| 公开文件/源码 | 实时 GitHub/PyPI 元数据对照原完整回下载文件：10/2 项哈希通过；四源码归档与 v1.6.0 标签内容一致，文本只存在 checkout 的 CRLF/LF 差异 | `public-recheck.json`、`source-tag-recheck.json`（均在上述版本目录） |
| 凭据扫描 | 当前工作树 0 findings | `build/security/working-tree.json` |

Linux 复验最初发现完整 `SHA256SUMS.txt` 为 Windows CRLF，`sha256sum` 将回车误认作文件名；失败证据保存在 `dist/gui/validation/ubuntu2204/20261004T113541Z-1428/`。脚本仅对校验输入规范化行尾，修复后四目标通过，原发行包与清单未改写。

维护代码并未重新发行 1.6.0。Windows 安装/卸载继续以原先最终 VM 的 15 项证据为准；本次新增的 Windows 配置/下载内容检查已通过静态检查及绿色版路径，尚未在 VM 重新执行安装模式。跨版升级与降级保护仍未验收；不要把本次绿色版结果当成安装器新增检查已通过。Ubuntu 24.04 与 Debian 13 在 `vagrant halt` 的正常关机等待后触发其超时强制关机；包验收已经结束且证据复制完成，关机行为不属于 GUI 生命周期通过证据，后续需单独排查桌面测试 VM 的关机超时。

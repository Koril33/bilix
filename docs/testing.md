# 测试与版本验收

在仓库根目录运行。日常回归使用一个入口；原生包、可见桌面、在线业务和公开渠道分别留证。当前缺陷与流程缺口见 [workflow-issues.md](workflow-issues.md)，未实现功能见 [backlog.md](backlog.md)。历史版本的“通过”不证明当前候选通过。

## 日常回归

CLI：

```powershell
uv sync --locked
uv run --locked python scripts/validate.py --profile cli
```

GUI 或共享内核：

```powershell
uv sync --locked --extra gui --group gui-test
uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui
```

脚本核对 checkout、导入包与安装元数据的版本；不一致直接失败。不要用 PYTHONPATH 或旧 `*.egg-info` 绕过检查，应重装当前源码或对应 wheel。GUI profile 检查全部共享内核、CLI、GUI 和更新器；CLI profile 排除 `tests/gui`、`tests/updates`，不引入 Qt/cryptography。GUI 依赖缺失直接失败。

一次运行包含 Markdown 相对文件链接、Ruff、pytest、CLI 帮助/版本/doctor/纠错/四种补全脚本，以及 GUI 离线启动。它使用虚构账号、本地 HTTP 和合成媒体，不登录、不操作 VM、不上传或部署。

结果写到 `build/validation/<版本>/<profile>-<UTC时间>-<随机数>/`：

- `result.json`：提交、工作树、锁文件哈希、环境与逐步状态。
- `pytest.xml`：测试结果和每项 skip 原因。
- 各步骤日志：失败定位；每轮独立，不覆盖旧证据。

完整媒体测试需要 lavfi、libx264/libx265 和 ffprobe；用 `BILIX_TEST_FFMPEG` 指定生成器。被测媒体扫描和合并仍使用项目实际 FFmpeg。开发环境允许有说明的 skip；Windows 全能力发行检查加 `--strict-skips`，Linux 的 Windows 专用 skip 逐项审查并引用 Windows 证据。

## 按改动选择检查

| 改动 | 必做检查 | 扩大范围的触发条件 |
| --- | --- | --- |
| 文档 | 相对文件链接、命令/参数对照源码 | 页面变化另做浏览器检查；发行包材料变化刷新归档/哈希 |
| CLI 或共享内核 | CLI profile；涉及 GUI 调度/数据再跑 GUI profile | 网络、媒体、凭据、取消和事务变化补相应故障/在线检查 |
| GUI | GUI profile 与受影响的可见桌面操作 | 布局/Qt/字体/输入变化复验 IME、DPI、目录选择器 |
| 安装器或更新器 | GUI profile、目标冻结包、实际升级与故障事务 | 影响多个发行形式时各自验证 portable/installer/deb |
| 构建依赖或工具链 | 重新构建并验证所有受影响平台 | Qt/原生依赖变化复验完整平台桌面 |
| 新发行 | 当前源码完整回归、最低 Python、八项最终包、签名与公开回验 | 未测范围须写在当版记录与发行说明 |

输入未变的二进制可以复用已绑定哈希的证据。改动产品源码或构建输入须重编译受影响程序；仅文档/许可变化也要重新打包并复核最终归档。通过后不为同一风险重复跑整套检查。

## 发行阶段

| 阶段 | 证据 | 操作入口 |
| --- | --- | --- |
| Python 分发 | 最终 wheel 在隔离环境安装，最低 Python 的入口/回归，CLI 无 Qt | [发布流程](releasing.md#2-python-包与最低版本验证) |
| Windows 原生包 | 绿色版中文/空格路径、安装/重装/升级/卸载、数据哈希、更新事务 | [Windows 流程](gui-win10-validation.md) |
| Linux deb | Ubuntu 22.04 构建，同一 deb 在四目标安装/重装/升级/卸载，X11/FFmpeg | [Linux 流程](gui-vm-validation.md) |
| 可见桌面 | 当前版本真实 IME、DPI、键盘、文件选择器、二维码、窗口退出 | 平台流程与当版验收记录 |
| 在线业务 | 经授权账号扫码、实际权限、下载与 CLI/GUI 对照；只保留脱敏结果 | [账号说明](accounts.md) 与当版验收记录 |
| 最终集合 | 八项大小/SHA256、归档路径、版本与必要许可/源码材料 | 下方只读命令 |
| 公网回验 | GitHub/PyPI/官网/APT 各自回下载、验签/哈希、公开包安装 | [发布流程](releasing.md#7-公开回验与完成条件) |

候选版本从源码读取，不把某个旧版本写进通用命令：

```powershell
$version = uv run --locked python -c "from djhx_bilix import __version__; print(__version__)"
uv run --locked --extra gui --group gui-test python scripts/validate.py `
  --profile gui --release-dir "dist/release-$version" --strict-skips
```

Linux 去掉 `--strict-skips` 后逐项审查 skip。此命令重新运行离线回归并**只读**检查最终集合，不修改发行目录；应使用与产物版本一致的 checkout。`assemble_release.py` 会写文件，只用于集合候选，不能用于复核公开发行。

集合校验并不证明二进制的编译来源；逐文件源输入、平台环境、冻结报告与实际安装要另存证。签名元数据也要单独验签。忽略目录内一次性脚本不是公开入口，缺口见 [交接文档](handoff.md#自动化边界)。

## 平台与数据保留

Python 支持范围由 `pyproject.toml` 定义；最低 3.11 的隔离 wheel 必测，锁定构建解释器执行全量。3.12/3.13 或其他系统未跑时照实记录，不沿用旧结果。

Windows 当前原生验收目标为 Windows 10 22H2 x64，PowerShell 5.1/7 分别记录；Windows 11 未做独立完整验收。Linux 目标为 Ubuntu 22.04/24.04、Debian 12/13 amd64，同一 deb 在 Ubuntu 22.04 构建。Xvfb、真实 X11、无头 Weston、GNOME/KDE Wayland、真实 IME 分开填写。macOS/ARM 的 Python 元数据可安装不等于 GUI 原生支持。

升级测试使用原始稳定包及其公开哈希。先在隔离用户目录用旧版创建非默认配置、虚构凭据占位与下载标记，关闭程序后升级，核对内容哈希、版本、再次启动与卸载后保留。Windows 的 `-PriorSetup`、Linux 的 `-PriorDeb` 接受本轮选定的旧包；同版重装、Preview 安装或占位文件不能代替稳定升级与真实账号有效性。

新 Windows 安装器有降级保护；已发布的 1.6.0 旧安装器没有该逻辑，不能宣称旧包也会拒绝覆盖。APT 显式降级遵守包管理策略。磁盘耗尽、权限不足、用户取消、安装失败、断电/强杀各自留证，不能由一个网络失败用例代替。

## 固定用例目录

自动用例以 `tests/` 为准；原型测试证明设计实验，不证明生产 GUI 已完成。历史场景编号保留在 [1.7.x 设计矩阵](cli-gui-ux-review.md#9-验收矩阵与发布门槛) 和各版指南；新版本使用 [validation-template.md](validation-template.md) 记录变更、风险、结果和证据，不把历史设计中的待办复制成当前事实。

| ID | 风险与通过标准 |
| --- | --- |
| CORE-01 / CORE-02 | URL/选集/批量解析准确；权限、降级、strict、试看/DRM 拒绝符合契约 |
| CORE-03 / CORE-04 / CORE-05 | 网络重试、媒体校验、取消和提交失败保护旧文件，无遗留子进程 |
| CLI-01 / CLI-02 | 所有入口、退出码、脱敏输出、四种 shell 补全与路径行为正确 |
| GUI-01 / GUI-02 / GUI-03 / GUI-04 | 任务隔离、账号生命周期、取消/退出/重试、共享配置正确 |
| UX-01 | 可见桌面的 IME、DPI、键盘、长标题、小屏、目录选择器正确 |
| PKG-01 / PKG-02 | 干净安装、启动、重装、真实升级/降级、卸载和用户数据保留 |
| REL-01 | 同版本/同源码、许可、源码归档、凭据扫描、公开哈希一致 |

新能力增加稳定 ID；删除用例须说明被替代的风险。更细的版本场景沿用当版指南，实际状态单独记录。

## 结果判定与发布门槛

只使用“通过、失败、未验证、不适用”。每份证据绑定版本、源码提交/工作树、产物哈希、操作系统、执行时间和准确范围。历史原生图片/日志位于被忽略的本地目录，公开仓库只能查到汇总时，应注明证据不可随 clone 重现。

代码/媒体/文件事务/凭据保护失败、安装或启动失败、源码/哈希不一致、许可缺失均阻止发布。缺少设备或账号时写明未验证范围与责任人，由维护者接受限制并同步发行说明。公开包、标签和同版本 PyPI 文件保持不可变；需修正时发布新版本。

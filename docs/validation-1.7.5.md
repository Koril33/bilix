# 1.7.5 GUI 修复与发布记录

日期：2026-10-11（Asia/Shanghai）。维护者指定修复六处界面细节并发布，沿用简化检查，不扩大到下载内核的全面回归。

## 本版修复

- 通知和右键详情共用展示代码；任务、尝试、输出和中文批次摘要一致，已清除记录有可读回退。
- 标题栏关闭/Alt+F4 默认进入托盘，下载继续；无托盘时普通最小化。文件及托盘菜单退出明确停止并等待线程；拒绝退出后仍可继续下载。关闭或最小化到托盘偏好关闭后，标题栏关闭执行退出。
- 账号状态使用只读标签，按完整文本计算宽度、长文本省略并显示提示；菜单保留账号操作。
- Qt 进度条显式使用水平绘制，从左到右；菜单按钮删除文字内的重复箭头，只保留控件自身的箭头。
- 帮助里的独立关于窗口显示 BiliX、版本、官网、GitHub、dingjinghui 和 dingjinghui33@163.com；设置里的诊断页只负责诊断。

下载内核、CLI 行为、依赖范围、FFmpeg 和公开下载权限不变。版本统一为 1.7.5。

## 已执行的简化检查

- Windows / CPython 3.14.8 / Qt 6.11.2：49 项相关 GUI 检查通过。新增 9 项定向用例覆盖通知/来源失败/清除记录、关闭不取消及无托盘回退、显式退出、账号与菜单、关于与诊断、浅深色两种模式下音视频进度实际像素填充方向。
- Windows 原生窗口在当前 125% 缩放、700×540 逻辑尺寸检查浅深色进度、单一菜单箭头、完整账号展示、通知详情与独立关于窗口；下载模拟运行期间关闭进托盘、恢复并显式退出通过。
- Ubuntu 22.04 / X11（xcb）原生窗口在当前 100% 缩放下复核通知详情、独立关于、主题进度及账号展示，关闭进托盘不取消、恢复与菜单退出通过。无托盘回退另由上述定向用例检查。
- CPython 3.11.2 独立安装本版 wheel，安装路径与版本、CLI 版本和 GUI 离线启动检查通过。
- 相关 Python 文件 Ruff 检查/格式、文档相对链接和工作树 Gitleaks 8.30.1 扫描通过，秘密扫描为 0 项。
- 账号与媒体结果均为本地可控模拟，不使用真实 token 或传输媒体；原生截图和本地结果位于忽略目录 `build/release-1.7.5/`。

未重复真实账号/下载权限、完整安装故障、原生 IME/全部 DPI、Linux 多发行版/Wayland 或大列表性能矩阵。单次模拟不代表操作系统通知必定送达。

## 构建与发布状态

发行集合沿用八项：Windows GUI 绿色版、安装器、许可/配套源码 ZIP，Linux deb、配套源码，以及 CLI ZIP、Python wheel/sdist。以最终 `release-manifest.json` 和 `SHA256SUMS.txt` 为准；网站由维护者部署，Gitea 同步代码与标签。

## 最终组装与公开发布

2026-10-11 已正式发布。源码提交 `7f0c151fe78542f2ca777b6b7fafe6c8ecebdfdb`，标签 `v1.7.5` 与代码已同步 GitHub 和 Gitea。以下为公开后补记；标签及公开文件不变，发行源码中的本记录保留打包时的候选快照。

- Windows GUI onefile/standalone 与 Ubuntu 22.04 GUI 最终冻结程序离线启动检查退出码均为 0；Windows CLI 新版本构建及原有入口/帮助/版本/FFmpeg/补全检查通过，编译报告核对不包含 Qt。Windows 安装器由通过启动检查的 standalone 程序打包。
- 完整八项发行文件经原有集合脚本核对归档路径、许可、版本、大小和 SHA256，证据为 `assembly.log`、`artifact-verification.json`。Windows 配套源码与 Python sdist 各有 144 份、Linux 配套源码有 143 份选定文件与标签工作区逐字节一致；wheel 的 43 份程序/资源文件与当前源文件一致，见 `source-verification.json`。
- [GitHub v1.7.5](https://github.com/Koril33/bilix/releases/tag/v1.7.5) 为最新正式发行。匿名页面可访问，认证 API 核对八项产物及两个清单文件的大小和 SHA256 全部一致，清单与校验文件匿名完整回下载通过；未完整回下载全部 GitHub 大型二进制。证据为 `public-verification.json`。
- [PyPI 1.7.5](https://pypi.org/project/djhx-bilix/1.7.5/) wheel/sdist 两项完整回下载，SHA256 与最终清单一致，Python 版本及 GUI extra 元数据通过。JSON 查询短暂出现旧的 404 缓存，使用官方 API 的等价规范化包名及 simple 索引核对实际文件，没有替换公开文件。
- 独立 CPython 3.11.2 环境重新安装公开回下载的 wheel，安装版本、CLI 版本和 GUI 离线启动均通过，证据为 `pypi-verification.json`、`public-wheel-smoke.json`。
- 本轮材料和证据位于忽略目录 `dist/release-1.7.5/`、`build/release-1.7.5/`。Ubuntu 构建 VM 已正常关闭。本版未修改或部署网站。

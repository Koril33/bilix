# 开发交接：从零开始

本文面向没有会话上下文的开发人员或 AI。仓库提供 Bilibili CLI 与 PySide6 GUI，唯一业务实现为 `src/djhx_bilix`。所有当前文档从 [README.md](README.md) 进入。

当前源码版本为 **1.7.9**。发行、各渠道上线和验收范围见 [validation-1.7.9.md](validation-1.7.9.md)，portable 修复与旧版一次手动迁移见 [portable-update-fix.md](portable-update-fix.md)。开始修改前查看 [workflow-issues.md](workflow-issues.md) 与 [backlog.md](backlog.md)，不要把源码版本号等同于发布已经完成。

## 1. 先确定源码身份

在仓库根目录执行：

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
Get-Content src/djhx_bilix/__init__.py
```

读适用的 `AGENTS.md`（若存在）和 [architecture.md](architecture.md)。源码版本以 `__init__.py` 为准，已发布范围以 CHANGELOG/发行页与当版验收为准；历史指南只用于追溯决策。

本地工作树可能含其他正在进行的修改，保持它们；不要用 reset/clean 为验证制造空白环境。公开版本/标签保持不可变，修复用新版本发布。

## 2. 建立环境并验证

需要 Git、uv，Python 支持范围从 3.11 起。锁定默认解释器为 `.python-version` 中的 3.14.8；若本机 uv 索引不可用，可用已安装解释器完整路径传给 `--python`，不要改锁文件绕过环境问题。

CLI：

```powershell
uv sync --locked
uv run --locked blx --help
uv run --locked python scripts/validate.py --profile cli
```

GUI/共享内核：

```powershell
uv sync --locked --extra gui --group gui-test
uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui
uv run --locked --extra gui bilix-gui
```

统一脚本覆盖文档链接、Ruff、pytest、CLI 行为和 GUI 离线自检，日志位于 `build/validation/`。检查版本身份失败时重装当前源码或对应 wheel，不使用 PYTHONPATH 或旧 egg-info 遮盖。完整 FFmpeg 生成器可用 `BILIX_TEST_FFMPEG` 指定；skip 按 [testing.md](testing.md) 逐项审查。

## 3. 找到改动位置

| 范围 | 位置与职责 |
| --- | --- |
| 前端 | `cli.py`、`gui/app.py` 与 GUI panels/preferences；业务能力进入共享内核 |
| 任务/计划/执行 | `tasks.py`、`planner.py`、`service.py`、`operations.py` |
| 网络/文件/媒体 | `network.py`、`downloader.py`、`media.py`；失败保护旧文件 |
| 登录与配置 | `auth.py`、`credentials.py`、`config.py`；不暴露登录秘密 |
| 更新 | `updater/`、`gui/updates.py`；必须验签、校验身份/大小/哈希，再安装 |
| 构建/发布 | `scripts/`、`scripts/installer/`；八项集合与平台清单 |
| 测试 | `tests/`、`tests/gui/`、`tests/updates/`、`tests/platform/windows/`、`tests/vm/` |
| 官网 | `site/bilix.html`；单文件，不需前端构建 |

CLI/GUI 共用账号、配置和任务契约。队列、并发与会话内暂停续传已实现；跨重启历史/续传仍待开发。

## 4. 构建和验证候选

按 [build.md](build.md) 构建 wheel/sdist 与 Windows CLI，按 [gui-build-and-release.md](gui-build-and-release.md) 构建 Windows GUI 和 Ubuntu 22.04 amd64 deb。Windows 原生工具链与 Linux glibc 基线不可互相替代。

[testing.md](testing.md) 说明检查选择、平台矩阵与通过条件。原生安装/升级、真实 IME/DPI/目录选择器、授权账号下载和公开回验分别留证。使用 [validation-template.md](validation-template.md) 新建当前候选记录，填入真实结果与未测范围。

## 5. 发布与服务器约定

精确顺序见 [releasing.md](releasing.md)：冻结输入 → Python/Windows/Linux 原生构建 → 平台验收 → 八项集合与只读复核 → 本地签名 → 各渠道发布 → APT/官网 → HTTPS 回验。

服务器安装包、更新、APT、官网全部使用 **`bilix@djhx.site`** 和已有 **`~/.ssh/bilix-release-ed25519`**。默认 Windows 路径为 `$env:USERPROFILE/.ssh/bilix-release-ed25519`。不使用服务器密码或管理员账号日常部署，bilix 无 sudo；Nginx/TLS/权限恢复交由管理员。SSH、应用签名和 APT 签名密钥分别保管在仓库外，正常发布不重新生成。

真实密码、私钥、Cookie/token、二维码和签名媒体地址不进入文档、代码、命令文本或日志。部署与 VM 操作按本轮任务范围执行。

## 自动化边界

| 已提交入口 | 覆盖 | 边界 |
| --- | --- | --- |
| `scripts/validate.py` | CLI/GUI 离线回归、相对文件链接、最终集合只读检查 | 不验远程链接/锚点，不证明真实桌面/在线/编译来源 |
| Windows/Linux 构建与打包脚本 | 冻结、启动自检、许可/源码、平台 manifest | 不替代安装/升级与桌面验收 |
| `tests/platform/windows/`、`tests/vm/` | 原生包、更新/安装故障及专用 Linux VM | 需要本轮明确的目标/包/基线；脚本会操作测试机 |
| [prepare_portable_handoff.py](../scripts/prepare_portable_handoff.py)、[validate-portable-handoff.ps1](../tests/platform/windows/validate-portable-handoff.ps1) | 签名测试材料及真实冻结 GUI 交接、保留退出句柄、替换和重启 | 独立测试程序不进入发行包；重跑命令见[修复说明](portable-update-fix.md#重跑冻结交接)，不等同公开网络版本发现 |
| `scripts/update_release.py` | 本地签名与自验 | 需要仓库外已有私钥、下一个正式序号 |
| `scripts/publish_update.py` | bilix 上传版本镜像，验哈希后切 stable | 不发布 GitHub/PyPI/APT/页面 |
| `scripts/publish_apt.sh` | 本地 aptly 快照和 GPG 验签 | 不上传服务器；需保留持久工作目录和旧索引 |
| `scripts/publish_apt.py` | 公有树验签/哈希、bilix 按顺序上传/切换；`--check` 不改服务器 | 本地需 gpg/gpgv；保留实际 public 文件，Contents 仅 `.gz` 时验证解压原文摘要；签名索引分别切换 |
| `scripts/deploy_site.py` | bilix 原子部署首页并保留备份 | 不代替 HTTPS 页面/下载链接回验 |

`build/` 与 `dist/` 被 Git 忽略。各版一次性驱动、原始日志和截图不会随 clone 取得；历史记录引用它们表示本机留证。portable 签名 fixture 已有公开生成入口，其他安装故障 fixture、源码映射和全渠道回下载仍有人工/本地脚本步骤。APT 工具已在 1.7.9 实际发布中使用；导出普通文件、验签、上传及恢复按[发布指南](releasing.md#6-apt-发布)执行。使用历史输入前确认文件存在。

接手结束时更新问题状态、实际检查与证据路径；未完成事项留在对应登记表。

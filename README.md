<p align="center">
  <img src="src/djhx_bilix/assets/bilix-128.png" width="96" height="96" alt="BiliX 项目图标">
</p>

# BiliX

Bilibili 视频下载器，提供命令行及 PySide6 图形界面，支持扫码登录、批量与多 P 下载、清晰度/编码/音轨选择，以及下载后的媒体校验。

[项目主页](https://bilix.djhx.site) · [GitHub](https://github.com/Koril33/bilix) · [PyPI](https://pypi.org/project/djhx-bilix/) · [Windows 下载](https://github.com/Koril33/bilix/releases) · [更新记录](CHANGELOG.md)

## 项目状态

**1.7.7**完善 GUI 偏好、固定快捷键和跟随系统/浅色/深色主题，下载列表显示速度与当前视频的传输剩余时间；GUI 与 CLI 共用估算器。1.7.6 的签名自动更新及 APT 源继续可用，相关说明见[图形版使用说明](docs/gui-usage.md)和[安装与更新](docs/gui-updating.md)。

图形版自 1.6.0 起提供 Windows 10 x64 单文件绿色版、安装版，以及 Ubuntu 22.04/24.04、Debian 12/13 amd64 的 `.deb`。GUI 与 CLI 共用任务内核，支持会话历史、精确快照重试、逐来源选集、冲突预览及配置来源。1.7.1 的真实 IME、DPI 和原生性能证据独立记录，旧版结论见 [1.7.0 验收记录](docs/validation-1.7.0.md)，历史首版文件保留在 [v1.6.0 发行页](https://github.com/Koril33/bilix/releases/tag/v1.6.0)。

Python 包要求 3.11 或更新版本。Windows GUI/CLI 独立程序和 Linux deb 无需安装 Python/Qt；Windows 包内置 FFmpeg，deb 自动安装系统 FFmpeg 依赖。macOS 暂提供 CLI Python 包，GUI 支持后续加入。

## 安装

安装命令行 Python 版本：

```shell
uv tool install djhx-bilix
blx --help
```

也可使用 `pip install djhx-bilix`。`blx` 与 `bilix` 为同一程序的两个命令名；模块入口为 `python -m djhx_bilix`。更新运行 `uv tool upgrade djhx-bilix`。

Windows 从 [GitHub Releases](https://github.com/Koril33/bilix/releases) 下载，并按发行页的 SHA256 校验文件。GUI 绿色版直接运行 EXE，同时保存配套许可证与源码 ZIP；安装版运行 Setup EXE。CLI 解压 ZIP 后，在 PowerShell 当前目录使用 `./bilix.exe`。

Ubuntu/Debian GUI 安装下载的 deb：

```shell
sudo apt install ./djhx-bilix-gui_1.7.7-1_amd64.deb
bilix-gui
```

安装请采用发行页提供的文件并核对 SHA256。也可使用 `uv tool install 'djhx-bilix[gui]'` 或 `pip install 'djhx-bilix[gui]'` 安装 GUI，然后运行 `bilix-gui`。Python 方式需自行安装 FFmpeg 并加入 PATH，或在 GUI 设置/CLI `--ffmpeg` 中指定路径。

从源码开发或运行 GUI：

```shell
uv sync --locked --extra gui --group gui-test
uv run --locked --extra gui bilix-gui
```

GUI 与 CLI 共用下载内核、账号和配置。功能流程见[图形版使用说明](docs/gui-usage.md)，更新设置、手动升级和签名 APT 源见[安装与更新](docs/gui-updating.md)，源码构建发行文件见[GUI 构建与发行](docs/gui-build-and-release.md)。用户配置与下载文件独立保存。

自动更新从 1.7.6 GUI 发行版开始支持，旧版请手动安装新版；不受支持的系统不提供更新兼容。CLI 和 pip/源码环境使用原安装方式升级。

首版的完成情况、最终产物和当时未验证的范围见 [1.6.0 验收记录](docs/validation-1.6.0.md)。桌面与性能基线见 [1.7.1 验收记录](docs/validation-1.7.1.md)。1.7.2 统一图标，1.7.3 改善交互与布局，1.7.7 补齐 GUI 偏好、主题及共享传输反馈；运行中追加、单项取消和结构化输出等继续独立排期，见 [CLI/GUI 开发路线](docs/roadmap.md)。

## 快速开始

```shell
blx auth login
blx auth status
blx info BV1j4411W7F7
blx download BV1j4411W7F7 --dry-run
blx download BV1j4411W7F7 --save videos -q 1080p
```

用手机 Bilibili App 扫码并确认；凭据保存在用户配置目录。默认选择当前账号实际可获取的最高视频清晰度与 AAC 音轨。清晰度/编码不可用时提示降级；要求精确匹配时使用 `--strict`。

```shell
blx download BV12R4y1J75d --page 1,3,5-7
blx download --file videos.txt --quiet
blx download BV1j4411W7F7 --codec HEVC --audio best
blx config
blx doctor
```

多 P 默认选择全部，含 `?p=2` 的链接默认选择 P2；`--page` 优先于链接。批量文件每行一个 URL/BV 号，支持 UTF-8/BOM、空行与 `#` 注释。

已有同名文件默认跳过；`--overwrite` 在新文件完成下载、校验与合并后才替换旧文件。失败保留 `.bilix-*` 临时材料，返回非零退出码。详细参数见 `blx download --help` 与 [用法说明](docs/usage.md)。

## 终端体验

1.5.0 支持 Bash、Zsh、Fish、Windows PowerShell 5.1 与 PowerShell 7 的 Tab 补全，覆盖命令、参数、清晰度、编码、音轨和本地路径。PowerShell 当前会话可这样启用：

```powershell
blx completion powershell | Out-String | Invoke-Expression
```

`blx donwload` 会提示相近的 `download`，参数解析错误返回退出码 `2`。启用方式、持久配置与排错见 [补全说明](docs/completion.md)。

## 文档

| 内容 | 文档 |
| --- | --- |
| 命令、下载参数、配置与退出码 | [使用说明](docs/usage.md) |
| 扫码登录、账号权限与排错 | [账号说明](docs/accounts.md) |
| shell 补全与指令纠错 | [终端体验](docs/completion.md) |
| 1.7.x 范围、任务契约、开发顺序与验收 | [开发指南](docs/cli-gui-ux-review.md) |
| 1.7.8 待开发：下载交互、任务控制、测试验收与部署发布 | [待开发指南](docs/gui-update-guide-1.7.8.md) |
| 1.7.4 列表布局、自动解析与托盘设计 | [更新指南](docs/gui-update-guide-1.7.4.md) |
| 1.7.3 GUI 简洁布局、交互与开发验收 | [更新指南](docs/gui-update-guide-1.7.3.md) |
| 1.7 指南的原型与实测范围 | [设计验证](docs/validation-1.7-design.md) |
| 模块职责与下载事务 | [架构说明](docs/architecture.md) |
| 图形版安装、下载与操作 | [GUI 使用说明](docs/gui-usage.md) |
| GUI 技术与版本选择 | [GUI 技术评估](docs/gui-technology-evaluation.md) |
| Windows/Linux 发行方式与升级方案 | [GUI 发行调研](docs/gui-distribution-and-updates.md) |
| 应用更新已确认方案、双源与 APT 源 | [更新方案](docs/application-update-plan.md) |
| 更新器实现、签名与首次上线步骤 | [更新开发指南](docs/application-update-development.md) |
| GUI 本地构建和打包 | [GUI 构建与发行](docs/gui-build-and-release.md) |
| Ubuntu/Debian 虚拟机验收 | [Linux 测试矩阵](docs/gui-vm-validation.md) |
| Windows 10 虚拟机验收 | [Windows 测试流程](docs/gui-win10-validation.md) |
| 本地开发、测试与构建 | [构建说明](docs/build.md) |
| 持续测试、用例与验收门槛 | [测试规范](docs/testing.md) |
| 每版验收记录格式 | [验收模板](docs/validation-template.md) |
| 1.7.1 候选的完成情况与测试范围 | [1.7.1 验收记录](docs/validation-1.7.1.md) |
| 首个 GUI 版本的最终完成情况 | [1.6.0 复核](docs/validation-1.6.0.md) |
| 功能范围索引与后续方向 | [版本规划](docs/roadmap.md) |
| 版本、产物、校验与发布 | [发布说明](docs/releasing.md) |
| 旧版本与兼容入口 | [迁移说明](docs/releases.md) |
| 贡献代码或报告问题 | [贡献指南](CONTRIBUTING.md) |
| 安全报告与凭据保护 | [安全政策](SECURITY.md) |
| 依赖与 FFmpeg 分发材料 | [第三方声明](THIRD_PARTY_NOTICES.md) |

项目页面源码为 [site/bilix.html](site/bilix.html)，CSS、背景图与脚本内嵌，无需构建；版本查询失败时仍保留发行页链接。官网使用 `https://bilix.djhx.site/`，对应服务器文件 `/var/www/bilix.djhx.site/index.html`；见 [页面维护说明](site/README.md)。

## 开发

```shell
uv sync --locked
uv run blx --help
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
```

GUI 测试需要 `uv sync --locked --extra gui --group gui-test`；无桌面的环境可设置 `QT_QPA_PLATFORM=offscreen`。GUI 发行文件依目标平台分别构建，不把 Windows 编译结果当作 Linux 验证。

统一检查入口为 `uv run --locked python scripts/validate.py --profile cli`；GUI 环境使用 `uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui`。每轮生成独立日志与 JSON/XML 结果，缺少 GUI 测试依赖会失败；完整平台及发布验收按[测试规范](docs/testing.md)执行。

唯一业务实现位于 `src/djhx_bilix`。项目使用本地检查与手动发布，不运行 GitHub/Gitea Actions。发布前须完成 [发布说明](docs/releasing.md) 中的凭据、源码与产物检查。

## 许可与使用边界

项目采用 [GPL-3.0-only](LICENSE)，使用、修改与再分发遵循其条款。软件许可与视频内容的版权、平台授权属于不同事项。

仅下载你拥有访问与保存权限的内容，遵守所在地法律、版权要求与平台条款。程序不绕过账号权限、单独购买权限或 DRM；试看媒体明确拒绝下载。软件按许可证提供，不作担保。

扫码凭据、Cookie、二维码链接与签名媒体地址不应出现在公开问题、日志或提交中。见 [安全政策](SECURITY.md)。

## 致谢

项目参考了 [Bilibili API 资料](https://socialsisteryi.github.io/bilibili-API-collect/)、[BBDown](https://github.com/nilaoda/BBDown) 和 [早期实现](https://blog.csdn.net/weixin_47481982/article/details/127666941)。当前应用图标由维护者原创，源稿见 [bilix.svg](src/djhx_bilix/assets/bilix.svg)；历史图标保存在 [docs/assets](docs/assets/bilix-icon.jpg)。本项目并非 Bilibili 官方产品。

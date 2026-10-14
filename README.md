<p align="center">
  <img src="src/djhx_bilix/assets/bilix-128.png" width="96" height="96" alt="BiliX 项目图标">
</p>

# BiliX

Bilibili 视频下载器，提供命令行及 PySide6 图形界面，支持扫码登录、批量与多 P 下载、清晰度/编码/音轨选择，以及下载后的媒体校验。

[项目主页](https://bilix.djhx.site) · [GitHub](https://github.com/Koril33/bilix) · [PyPI](https://pypi.org/project/djhx-bilix/) · [Windows 下载](https://github.com/Koril33/bilix/releases) · [更新记录](CHANGELOG.md)

## 项目状态

当前已发布版本为 **1.8.0**，新增仅音频、仅无声视频、分别保存、仅封面和媒体附带封面五种下载选择；完整视频仍为默认。界面设计见[1.8.0 指南](docs/gui-update-guide-1.8.0.md)，发行与验收结果见[本版记录](docs/validation-1.8.0.md)。旧绿色版更新问题的一次手动迁移见[说明](docs/portable-update-fix.md#用户迁移)，后续功能见[待办清单](docs/backlog.md)。

Python 包要求 3.11 或更新版本。Windows GUI/CLI 独立程序和 Linux deb 无需 Python/Qt；Windows 包内置 FFmpeg，deb 安装系统 FFmpeg 依赖。原生 GUI 面向 Windows 10 x64 与 Ubuntu 22.04/24.04、Debian 12/13 amd64；macOS 当前提供 CLI Python 包。每版真实验证范围见 [文档索引](docs/README.md#版本验收)。

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
# 将 VERSION 换为发行页所选版本，文件名以下载结果为准。
sudo apt install ./djhx-bilix-gui_VERSION-1_amd64.deb
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

历史设计、各版验收和未测范围保留在 [文档索引](docs/README.md)。GUI 会话内续传不跨重启；公开 JSONL 和持久历史仍待开发。

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

所有文档从 [docs/README.md](docs/README.md) 进入。没有会话上下文的开发人员或 AI 先读 [开发交接](docs/handoff.md)，再按任务选择入口。

| 任务 | 文档 |
| --- | --- |
| CLI、登录与补全 | [使用](docs/usage.md) · [账号](docs/accounts.md) · [补全](docs/completion.md) |
| GUI 使用、安装与更新 | [GUI 使用](docs/gui-usage.md) · [安装/更新/APT](docs/gui-updating.md) |
| 共享内核与模块职责 | [架构](docs/architecture.md) |
| 从源码开发与构建 | [开发/CLI](docs/build.md) · [GUI 原生包](docs/gui-build-and-release.md) |
| 统一回归、原生平台与结果规则 | [测试](docs/testing.md) |
| 最终产物、签名、发布与部署 | [维护者流程](docs/releasing.md) |
| 已发布范围、未实现功能、当前缺陷 | [版本范围](docs/roadmap.md) · [backlog](docs/backlog.md) · [workflow issues](docs/workflow-issues.md) |
| 当版证据、历史设计/研究 | [完整索引](docs/README.md) |
| 贡献、安全与第三方材料 | [贡献](CONTRIBUTING.md) · [安全](SECURITY.md) · [许可材料](THIRD_PARTY_NOTICES.md) |

官网源码为 [site/bilix.html](site/bilix.html)，样式、图像与脚本内嵌，无需构建；页面维护与浏览器检查见 [site/README.md](site/README.md)。官网、安装包、签名更新和 APT 的服务器部署统一使用 `bilix@djhx.site` 与现有专用 SSH 密钥，精确顺序见 [发布流程](docs/releasing.md)。

## 开发

CLI 日常验证：

```powershell
uv sync --locked
uv run --locked python scripts/validate.py --profile cli
```

GUI 或共享内核：

```powershell
uv sync --locked --extra gui --group gui-test
uv run --locked --extra gui --group gui-test python scripts/validate.py --profile gui
```

统一入口生成独立日志与 JSON/XML，核对版本身份，GUI 依赖缺失直接失败。完整 FFmpeg、skip 处理、原生桌面与发布检查见 [testing.md](docs/testing.md)。项目使用本地检查与手动发布，不运行 GitHub/Gitea Actions；推送代码或标签不会自动部署。

## 许可与使用边界

项目采用 [GPL-3.0-only](LICENSE)，使用、修改与再分发遵循其条款。软件许可与视频内容的版权、平台授权属于不同事项。

仅下载你拥有访问与保存权限的内容，遵守所在地法律、版权要求与平台条款。程序不绕过账号权限、单独购买权限或 DRM；试看媒体明确拒绝下载。软件按许可证提供，不作担保。

扫码凭据、Cookie、二维码链接与签名媒体地址不应出现在公开问题、日志或提交中。见 [安全政策](SECURITY.md)。

## 致谢

项目参考了 [Bilibili API 资料](https://socialsisteryi.github.io/bilibili-API-collect/)、[BBDown](https://github.com/nilaoda/BBDown) 和 [早期实现](https://blog.csdn.net/weixin_47481982/article/details/127666941)。当前应用图标由维护者原创，源稿见 [bilix.svg](src/djhx_bilix/assets/bilix.svg)；历史图标保存在 [docs/assets](docs/assets/bilix-icon.jpg)。本项目并非 Bilibili 官方产品。

# BiliX

Bilibili 命令行视频下载器，支持扫码登录、批量与多 P 下载、清晰度/编码/音轨选择，以及下载后的媒体校验。

[项目主页](https://djhx.site/project/bilix.html) · [GitHub](https://github.com/Koril33/bilix) · [PyPI](https://pypi.org/project/djhx-bilix/) · [Windows 下载](https://github.com/Koril33/bilix/releases) · [更新记录](CHANGELOG.md)

## 项目状态

**1.5.0** 增加 Tab 补全与相近指令提示；源码、文档和项目页面统一在本仓库维护。发行文件以 PyPI 与 GitHub Releases 为准。

Python 要求 3.11 或更新版本。Windows 独立程序无需安装 Python；Linux/macOS 使用 Python 包并自行提供 FFmpeg。

## 安装

推荐安装已经发布的 Python 版本：

```shell
uv tool install djhx-bilix
blx --help
```

也可使用 `pip install djhx-bilix`。`blx` 与 `bilix` 为同一程序的两个命令名；模块入口为 `python -m djhx_bilix`。更新运行 `uv tool upgrade djhx-bilix`。

Windows 从 [GitHub Releases](https://github.com/Koril33/bilix/releases) 下载，并按发行页的 SHA256 校验文件。PowerShell 当前目录使用 `./bilix.exe`。Windows 包使用内置 FFmpeg；其他系统请安装 FFmpeg 并加入 PATH，或用 `--ffmpeg` 指定路径。

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
| 模块职责与下载事务 | [架构说明](docs/architecture.md) |
| 本地开发、测试与构建 | [构建说明](docs/build.md) |
| 版本、产物、校验与发布 | [发布说明](docs/releasing.md) |
| 旧版本与兼容入口 | [迁移说明](docs/releases.md) |
| 贡献代码或报告问题 | [贡献指南](CONTRIBUTING.md) |
| 安全报告与凭据保护 | [安全政策](SECURITY.md) |
| 依赖与 FFmpeg 分发材料 | [第三方声明](THIRD_PARTY_NOTICES.md) |

项目页面源码为 [site/bilix.html](site/bilix.html)，沿用线上布局与背景图，更新当前命令说明。CSS、背景图与脚本内嵌，无需构建；版本查询失败时仍保留发行页链接。发布时复制到现有网站的 `/project/bilix.html`，见 [页面维护说明](site/README.md)。

## 开发

```shell
uv sync --locked
uv run blx --help
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
```

唯一业务实现位于 `src/djhx_bilix`。项目使用本地检查与手动发布，不运行 GitHub/Gitea Actions。发布前须完成 [发布说明](docs/releasing.md) 中的凭据、源码与产物检查。

## 许可与使用边界

项目采用 [GPL-3.0-only](LICENSE)，使用、修改与再分发遵循其条款。软件许可与视频内容的版权、平台授权属于不同事项。

仅下载你拥有访问与保存权限的内容，遵守所在地法律、版权要求与平台条款。程序不绕过账号权限、单独购买权限或 DRM；试看媒体明确拒绝下载。软件按许可证提供，不作担保。

扫码凭据、Cookie、二维码链接与签名媒体地址不应出现在公开问题、日志或提交中。见 [安全政策](SECURITY.md)。

## 致谢

项目参考了 [Bilibili API 资料](https://socialsisteryi.github.io/bilibili-API-collect/)、[BBDown](https://github.com/nilaoda/BBDown) 和 [早期实现](https://blog.csdn.net/weixin_47481982/article/details/127666941)。原图标保存在 [docs/assets](docs/assets/bilix-icon.jpg)。本项目并非 Bilibili 官方产品。

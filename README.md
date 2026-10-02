# BiliX

一个支持扫码登录、选集和编码选择的 Bilibili 命令行视频下载器。

[项目主页](https://djhx.site/project/bilix.html) · [GitHub](https://github.com/Koril33/bilix) · [PyPI](https://pypi.org/project/djhx-bilix/) · [下载 Windows exe](https://github.com/Koril33/bilix/releases)

![BiliX](https://raw.githubusercontent.com/Koril33/bilix/main/doc/bilix-icon.jpg)

## 安装

Python 3.11 或更新版本，推荐通过 uv tool 安装：

```shell
uv tool install djhx-bilix
blx --help
blx --version
```

`blx` 和 `bilix` 是同一程序的两个命令名。也支持 `pip install djhx-bilix` 和 `python -m djhx_bilix`。一次性运行使用 `uvx --from djhx-bilix blx --help`。更新使用 `uv tool upgrade djhx-bilix`。

Windows exe 使用相同的命令和功能，将下文的 `blx` 替换为 `bilix.exe`。Windows 包内附 FFmpeg；Linux/macOS 需要安装 FFmpeg 并加入 PATH，或使用 `--ffmpeg` 指定路径。

1.4.1 使用统一的 `src` 实现，支持 Python 3.11–3.14，并修复英文 Windows 下中文输出的编码问题。旧版迁移及变更见 [发行说明](https://github.com/Koril33/bilix/blob/main/docs/releases.md)。开发时使用 `uv sync --locked`、`uv run blx`；本地 wheel/exe 的构建方法见 [打包与验证](https://github.com/Koril33/bilix/blob/main/docs/build.md)。

## 使用

查看视频信息及当前账号可获取的清晰度：

```shell
blx info https://www.bilibili.com/video/BV1j4411W7F7
blx info BV1j4411W7F7 --json
```

下载、指定目录、清晰度及编码：

```shell
blx download BV1j4411W7F7
blx download BV1j4411W7F7 -s videos -q 480p --codec HEVC
blx download BV1j4411W7F7 -q 1080p --strict
blx download BV1j4411W7F7 --dry-run
blx download BV1Wv411y7o9 -q HDR --strict
blx download BV13L4y1K7th -q 126 --audio dolby --strict
blx download BV1pB4y1o7TF -q 1080p --audio flac --strict
```

默认清晰度为当前账号可获取的最高视频流。支持 `auto`、`360p`、`480p`、`720p`、`1080p`、`1080p+`、`1080p60`、`4k`、`HDR`、`杜比视界`、`8k` 和数字 id（如 `16`、`80`、`120`、`126`）。编码可选 `auto`、AVC、HEVC、AV1，忽略大小写；自动编码优先选择该清晰度的 AVC，其次 HEVC/AV1，所以 HDR/杜比视界/8K 不会因为默认 AVC 而降级。指定清晰度或编码不可用时会明确提示降级；使用 `--strict` 可让它直接失败。

默认音频为最高码率 AAC。`--audio flac` 选择 FLAC 无损音轨，`--audio dolby` 选择 Dolby 音轨，`--audio best` 按 FLAC、Dolby、AAC 的顺序选择。显式选择的视频/账号没有该音轨时直接失败；可先用 `info` 查看可获取的音轨。保留原始编码，不转码；非 AAC 音轨会在文件名中标明，播放器需要支持对应格式。杜比视界合并会保留其配置元数据。

页面列出的清晰度可能需要登录或会员，实际下载取决于账号权限与视频提供的流；无登录时一般可获取 360P/480P，普通账号通常可获取 720P/1080P。不同视频的清晰度、编码和音轨权限可能不同，先用 `info` 检查。普通账号的完整流程、影视权限和排错见 [账号使用说明](https://github.com/Koril33/bilix/blob/main/docs/accounts.md)。本工具不会绕过权限。

多 P 默认下载全部集数，链接含 `?p=2` 时默认只下载 P2。`--page` 会覆盖链接中的选集：

```shell
blx download BV12R4y1J75d --page all
blx download BV12R4y1J75d --page 1,3,5-7
blx download "https://www.bilibili.com/video/BV17x411w7KC?p=2"
```

支持多个地址、BV 号、Bilibili 的 av/ep/ss/md 地址及 b23.tv 短链接。`ep` 下载单集，`ss`/`md` 默认下载全部正片选集，可用 `--page` 选择电影语言版本或番剧集数；合集的信息展示以第一个正片选集为准，避免将预告片权限当成正片权限。番剧/电影下载需要账号拥有相应权限；大会员并不包含所有单独付费影片。仅有试看权限或使用 DRM 的媒体会明确拒绝下载。批量列表为 UTF-8 文件，每行一个 URL/BV 号，空行和 `#` 注释会忽略：

```shell
blx download BV1j4411W7F7 BV1yt4y1Q7SS -q 360p
blx download --file videos.txt
blx info --file videos.txt --json
```

已有文件默认跳过。`--overwrite` 仅在新文件完成传输、媒体校验和合并后替换旧文件。失败返回非零退出码，并保留目标目录中的 `.bilix-*` 临时目录；错误消息会说明位置。旧版留下的坏文件需要用 `--overwrite` 重新下载。

```shell
blx download BV1j4411W7F7 --overwrite
blx download BV1j4411W7F7 --quiet
```

默认目录为用户 Downloads 下的 `djhx-bilix`。文件名包含视频标题、BV/CID、清晰度和实际编码，用于区分视频和选集。

## 登录和配置

```shell
blx auth login
blx auth status
blx auth status --json
blx auth logout
blx config
blx doctor
```

`auth login` 在用户配置目录中生成二维码，打开终端显示的 PNG 路径，用手机 App 扫码并确认。凭据保存在该目录的 `token.txt`，终端不输出 Cookie、登录响应或刷新地址。`auth status` 区分普通账号、大会员、年度大会员及失效登录；只有会员状态有效时才认定为大会员。`--json` 输出筛选后的账号信息，不含凭据。退出删除本地凭据。

兼容旧版 `blx` 写在同一用户配置目录中的 `token.txt`，读取时会清除 Set-Cookie 的 Path/Expires 等属性，无需重新扫码，也不会改写原文件。旧版根目录 `cookie.txt` 不再自动读取，请重新扫码。

`blx config` 显示配置文件位置。在该位置创建可选的 `config.toml`：

```toml
download_dir = "D:/Videos/BiliX"
ffmpeg = "C:/Tools/ffmpeg/bin/ffmpeg.exe"
```

`BILIX_CONFIG_DIR`、`BILIX_DOWNLOAD_DIR`、`BILIX_FFMPEG` 可覆盖配置；`--save`、`--ffmpeg` 优先于配置。`doctor` 不访问网络，用于检查版本和 FFmpeg。

## 旧命令兼容与开发

`blx video URL -i`、`blx user --login`、`bilix.exe URL`、`bilix.exe -i URL`、`bilix.exe -o videos.txt` 等常见旧写法仍转入同一实现。新版根目录不再保留业务脚本，`python main.py` 改用 `uv run blx`。旧 exe 自更新脚本已移除，请通过发行页更新。

唯一业务实现为 `src/djhx_bilix`。详见 [架构说明](https://github.com/Koril33/bilix/blob/main/docs/architecture.md)、[测试与 Windows 打包](https://github.com/Koril33/bilix/blob/main/docs/build.md)、[1.4.0 验证记录](https://github.com/Koril33/bilix/blob/main/docs/validation-1.4.0.md)。

项目不使用 GitHub/Gitea Actions。检查和打包在本地执行，验证通过后手动上传发行文件；推送提交或版本标签不会自动检查、构建或发布。

```shell
uv sync --locked
uv run pytest -q
uv run ruff check src tests scripts
uv build
```

## 声明

本项目仅用于学习、研究与技术交流目的，严禁用于任何商业用途或违反中国大陆及其他国家和地区相关法律法规的行为。

- 本项目不提供任何盗版内容，也不鼓励用户下载、传播受版权保护的内容。
- 使用本工具所造成的一切后果，由使用者本人承担。
- 请在下载前获得原作者授权，尊重原创和内容版权。
- 若您不同意本声明，请不要使用或传播本项目中的任何内容。
- 开发者对任何由于使用本项目所引起的直接或间接损失不承担任何法律责任。

项目许可证见 [LICENSE](LICENSE)。

## 感谢

项目开发过程中参考了 [Bilibili API 资料](https://socialsisteryi.github.io/bilibili-API-collect/)、[BBDown](https://github.com/nilaoda/BBDown) 和 [早期实现参考](https://blog.csdn.net/weixin_47481982/article/details/127666941)。

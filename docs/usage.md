# 命令与下载用法

示例使用 `blx`；`bilix` 为同一入口。Windows 独立程序使用 `bilix.exe`（PowerShell 当前目录写 `./bilix.exe`）。


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

页面列出的画质不一定可下载，实际流取决于当前账号与视频权限，先用 `info` 检查。登录、会员与单独购买的权限范围见 [accounts.md](accounts.md)；本工具不绕过权限。

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

已有普通文件默认跳过，并明确标记“已存在，未校验”。`--overwrite` 仅在新文件完成传输、媒体校验和合并后替换旧文件。输出位置已被目录等非普通文件占用时直接失败。失败返回非零退出码，并保留目标目录中的 `.bilix-*` 临时目录；错误消息会说明位置。旧版留下的坏文件需要用 `--overwrite` 重新下载。

`--dry-run` 读取实际媒体流和完整输出计划，显示新建、跳过、替换或阻塞；不下载媒体、不调用 FFmpeg、不创建保存目录。重复输出路径会提示。预览只代表读取时刻，执行和提交时会再次检查。

Ctrl+C（Windows 也支持 Ctrl+Break）会协作取消整个批次，等待当前请求/媒体处理停止并清理本次临时材料，已完成文件不回滚；退出码为 130。汇总分开列出来源读取失败和已发现的媒体任务，未读取来源的媒体数量标记为未知。GUI 的追加队列、单项暂停/会话内续传与精确重试见 [图形版说明](gui-usage.md)。CLI 没有交互暂停按钮；跨重启队列/续传和公开 JSONL 实时事件尚未实现，见 [backlog.md](backlog.md)。

```shell
blx download BV1j4411W7F7 --overwrite
blx download BV1j4411W7F7 --quiet
```

默认目录为用户 Downloads 下的 `djhx-bilix`。文件名包含视频标题、BV/CID、清晰度和实际编码，用于区分视频和选集。

## 配置与退出码

`blx config` 显示 `config.toml` 的准确位置、文件值、当前生效值和覆盖来源；配置不需要随仓库提交。`blx doctor` 检查当前生效的 FFmpeg 是否能执行。

```toml
download_dir = "D:/Videos/BiliX"
ffmpeg = "C:/Tools/ffmpeg/bin/ffmpeg.exe"
naming_template = "{title}"
concurrency = 1
# 可选本地代理；不要在公开示例写认证信息。
proxy = "http://127.0.0.1:7890"
```

`BILIX_CONFIG_DIR` 改变配置目录；`BILIX_DOWNLOAD_DIR`、`BILIX_FFMPEG`、`BILIX_PROXY` 覆盖对应文件值，命令行的 `--save` 和 `--ffmpeg` 优先。默认配置位置由 platformdirs 决定。`concurrency` 为 1–4，CLI/GUI 共用；命名模板允许 `{title}`、`{owner}`、`{part}`、`{page}`、`{bvid}`、`{cid}`、`{quality}`、`{codec}`，清理路径字符并保留身份后缀。代理支持 HTTP/HTTPS/SOCKS5/SOCKS5H，留空沿用环境代理。这些设置当前通过配置文件或 GUI 修改，没有同名 CLI 参数。

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功，包含已有文件跳过与 dry-run |
| 1 | 业务、配置、网络或媒体失败；批量中任一项失败也返回 1 |
| 2 | 命令/参数解析错误；直接不带参数显示帮助也可能返回 2 |
| 130 | 在受保护的命令处理中取消操作 |

完整参数以 `blx COMMAND --help` 为准。参见 [账号说明](accounts.md)、[补全说明](completion.md) 与 [迁移说明](releases.md)。

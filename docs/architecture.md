# 架构与下载事务

项目的唯一业务实现位于 `src/djhx_bilix`。`blx`、`bilix`、`python -m djhx_bilix` 和 Windows exe 均进入 `cli.main`。构建脚本位于 `scripts`，测试位于 `tests`，根目录保留项目元数据和说明文件。

| 模块 | 职责 |
| --- | --- |
| `cli.py`、`presentation.py` | 参数、终端展示、批量汇总和退出码 |
| `completion.py` | 离线参数/路径候选、shell 补全脚本与 PowerShell 参数传递 |
| `models.py`、`errors.py` | 数据模型及可以安全展示的领域错误 |
| `urls.py`、`filenames.py` | URL、选集及跨平台文件名校验 |
| `config.py`、`auth.py`、`credentials.py` | 显式配置加载、扫码登录、凭据存储及旧凭据格式兼容 |
| `bilibili/client.py` | 页面/API 请求及短链接解析 |
| `bilibili/parser.py` | 统一适配页面/API 的播放数据和影视元数据 |
| `planner.py` | 选集、清晰度、编码、音频和文件路径的纯计算 |
| `downloader.py` | 流传输、重试、备用 CDN 和字节数校验 |
| `media.py` | FFmpeg 定位、包扫描、时长校验及合并 |
| `service.py` | 编排下载事务及原子提交 |
| `assets/ffmpeg.exe` | Windows 内置的 FFmpeg |

业务模型构造和模块导入没有网络请求，也不创建用户目录。`info` 和下载共用页面解析器。选集发现只获取初始页面，随后逐集获取和下载；当前选集已获取播放数据时会复用。单集失败会记录错误并继续处理后续选集，整批最终返回非零退出码。

## 下载事务

1. 获取页面和选集，生成实际清晰度、编码与最高码率音频的下载计划。
2. 已有目标默认跳过；`--overwrite` 表示允许在最后提交阶段替换。
3. 在目标目录下创建唯一 `.bilix-*` 临时目录，使提交保持在同一文件系统。
4. 并行下载音视频，显式等待两个 Future；流失败最多尝试三次，并轮换服务器提供的备用 URL。
5. 校验收到的字节数与 `Content-Length`；缺少该头时使用接口中的 `size`（若存在）。无论是否有长度信息，下一步仍进行媒体校验。
6. FFmpeg 用 `-xerror -err_detect explode` 扫描每个流的全部包，生成经过检查的临时 MP4。进度日志中的最终包时间戳与页面时长比较，误差不得超过 2 秒；音视频时长差也不得超过 2 秒。不能只相信 MP4 头里的时长。
7. 明确映射视频和音频轨，合并临时结果并同步文件缓冲。
8. 允许覆盖时使用 `os.replace`；默认模式在 Windows 使用不会覆盖已有文件的 rename，在 POSIX 使用原子 hard link，避免并发提交互相覆盖。
9. 提交成功才清理临时目录。失败保留临时文件，并返回非零退出码；已有 MP4 始终保留到新结果校验成功。

FFmpeg 校验采用包扫描和时间轴检查，无需解码 HEVC/AV1；这适配内置 FFmpeg 的 stream-copy 能力。回归验证另用完整 FFmpeg 解码生成的测试文件。包扫描不能证明每一帧的视觉内容正确，也不会绕过视频权限。

UGC、旧 PGC SSR、新版 `playurlSSRData.data.result` 共用 `apply_playback`。影视标题和 season_id 从 Next.js 的 `__NEXT_DATA__` 补全；播放脚本的变量引用只作识别，不执行 JavaScript。PGC SSR 缺少流时使用 episode_id 补查官方网页播放接口。仅有试看或 DRM 状态的媒体在生成下载计划前拒绝下载。

自动编码先确定可获取的最高/指定清晰度，再在该清晰度内依次选择 AVC、HEVC、AV1。音频分别读取普通 AAC、`dash.dolby.audio` 和 `dash.flac.audio`，显式选择不可用音轨时失败。包扫描和最终合并都使用 `-strict unofficial`，保留 MP4 的 Dolby Vision 配置记录；只有在最后合并时添加该参数已经太晚。集成测试用合成媒体验证两次合并都保留配置，在线验证还比较原始视频包与最终视频包的 SHA-256。

该参数要求可在 [FFmpeg 的 MOV 封装器源码](https://github.com/FFmpeg/FFmpeg/blob/n7.1/libavformat/movenc.c#L2615-L2623) 中核对。

默认跳过已存在文件时不检查历史文件的完整性。如果旧版本生成过坏文件，需要使用 `--overwrite` 重新下载。残留 `.bilix-*` 可以手动检查或删除；目前不实现自动续传，也不自动删除失败材料。

## 凭据边界

- 凭据只保存在用户配置目录中的 `token.txt`。POSIX 下新文件权限为 `0600`；Windows 使用用户目录权限。
- 登录成功不输出响应正文、Cookie、二维码 key 或刷新地址。Set-Cookie 只提取 cookie name/value，忽略 Path、HttpOnly 等属性。
- 兼容旧 `token.txt` 的逗号拼接 Set-Cookie 格式，在内存中规范化 Cookie 请求头，不改写用户已有凭据；空凭据和换行注入会明确失败。
- 账号状态只导出白名单字段。会员 `type` 用于区分月度/年度，是否有效取决于 `status`；登录失效通过数值错误码识别。
- API 和传输层将第三方异常转换为不包含 headers、响应正文和签名 URL 的错误。CLI 关闭自动富文本 traceback，不输出异常局部变量。
- 公开 JSON 信息排除 CDN 地址；下载 CDN 请求不携带账号 Cookie。短链接解析不携带账号 Cookie。
- 旧根目录 `cookie.txt` 不自动读取；需要重新扫码登录。删除散落的旧程序不会删除用户原有 Cookie 或下载文件。

## 兼容入口

保留 `blx video ...`、`blx user --login/--logout/-i`，以及 exe/Python 入口直接传 URL、`-i`、`-o`、`--login`、`--logout`、`-u` 的常用写法。它们只将参数转入新 CLI，不保留第二套业务逻辑。

旧版根目录 Python 模块、旧日志模块与旧自更新器已移除。`python main.py` 应改为 `uv run blx` 或 `python -m djhx_bilix`。exe 自更新不沿用删除/替换自身的旧脚本；通过发行页更新 exe，Python 安装通过 `uv tool upgrade djhx-bilix` 更新。

未知命令交给 Typer 的相近指令提示；只有 URL/BV 输入和旧版参数会转入下载入口，避免拼错命令被当成下载地址。命令和选项的补全候选来自同一 Typer 命令树，清晰度候选来自 `QUALITY_NAMES`，补全过程不访问网络或配置凭据。PowerShell 脚本通过 AST/JSON 传入参数，保留中文、空格与引号，并在调用后恢复环境变量。

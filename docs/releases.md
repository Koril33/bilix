# 版本与迁移

## 1.4.1

修复英文 Windows 和重定向输出使用 cp1252 等编码时，中文或 emoji 帮助触发 `UnicodeEncodeError`、导致 exe 无法启动的问题。CLI 入口将标准输出和错误输出设置为 UTF-8；通过 `python -X utf8 -m nuitka` 编译，避免 isolated 模式忽略 `PYTHONUTF8` 环境变量。

新增非 UTF-8 编码环境和重定向输出的回归检查，将同样的检查纳入 exe 构建。1.4.0 已发布的 Python 包和标签保留，Windows exe 使用通过修复后检查的 1.4.1 产物。

更新本地 uv tool：

```shell
uv tool install --force --upgrade djhx-bilix==1.4.1
blx --version
blx doctor
blx auth status
```

Windows exe 从 [GitHub Releases](https://github.com/Koril33/bilix/releases) 下载。此次更新保留已有登录配置和下载文件。1.4.0 的完整迁移说明仍适用于 1.4.1。

## 1.4.0

本次更新将命令行、Python 包和 Windows exe 收拢到 `src/djhx_bilix` 的同一实现，恢复长期未更新的下载、登录和打包流程。

### 下载可靠性

- 等待音视频两路传输完成，检查 HTTP 状态、字节数和完整媒体时间轴；截断、空响应、残缺媒体及合并失败返回失败。
- 文件下载在目标目录下的唯一临时目录中完成。默认跳过已有文件；显式覆盖时只在新文件完成校验、合并和同步后替换旧文件。
- 流传输支持有限重试和备用地址。长视频不会因为将流传输超时错误当成总下载时限而在 5 分钟后中止。
- 多 P 和批量任务逐项处理；中间选集失败会继续后续任务，最终汇总并返回非零退出码。

### 账号、会员和媒体

- 扫码登录保存规范化 Cookie，兼容旧 token.txt 的 Set-Cookie 拼接格式；登录响应、刷新地址、Cookie 和签名 CDN 地址不进入终端和公开 JSON。
- 账号状态区分普通账号、有效大会员、年度大会员和失效登录。试看及 DRM 媒体在传输前拒绝，避免把试看结果当成完整正片。
- 适配新版影视 SSR 和 Next.js 元数据，影视页面缺少流时补查播放接口；支持 ep/ss/md 正片选集。
- 影视合集的信息展示使用正片权限，避免免费预告片造成误判；接口格式异常不会中断后续批量地址。
- 自动编码先保留可获取的最高清晰度，再选择 AVC、HEVC 或 AV1。支持明确选择 FLAC/Dolby 音轨和保留杜比视界配置元数据。
- 提供普通账号、大会员和匿名会话的回归测试；具体清晰度及影片权限以当前会话实际返回的流为准。

### CLI 和安装

- 新增统一的 `download`、`info`、`auth`、`config`、`doctor` 命令，支持下载计划、严格清晰度/编码要求、JSON 信息、选集和 UTF-8 BOM 列表文件。
- 支持 `-h` 和根入口补全命令；结果路径保持完整一行，便于复制。同名目录明确报错并保护内容。
- `blx`、`bilix`、`python -m djhx_bilix` 和 exe 进入同一 CLI。运行时不安装 Nuitka，不在模块导入时创建用户目录或访问网络。
- Windows 包含 FFmpeg。exe 使用独立 CPython 3.11/Nuitka 4.2.2 环境构建，并自动检查中文/空格路径、最小 PATH、帮助和错误退出码。
- CI 覆盖 Windows/Linux、Python 3.11–3.14，以及合成媒体和 Windows exe 构建。媒体测试分别检查传输完整性、FLAC/E-AC-3 和杜比视界元数据。

### 从旧版本升级

新版要求 Python 3.11 或更新版本，建议使用 uv tool：

```shell
uv tool install --force --upgrade djhx-bilix==1.4.0
blx --version
blx auth status
blx doctor
```

日常更新可用 `uv tool upgrade djhx-bilix`。如果 Python 版本过低，可在安装命令中加 `--python 3.11`；uv 会选择或安装该版本的解释器。Windows exe 从 [GitHub Releases](https://github.com/Koril33/bilix/releases) 下载新文件。

| 旧用法或行为 | 新版用法或行为 |
| --- | --- |
| `python main.py` | `uv run blx` 或 `python -m djhx_bilix` |
| 根目录业务脚本/第二套实现 | 唯一实现为 `src/djhx_bilix` |
| `blx video URL` | 仍兼容；推荐 `blx download URL` |
| `blx user --login` / `blx user` | 仍兼容；推荐 `blx auth login` / `blx auth status` |
| exe 直接传 URL、`-i`、`-o` | 仍转入相同 CLI |
| 默认尝试固定清晰度 | 默认选择实际可获取的最高流；精确要求加 `--strict` |
| 根目录 cookie.txt | 不再自动读取，请重新扫码 |
| 用户配置目录 token.txt | 自动在内存中兼容旧格式，无需重新登录 |
| 删除/替换自身的 exe 自更新脚本 | 通过发行页更新 exe |
| 旧版同名下载文件 | 默认跳过；需要重新下载时使用 `--overwrite` |

下载文件和用户配置目录不随升级删除。旧版本生成的文件不会在默认跳过时重新验证；发生过下载完整性问题的文件建议显式覆盖重新下载。失败保留 `.bilix-*` 临时材料，目前不实现断点续传。

具体账号流程见 [普通账号与会员权限](accounts.md)，构建和发布方法见 [打包与验证](build.md)，模块职责和事务边界见 [架构说明](architecture.md)。

本次验证的环境、样本和限制见 [验证记录](validation-1.4.0.md)。

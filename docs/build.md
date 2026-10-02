# 本地开发、打包与验证

项目不使用 GitHub/Gitea Actions，仓库不保留工作流文件。检查、构建和发行文件上传均由维护者在本地完成，推送提交或版本标签不会自动执行这些步骤。

## Python 包

```shell
uv sync --locked
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
uv build
```

在受限目录中运行时，可以把 pytest 的临时目录指定到项目内，例如 `uv run pytest --basetemp build/pytest-local -q`。

wheel 包括 `src` 中的实现与 Windows FFmpeg。版本只在 `src/djhx_bilix/__init__.py` 定义，Hatchling 读取该版本构建。Nuitka 只在 `build` 依赖组中，不随 uv tool 安装。`uv.lock` 同时锁定开发、构建和运行依赖。

验证本地 wheel 的独立工具安装：

```shell
uv tool install --force dist/djhx_bilix-1.4.1-py3-none-any.whl
blx --version
blx doctor
```

也可使用 `uvx --from <wheel路径> blx --version`。`uv tool install` 接收 wheel 路径作为位置参数；`uvx` 使用 `--from` 指定提供 `blx`/`bilix` 命令的发行包。

本地 wheel 安装会记录该文件来源。切换回 PyPI 发行版时使用 `uv tool install --force --upgrade djhx-bilix==1.4.1`；随后可通过 `uv tool upgrade djhx-bilix` 更新。

## Windows exe

已验证的本地基线为 CPython 3.11 x64、Nuitka 4.2.2、Visual Studio 2022 MSVC 14.3。在独立环境中构建，避免把用户全局 Python 库一起打包：

```shell
uv sync --python 3.11 --locked --group build
uv run --group build python scripts/build_windows.py
```

脚本编译 `src/djhx_bilix/__main__.py`，显式包含包内 FFmpeg 和 Windows runtime DLL。默认 onefile 输出为 `build/windows/bilix.exe`，不依赖目标电脑安装 Python 或 FFmpeg。不启用 LTO，缩短重复构建时间；Nuitka 缓存在 `build/nuitka-cache`。编译通过 `python -X utf8 -m nuitka` 启动，Nuitka 使用 `--python-flag=isolated`；CLI 入口将标准输出和错误输出设置为 UTF-8，支持中文/emoji 帮助及重定向输出。

构建后自动复制 exe 到中文和空格目录，在仅含 Windows 系统目录的 PATH 下验证 `--help`、`--version`、`doctor` 和无效参数退出码。检查设置 `PYTHONUTF8=0`、`PYTHONIOENCODING=cp1252`，捕获标准输出和错误输出，覆盖非 UTF-8 编码设置与重定向场景。只有产物通过这些检查，脚本才报告成功。构建日志、编译报告和 `smoke.json` 保存在输出目录。

1.4.0 的本地中文 Windows exe 检查通过，但远端英文 Windows 的首次 `--help` 检查触发 cp1252 `UnicodeEncodeError`，因此没有发布该版 exe。Nuitka isolated 模式忽略 `PYTHONUTF8` 环境变量，不能仅靠环境变量启用 UTF-8；1.4.1 使用编译解释器的 `-X utf8` 和 CLI 标准流处理修复该问题，保留 1.4.0 的发行文件和标签。

`--mode standalone` 可以生成便于排查动态库和资源问题的目录产物。必须分发整个 `__main__.dist`，不能只复制其中的 exe。

旧 Nuitka 2.8.9 / Python 3.14 组合生成过无法启动的 exe。不能把“编译成功”等同于“可发布”；当前方案升级了 Nuitka、使用已验证的构建 Python，并把运行检查纳入构建脚本。旧崩溃的底层原因未进行 native debugger 定位。

## 测试分层

- 纯逻辑测试覆盖 URL、JSON 字符串、选集边界、音频/编码选择和文件名。
- 下载故障测试使用本地 HTTP 服务器，覆盖截断连接、503 和备用地址。
- 事务测试覆盖下载、校验、合并和提交失败时的旧文件保护、临时材料保留及并发提交。
- 凭据测试仅使用虚构 Cookie，覆盖登录响应、请求异常和终端错误输出。
- 会员回归使用合成页面/API 响应，覆盖新版影视 SSR、Next.js 元数据、播放接口补查、普通/有效会员/过期会员状态、失效登录、试看/DRM 拒绝和旧 token 格式兼容，不需要登录个人账号。
- 媒体集成测试使用完整 FFmpeg 的 lavfi/libx264 生成合成媒体，再用运行时选择的 FFmpeg 扫描和合并。缺少编码器会明确 skip。可以通过 `BILIX_TEST_FFMPEG` 指定用于生成样本的完整 FFmpeg。
- 会员音轨集成测试合成 FLAC/E-AC-3 媒体；杜比视界元数据回归使用 libx265 生成的小视频和合成配置记录，验证包扫描与最终合并两个阶段均保留该记录，不把实际电影存入测试仓库。
- 公开视频在线测试单独进行，避免日常本地检查依赖 Bilibili 服务、账号和变化的权限。

需要验证 Windows/Linux、Python 3.11–3.14 兼容性时，在对应系统与解释器环境中分别运行上述检查，并记录实际环境和结果。媒体测试需要安装用于合成媒体的完整 FFmpeg，包含 libx264、libx265 和 ffprobe；Windows 实际扫描/合并仍使用包内 FFmpeg，避免把系统 FFmpeg 的通过误当作内置版本通过。Windows 可使用 [Gyan 构建方公开的 Chocolatey 命令](https://www.gyan.dev/ffmpeg/builds/) 安装完整 FFmpeg，该构建方也列在 [FFmpeg 官方下载页](https://ffmpeg.org/download.html)。Windows exe 继续使用上述本地 CPython 3.11、Visual Studio 2022 基线构建。

本地构建保留 `build/nuitka-cache` 以减少重复编译时间，每次仍重新构建并执行 exe 启动检查。

## 发布

版本只改 `src/djhx_bilix/__init__.py`，同步锁文件及发布说明。每个版本必须使用新的版本号，PyPI 不允许替换已有文件。运行以上检查、验证独立 wheel 和 Windows exe 后，再提交并推送到远程仓库。

构建并检查这一版本的两个 Python 发行文件：

```shell
uv build
uvx twine check dist/djhx_bilix-1.4.1-py3-none-any.whl dist/djhx_bilix-1.4.1.tar.gz
```

使用 [uv 的发布命令](https://docs.astral.sh/uv/guides/package/#publishing-your-package) 从本地上传已验证的文件，明确列出文件名，避免混入 `dist` 中的旧版本。发布凭据通过发布环境的 `UV_PUBLISH_TOKEN` 提供；不要把 token 放入仓库、命令参数或日志。

```shell
uv publish dist/djhx_bilix-1.4.1-py3-none-any.whl dist/djhx_bilix-1.4.1.tar.gz
uv tool install --force --upgrade djhx-bilix==1.4.1
blx --version
blx doctor
blx auth status
```

从 PyPI 重新安装验证时保留用户配置目录；程序更新不会注销现有账号。最后核对 PyPI 上的版本及文件哈希、仓库提交与 exe 来源，记录发行结果。

Windows 发行前，在本地运行上面的 exe 构建命令并确认检查通过，再生成校验文件：

```powershell
$digest = (Get-FileHash -Algorithm SHA256 'build/windows/bilix.exe').Hash.ToLowerInvariant()
"$digest  bilix.exe" | Set-Content 'build/windows/SHA256SUMS.txt' -Encoding ascii
```

推送与源码版本一致的版本标签（例如 `v1.4.1`）后，在 GitHub/Gitea 发行页面手动选择该标签、填写发行说明，并上传本地验证过的 `build/windows/bilix.exe` 和 `build/windows/SHA256SUMS.txt`。上传完成后核对下载文件的 SHA256 与本地记录一致。

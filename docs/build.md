# 本地开发、测试与构建

项目不使用 GitHub/Gitea Actions。所有检查、构建与发行文件上传在本地进行；推送提交或标签不会自动执行它们。发布流程统一见 [releasing.md](releasing.md)。

## Python 开发环境

```shell
uv sync --locked
uv run blx --help
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
```

Python 3.11–3.14 为支持范围，最低版本在 `pyproject.toml` 中定义。`.python-version` 是本地默认解释器，不缩小发行包的支持范围。uv 锁文件涵盖运行、开发与构建依赖；Nuitka 只在 `build` 依赖组中。

受限环境可把缓存与临时目录放进项目内：

```powershell
$env:UV_CACHE_DIR = Join-Path $PWD 'build/uv-cache'
uv run pytest --basetemp build/pytest-local -q
```

请为每轮验证使用明确的临时目录。`pytest --basetemp` 会清理指定目录，不要指向含个人数据的目录。

## 测试范围

- URL、解析器、选集、编码/音轨与文件名使用纯逻辑或合成响应。
- 下载故障使用本地 HTTP 服务，覆盖截断、503、备用 CDN 与有限重试。
- 下载事务验证失败保护旧文件、保留临时材料及并发提交。
- 账号与会员使用虚构凭据，覆盖普通/有效/过期会员、失效登录与试看/DRM 拒绝。
- 媒体集成用完整 FFmpeg 合成 H.264、FLAC、E-AC-3 与杜比视界测试数据。
- CLI 覆盖中文输出、legacy 编码、旧入口、退出码、相近指令和 shell 补全。

媒体生成需要完整 FFmpeg（含 lavfi、libx264/libx265、ffprobe），可用 `BILIX_TEST_FFMPEG` 指定；缺少能力时明确 skip。Windows 扫描/合并使用包内 FFmpeg，避免把系统版本的成功当作内置版本成功。实际网络/权限检查与日常回归分开，使用账号前须获得授权。

新版本应在需要支持的系统与解释器中实际执行检查；不能用 [历史验证记录](validation-1.4.0.md) 替代新版本验证。本轮已执行内容与限制见 [1.5.0 验证记录](validation-1.5.0.md)。

## Python 发行包

```shell
uv build --out-dir dist/candidate
```

Hatchling 从 `src/djhx_bilix/__init__.py` 读取版本。wheel 包括统一实现、Windows FFmpeg 与许可证声明；sdist 另外包含测试、脚本、文档、单文件页面与锁文件。`build`、个人凭据和旧根目录脚本不属于发行内容。

使用独立环境安装候选 wheel 验证，不覆盖日常工具安装。完整检查、版本号与上传方法见 [发布流程](releasing.md)。内置 FFmpeg 的源码、许可与构建记录见 [第三方声明](../THIRD_PARTY_NOTICES.md) 和 [重建步骤](../vendor/ffmpeg/README.md)。

## Windows exe

已验证的构建基线：CPython 3.11 x64、Nuitka 4.2.2、Visual Studio 2022 MSVC 14.3。使用独立环境构建，避免把全局库打入产物。

```shell
uv sync --python 3.11 --locked --group build
uv run --group build python scripts/build_windows.py
```

默认 onefile 输出 `build/windows/bilix.exe`；`--mode standalone` 输出目录产物，必须分发整个目录。脚本显式包含 Windows runtime DLL 与包内 FFmpeg，使用 `python -X utf8 -m nuitka`、`--python-flag=isolated`，禁用 LTO；缓存保存在 `build/nuitka-cache`。

构建后自动在中文/空格目录、最小 Windows PATH、非 UTF-8 环境设置和重定向输出下检查启动、帮助、版本、doctor、参数错误与补全脚本。构建日志、编译报告与 `smoke.json` 保存在输出目录。只有运行检查通过才报告成功；编译成功不等于可发布。

发行包须携带 `LICENSE`、`THIRD_PARTY_NOTICES.md`、校验文件及准确对应的 FFmpeg 源码/构建材料。更新 FFmpeg 时须同时更新对应源码与构建记录。

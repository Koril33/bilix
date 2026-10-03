# 第三方组件声明

BiliX 自身采用 GPL-3.0-only（见 `LICENSE`）。各第三方组件保留自己的许可证与版权。本声明列出直接运行依赖，不替代各发行包携带的许可证；发布者还应保留实际分发的传递依赖、Python runtime 与 Windows runtime 的许可材料。

| 组件 | 许可证 | 上游 |
| --- | --- | --- |
| curl-cffi | MIT | https://github.com/lexiforest/curl_cffi |
| platformdirs | MIT | https://github.com/tox-dev/platformdirs |
| PyPNG | MIT | https://gitlab.com/drj11/pypng |
| qrcode | BSD | https://github.com/lincolnloop/python-qrcode |
| Typer | MIT | https://github.com/fastapi/typer |
| Rich | MIT | https://github.com/Textualize/rich |
| FFmpeg（Windows 内置工具） | GPL-2.0-or-later，由该二进制 `-L` 输出确认 | https://ffmpeg.org/ |

## 内置 FFmpeg

BiliX 1.5.0 的 `src/djhx_bilix/assets/ffmpeg.exe` 已改为从官方 **FFmpeg 7.1.5** 归档编译的 Windows x64 静态工具。构建含 `--enable-gpl`，其 `-L` 输出为 GPL-2.0-or-later。它通过独立子进程调用，保留 FFmpeg 本身的版权和许可证。

- 源码：仓库 `vendor/ffmpeg/ffmpeg-7.1.5.tar.xz`，未修改上游源码。
- 构建：`scripts/build_ffmpeg.sh`；完整参数和工具链记录在 `vendor/ffmpeg/manifest.json`。
- 源码 SHA256：`de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f`。
- 内置程序 SHA256：`aae2a7c0dad7a96eac5fe06891d74ca475630a8efb268ab2161016907052db27`。
- FFmpeg 及 MinGW/GCC 运行库许可随 Python wheel 和 Windows 发行 zip 提供。
- 完整 FFmpeg 源码归档与构建脚本随 Python sdist、Git 源码和 Windows zip 一起分发。取得 wheel 的用户可从同一版本的 PyPI 源码分发包获取对应源码。

重建步骤与分发文件布局见 [vendor/ffmpeg/README.md](vendor/ffmpeg/README.md)。旧 7.1.git 自定义程序仅保留在本地忽略的构建目录，不再用于本版本发行。参考 [FFmpeg 许可说明](https://ffmpeg.org/legal.html)。

# 第三方组件声明

BiliX 自身采用 GPL-3.0-only（见 `LICENSE`）。各第三方组件保留自己的许可证与版权。本声明列出直接运行依赖，不替代各发行包携带的许可证；发布者还应保留实际分发的传递依赖、Python runtime 与 Windows runtime 的许可材料。

所列 GUI/FFmpeg 版本对应 1.6.0 发行基线。后续依赖或 Qt 模块变化时同步更新锁文件、实际组件清单、对应源码获取方式和许可材料，并按[测试规范](docs/testing.md)验收最终包。1.6.0 公开产物的完成情况见[版本记录](docs/validation-1.6.0.md)。

| 组件 | 许可证 | 上游 |
| --- | --- | --- |
| curl-cffi | MIT | https://github.com/lexiforest/curl_cffi |
| platformdirs | MIT | https://github.com/tox-dev/platformdirs |
| PyPNG | MIT | https://gitlab.com/drj11/pypng |
| qrcode | BSD | https://github.com/lincolnloop/python-qrcode |
| Typer | MIT | https://github.com/fastapi/typer |
| Rich | MIT | https://github.com/Textualize/rich |
| cryptography（可选 GUI 更新验签依赖） | Apache-2.0 OR BSD-3-Clause；wheel 内附对应许可及 OpenSSL 许可 | https://github.com/pyca/cryptography |
| PySide6-Essentials（可选 GUI 依赖） | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；本项目按 GPL-3.0-only 选项分发 | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| shiboken6（PySide6 传递依赖） | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；本项目按 GPL-3.0-only 选项分发 | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Qt 6 基础库、Widgets 及平台插件（GUI 二进制内含） | 按各实际模块的开源许可；本项目使用 GPL-3.0 可用的模块 | https://www.qt.io/licensing/ |
| FFmpeg（Windows 内置工具） | GPL-2.0-or-later，由该二进制 `-L` 输出确认 | https://ffmpeg.org/ |

## GUI 发行的许可材料

应用图标由项目维护者原创，2026-10-10 确认为个人绘制，无第三方图标库来源。圆角底板、SVG、PNG 和 ICO 与项目源码一同按 GPL-3.0-only 分发；源稿为 `src/djhx_bilix/assets/bilix.svg`，派生素材由 `scripts/generate_icons.py` 生成。

PySide6-Essentials 6.11.2 与 shiboken6 6.11.2 的 wheel 元数据列出上述三选一许可；BiliX 自身为 GPL-3.0-only，GUI 发行选择 GPL-3.0-only。Qt for Python 的[许可说明](https://doc.qt.io/qtforpython-6/)及 [Qt 6 模块许可清单](https://doc.qt.io/qt-6/licensing.html)记录该选项与个别模块差异。仅使用 QtCore、QtGui、QtWidgets 及运行所需平台插件；增加其他 Qt 模块时须重新核对其许可。

Linux 的上述两个 wheel 未附单独许可文件时，`.deb` 会保存其原始 METADATA 许可表达式与 GPL-3.0 全文，并在 `SOURCE-ACCESS.md` 中给出对应的 Qt/Qt for Python 源码地址；Windows wheel 自带的许可文件则随包复制。

冻结构建会复制具体的 Qt 动态库、插件、shiboken6 和 Python 运行时。正式提供 Windows EXE、安装器或 Linux deb 前，维护者须检查最终产物实际包含的组件，并随产物提供对应版本的版权、许可及第三方声明，或满足其许可要求的源码获取方式；上游文档链接不能代替所需的发行材料。Qt 还包含[第三方代码与 SBOM](https://doc.qt.io/qt-6/licensing.html#third-party-code-in-qt)，应按实际打包的模块核对。

## 内置 FFmpeg

BiliX 1.5.0 的 `src/djhx_bilix/assets/ffmpeg.exe` 已改为从官方 **FFmpeg 7.1.5** 归档编译的 Windows x64 静态工具。构建含 `--enable-gpl`，其 `-L` 输出为 GPL-2.0-or-later。它通过独立子进程调用，保留 FFmpeg 本身的版权和许可证。

- 源码：仓库 `vendor/ffmpeg/ffmpeg-7.1.5.tar.xz`，未修改上游源码。
- 构建：`scripts/build_ffmpeg.sh`；完整参数和工具链记录在 `vendor/ffmpeg/manifest.json`。
- 源码 SHA256：`de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f`。
- 内置程序 SHA256：`aae2a7c0dad7a96eac5fe06891d74ca475630a8efb268ab2161016907052db27`。
- FFmpeg 及 MinGW/GCC 运行库许可随 Python wheel 和 Windows 发行 zip 提供。
- 完整 FFmpeg 源码归档与构建脚本随 Python sdist、Git 源码和 Windows zip 一起分发。取得 wheel 的用户可从同一版本的 PyPI 源码分发包获取对应源码。

重建步骤与分发文件布局见 [vendor/ffmpeg/README.md](vendor/ffmpeg/README.md)。旧 7.1.git 自定义程序仅保留在本地忽略的构建目录，不再用于本版本发行。参考 [FFmpeg 许可说明](https://ffmpeg.org/legal.html)。

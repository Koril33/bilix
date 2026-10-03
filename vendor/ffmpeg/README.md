# 内置 FFmpeg 的对应源码

BiliX 1.5.0 的 Windows 工具由官方 FFmpeg 7.1.5 源码直接编译，没有修改上游源码。这里保留完整的官方源码归档、许可证、构建记录和所用 GCC/MinGW 运行库许可。

- 官方归档：https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz
- 源码 SHA256：`de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f`
- 二进制 SHA256：`aae2a7c0dad7a96eac5fe06891d74ca475630a8efb268ab2161016907052db27`
- 构建配置、工具链与日期：[manifest.json](manifest.json)
- 构建脚本：[scripts/build_ffmpeg.sh](../../scripts/build_ffmpeg.sh)

## 重建

本轮基线为 Windows x64、Git Bash、MinGW-w64 GCC 12.2.0、GNU Make 4.2.1（mingw32-make）。使用无空格的源码/构建目录；所需工具均加入 PATH。解包到工作目录后，使用 Bash：

```bash
tar -xf vendor/ffmpeg/ffmpeg-7.1.5.tar.xz -C build
export PATH="/c/Software/mingw64/bin:$PATH"
export MAKE="/c/Software/mingw64/bin/mingw32-make.exe"
bash scripts/build_ffmpeg.sh "$PWD/build/ffmpeg-7.1.5" "$PWD/build/ffmpeg-compiled"
```

结果为 `build/ffmpeg-compiled/ffmpeg.exe`。Git Bash 配合原生 MinGW Make 时，脚本只将生成的 Makefile/config.mak 中的路径转为 Windows 格式，不修改源码。配置关闭自动外部依赖检测、网络协议与外部汇编；支持本地 MOV/MP4 读取、MP4 封装、媒体包扫描和 stream-copy，未加入转码编码器。

复制新结果至 `src/djhx_bilix/assets/ffmpeg.exe` 前，核对 `-version`、`-L`、DLL 依赖和 SHA256，执行完整媒体回归。构建目录和工具链不同可能改变二进制哈希，源码归档哈希应保持一致。

Python sdist 包含本目录与构建脚本；Windows 发行 zip 同样附上源码归档、构建脚本和许可。无需依赖一个可能失效的外部源码链接。项目源码归档或发行 zip 的接收者可解开嵌套 tar.xz 获取完整 FFmpeg 源码。

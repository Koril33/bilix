#!/usr/bin/env bash
# Build the bundled Windows stream-copy tool from the unmodified upstream source.
# Usage: build_ffmpeg.sh ABSOLUTE_SOURCE_DIRECTORY ABSOLUTE_BUILD_DIRECTORY
set -euo pipefail

source_dir="${1:?Pass the absolute FFmpeg source directory}"
build_dir="${2:?Pass the absolute build directory}"
mkdir -p "$build_dir"
cd "$build_dir"

bash "$source_dir/configure" \
    --target-os=mingw32 --arch=x86_64 \
    --enable-gpl --disable-everything --disable-autodetect --disable-network \
    --enable-ffmpeg --enable-protocol=file --enable-demuxer=mov --enable-muxer=mp4 \
    --enable-decoder=aac --enable-decoder=h264 \
    --enable-parser=aac --enable-parser=h264 --enable-parser=hevc --enable-parser=av1 \
    --enable-avformat --enable-avcodec --enable-avutil --enable-swresample \
    --disable-doc --disable-ffplay --disable-ffprobe --disable-iconv --disable-zlib \
    --disable-shared --enable-static --disable-x86asm \
    --extra-cflags=-static --extra-ldflags=-static

# Git Bash canonicalizes paths to /c/...; native MinGW Make needs C:/....
case "${MAKE:-make}" in
    *mingw32-make*)
        posix_source="$(cd "$source_dir" && pwd)"
        native_source="$(cygpath -m "$source_dir")"
        sed -i "s|$posix_source|$native_source|g" Makefile ffbuild/config.mak
        ;;
esac

"${MAKE:-make}" -j "${BILIX_BUILD_JOBS:-4}" SHELL=bash ffmpeg.exe

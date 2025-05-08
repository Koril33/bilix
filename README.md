# Bilix

一个简单的 Bilibili 命令行视频下载器

![](https://img.shields.io/badge/Python-3.11.2-green.svg)
![](https://img.shields.io/badge/license-GPLv3-red.svg)
![](https://img.shields.io/badge/release-v1.0.0-blue.svg)

项目主页: https://djhx.site/project/bilix.html

Github: https://github.com/Koril33/bilix

Gitee: https://gitee.com/ding_jing_hui/bilix

## 功能

### 登录

* 非登录状态下，可以下载 360P/480P 的普通视频
* 登录普通用户后，可以下载 720P/1080P 的普通视频
* 登录大会员用户后，可以下载 1080P+/4K 的普通视频、电影、番剧

本工具使用**扫码登录**的方式，键入 `bilix.exe --login` 后会在 bilix.exe 所在目录下生成一个二维码图片，手机扫码登录即可。

工具登陆后获取到的用户 Cookie 保存在当前目录下的 cookie.txt 文件中。

### 信息

查看帮助信息
```shell
bilix.exe --help
```

查看指定视频的清晰度信息
```shell
bilix.exe -i "https://www.bilibili.com/video/BV1j4411W7F7"
```

### 下载

下载单个视频
```shell
bilix.exe "https://www.bilibili.com/video/BV1j4411W7F7"
```

下载视频到指定目录
```shell
bilix.exe -s "videos" "https://www.bilibili.com/video/BV1j4411W7F7"
```

## 依赖

1. ffmpeg
2. httpx
3. curl_cffi
4. typer
5. rich
6. qrcode
7. nuitka

## 感谢

项目开发过程中参考了以下资源

1. https://blog.csdn.net/weixin_47481982/article/details/127666941
2. https://socialsisteryi.github.io/bilibili-API-collect/
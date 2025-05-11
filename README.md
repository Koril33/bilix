# Bilix

![](doc/bilix-icon.jpg)

一个简单的 Bilibili 命令行视频下载器

<p align="center">
  <a href="https://github.com/Koril33/bilix/stargazers"><img src="https://img.shields.io/github/stars/Koril33/bilix.svg?style=for-the-badge" alt="Stargazers"></a>
  <a href="https://github.com/Koril33/bilix/releases/latest"><img src="https://img.shields.io/github/v/release/Koril33/bilix?style=for-the-badge" alt="Latest Release"></a>  
  <a href="https://github.com/Koril33/bilix/blob/main/LICENSE"><img src="https://img.shields.io/github/license/Koril33/bilix.svg?style=for-the-badge" alt="License"></a>
  <a href="https://www.python.org/downloads/release/python-3110/"><img src="https://img.shields.io/badge/Python-3.11.0-green.svg?style=for-the-badge" alt="Python Version"></a>
</p>

项目主页: https://djhx.site/project/bilix.html

Github: https://github.com/Koril33/bilix

Gitee: https://gitee.com/ding_jing_hui/bilix

## 声明

本项目仅用于学习、研究与技术交流目的，严禁用于任何商业用途或违反中国大陆及其他国家和地区相关法律法规的行为。

请注意以下几点：

* 本项目不提供任何盗版内容，也不鼓励用户下载、传播受版权保护的内容；

* 使用本工具所造成的一切后果，由使用者本人承担；

* 请在下载前获得原作者授权，尊重原创和内容版权；

* 若您不同意本声明，请不要使用或传播本项目中的任何内容。

* 开发者对任何由于使用本项目所引起的直接或间接损失不承担任何法律责任。

## 演示

Windows
![](doc/bilix-demo-win.gif)

Ubuntu
![](doc/bilix-demo-ubuntu.gif)

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

查看当前登陆用户的信息
```shell
bilix.exe -u
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

### 视频选集下载

下载所有视频选集
```shell
bilix.exe --page "all" --save "世界通史" "https://www.bilibili.com/video/BV12R4y1J75d"
```
下载第 1 和 3 集

```shell
bilix.exe --page "1,3" --save "世界通史" "https://www.bilibili.com/video/BV12R4y1J75d"
```
下载第 4-6 集

```shell
bilix.exe --page "4-6" --save "世界通史" "https://www.bilibili.com/video/BV12R4y1J75d"
```

### 多个视频下载

方式一: 命令行中指定多个 URL
```shell
bilix.exe "https://www.bilibili.com/video/BV1j4411W7F7" "https://www.bilibili.com/video/BV1yt4y1Q7SS"
```

方式二: 把多个 URL 存储到文本文件中，例如，当前目录下建立一个 video.txt，内容如下
```text
https://www.bilibili.com/video/BV1j4411W7F7
https://www.bilibili.com/video/BV1yt4y1Q7SS
```
然后 -o 选项，指定该文件
```shell
bilix.exe -o "video.txt"
```

## 待实现

1. 下载课程（/cheese）
2. 切换 CDN
3. 下载弹幕/评论
4. 完善 --user 和 --info 的返回信息
5. 下载视频封面
6. 可以选择视频的编码
7. 支持设置本地 ffmpeg 路径
8. 收藏夹/个人空间解析和批量下载
9. 自定义格式化文件名

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
3. https://github.com/nilaoda/BBDown
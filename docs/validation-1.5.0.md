# 1.5.0 验证记录

日期：2026-10-03。以下检查在 Windows 本地完成，针对 1.5.0 源码及实际发行产物。公开发行状态、最终提交与下载文件哈希见 [GitHub Releases](https://github.com/Koril33/bilix/releases/tag/v1.5.0) 和 [PyPI](https://pypi.org/project/djhx-bilix/1.5.0/)。项目页面纳入源码管理，本轮没有部署线上网站。

## 已执行

| 检查 | 环境与结果 |
| --- | --- |
| Ruff 格式与 lint | src、tests、scripts 全部通过 |
| 完整 pytest | Windows / CPython 3.14.0，195 passed；包含本地 HTTP 故障、媒体事务、权限与 CLI 回归 |
| 实际终端补全 | Windows PowerShell 5.1、PowerShell 7、Bash 回归通过；Windows 覆盖完整路径、中文/空格/引号、中间光标与省略 .exe 的 blx 命令 |
| 构建 | Hatchling / uv 生成 1.5.0 wheel 与 sdist |
| 包元数据 | Twine 7.0.0 对 wheel 和 sdist 检查通过；许可证与第三方声明随包提供 |
| 归档内容 | wheel 源码与工作区逐文件一致，内置 FFmpeg 哈希与 manifest 一致；sdist 包括完整 FFmpeg 对应源码、文档、页面、脚本、测试与锁文件，不含私人凭据、缓存、.git 或旧 doc 目录 |
| 独立 wheel 安装 | CPython 3.11.2 新环境安装实际 wheel 和依赖，确认导入路径来自安装包；版本、help、参数纠错、四种 shell 脚本、doctor 通过 |
| wheel 的真实 PowerShell 补全 | PowerShell 5.1/7 中输入 blx do，均返回 doctor / download；环境仅在子进程 PATH 中加入候选安装目录 |
| Windows onefile 构建 | CPython 3.11.2 / Nuitka 4.2.2 / MSVC 14.3，实际编译并运行；最小 PATH、cp1252、中文/空格路径下通过 11 项启动检查 |
| exe 的真实 PowerShell 补全 | PowerShell 5.1/7，exe 位于 PATH 外且路径含中文、空格、单引号；命令、子命令、选项与清晰度值补全通过 |
| Windows zip | 包含实际 exe、使用说明、项目/Python/依赖许可证，以及完整 FFmpeg 对应源码与构建材料 |
| FFmpeg | 官方 7.1.5 未修改源码，本地 GCC 12.2.0 / MinGW-w64 静态构建；实际媒体回归通过，源码与二进制哈希记录在 vendor/ffmpeg/manifest.json |
| 静态页面 | 沿用线上布局、背景和配色，背景图内嵌；1440、980、700、390、320px 无页面横向溢出；版本 API 成功/失败响应使用合成数据测试，禁用 JavaScript 时内容与下载链接可用 |
| 文档与差异 | 本地 Markdown 链接和 git diff --check 通过 |
| 凭据检查 | Gitleaks 8.30.1 默认规则与本项目 Cookie 规则扫描当前工作区，0 findings；维护者确认已发现的历史凭据失效，本地审计报告按要求删除 |

独立 wheel 的运行依赖使用 uv.lock 中版本，安装 Twine 后 Rich 为 15.0.0（仍在允许范围内）。其他运行依赖包括 curl-cffi 0.13.0、Typer 0.20.0、Click 8.3.1、platformdirs 4.5.1、qrcode 8.2、PyPNG 0.20220715.0。

## 公开地址检查

对 ss46055 的官方选集接口进行未登录查询，正片包含原版 ep777109 与中文 ep777157。用程序当前的官方网页播放请求参数查询，两项均返回 is_drm=true、is_preview=1，未提供普通 DASH 音视频流。本轮没有使用历史 Cookie，也没有测试用户的登录账号、传输该影片或尝试解密。这个响应仅代表当时的匿名会话。

针对这类场景的合成回归验证：DRM 在传输前拒绝，两项分别显示名称/URL，最终失败计数为 2。

## 验证范围

- 未运行新的 Linux/macOS 系统验证；Zsh/Fish 验证为脚本生成，未在真实 Zsh/Fish 终端执行。
- 历史文本对象检查覆盖当时本地可见 refs；没有重写 Git 历史、强制推送或用旧凭据访问账号。失效状态来自维护者确认。
- 扫描没有覆盖私人用户目录、远程不可见 refs 或二进制内部的任意秘密类型；扫描通过不能代替凭据管理。

本轮产物与构建日志位于忽略的 build/release-1.5.0；公开发行文件的哈希随发行提供。后续源码修订须重新执行相应检查、构建并计算哈希，遵循 [发布流程](releasing.md)。

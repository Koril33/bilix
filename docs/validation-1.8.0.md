# 1.8.0 发行与验收记录

日期：2026-10-14（Asia/Shanghai）。状态：**已发布，本文列明范围的验收与公开渠道回验完成**。设计与交互见 [1.8.0 指南](gui-update-guide-1.8.0.md)。标签 `v1.8.0` 固定在提交 `d41f5bf2fdf978d8c2420c550006388341ad256d`；以下发行结果在标签冻结后补入，已公开文件和标签不修改。

## 实现与边界

GUI 采用方案一，在新建下载对话框中直接选择完整视频、仅音频、仅无声视频、音视频分别保存或仅封面；完整视频仍为默认，并可同时保存封面。界面按方式隐藏无关参数，预览、结果与失败重试按实际输出文件显示。CLI 增加 `--mode` 与 `--cover`，和 GUI 使用同一执行路径。

音视频保持源编码，AAC 音轨保存为 M4A，其他音轨保存为音频 MP4；无声视频不再进入合并步骤。封面下载限制为受信 HTTPS 主机、受控重定向、内容类型和大小上限，并采用临时文件后原子提交。本版没有加入 MP3 转码、字幕或跨重启续传。

## 自动化与平台验收

- Windows 10 / Python 3.14.8 最终严格发行 profile：**525 passed、0 failed、0 skip**，并通过 Ruff、CLI 版本/帮助/doctor/纠错/四种补全、GUI 离线冒烟和发行集合检查。证据在忽略目录 `build/validation/1.8.0/gui-20261014T075922Z-bf988a9e/`；开发阶段完整 profile 另见 `gui-20261014T065950Z-edca5d49/`。
- Python 3.11.2 隔离环境安装最终 wheel 后，版本、帮助和 doctor 通过。
- Ubuntu 22.04 对新增导出与真实 FFmpeg 媒体读取执行 **20 passed**，Ruff 与格式检查通过。完整 Linux 测试为 **510 passed、14 个 Windows 专属 skip、1 failed**：失败是离屏环境字体截断后 `QLabel.text()` 仅含 `已登录：offline · 年度大…`，而 `ElidedLabel.full_text` 保留完整文本；它与本版下载功能无关，未据此宣称 Linux 全套通过。
- 全新 Ubuntu 22.04 VM 中，deb 安装、两次启动、自身重装、卸载和用户数据保留通过。发布后又从本地 1.7.9 基线经公开 APT 升级至 1.8.0-1，dpkg 版本断言与无界面 GUI 冒烟通过。
- 工作树 Gitleaks 为 0 项发现。全历史仍有 22 项既有命中，来自先前已确认失效的旧凭据，不写成全历史 0。

按维护者要求采用精简测试。本版没有重做 Ubuntu 24.04、Debian 12/13、Wayland、IME、系统 DPI、高对比、在线账号或四发行版升级矩阵；这些属于未验证范围，不表示已发现产品故障。

## 冻结发行文件

构建使用 Python 3.14.8、Nuitka 4.2.2 和 PySide6/Qt 6.11.2。八项发行文件位于本地不可变候选目录 `dist/release-1.8.0/`，签名更新序号为 5；目录还包含 SHA256 清单、发行清单及签名更新元数据，共 15 个公开文件。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `BiliX-GUI-Portable-1.8.0-windows-x64.exe` | 35,889,664 | `e0ea832a8bd0f78320b79a1e7b3005fcfe2a59fe22779916620a6f1d63095326` |
| `BiliX-GUI-Setup-1.8.0-windows-x64.exe` | 47,585,005 | `54b2f2f033a0e60b2316711a247d4c93a61b53e8af1ab45d0378fc7c9be7e10e` |
| `BiliX-GUI-licenses-and-source-1.8.0-windows-x64.zip` | 13,846,136 | `5e1d4c7e50dfeeba741e5aabf5313ab457e340b0a711c374f033009257f1cb81` |
| `bilix-1.8.0-windows-x64.zip` | 30,098,020 | `5a91292c85c977bf4a6439cc9a3beebbc688d3d88e043085a8c02f5af960c0ca` |
| `djhx-bilix-gui_1.8.0-1_amd64.deb` | 64,471,732 | `75cc3c5fa648bab41c39ee76bfd445e9bdecae8e4526e924f0dc6a305c253273` |
| `djhx-bilix-gui_1.8.0_source.tar.gz` | 857,535 | `e9c7a0f23e6dc671794e0bacf105ba9ae60e2fdd805fc1e800aa4c3fae3fa309` |
| `djhx_bilix-1.8.0-py3-none-any.whl` | 1,923,147 | `5529497bd4dca7140548769652645b7a480eff9c4b34539aa3e5303db669dace` |
| `djhx_bilix-1.8.0.tar.gz` | 13,837,463 | `54bba7e49d8f95ed598176fe55e16103820b5e677f300eaed857b19af41c7f75` |

## 发布与公开回验

- GitHub 与 Gitea 的 `main` 和 `v1.8.0` 已推送。GitHub [v1.8.0 Release](https://github.com/Koril33/bilix/releases/tag/v1.8.0) 为 latest，15 个资产从公网完整重新下载后，大小与 SHA-256 全部匹配。
- [PyPI 1.8.0](https://pypi.org/project/djhx-bilix/1.8.0/) 已发布；公网重新下载的 wheel 和 sdist 与冻结文件匹配。
- [官网](https://bilix.djhx.site/) 与 `site/bilix.html` 字节一致，SHA-256 为 `b67ff511e788ba32615b0b50cc6bef10990898ab6bf8c5a015d527f265888a59`，包含 1.8.0 链接；不存在的版本资产返回 404。
- 官网版本镜像的 15 个文件已逐个重新下载并验证大小与 SHA-256；活动 `stable.json`、签名、更新清单和密钥链验证通过。隔离客户端模拟 1.7.8 后成功检查、下载、准备并重新验证 1.8.0，模拟当前 1.8.0 时正确返回无更新，未调用安装。
- 公开 APT 仓库使用原指纹 `201A20E104EF3C72CE573F7E61323BAA3BB87821`，保留 1.7.6 至 1.7.9。构建 VM 为新环境，因此用仓库外备份恢复同一签名密钥，并从旧包池重建 aptly 工作区后加入 1.8.0；39 个公开文件预检、上传和 Ubuntu 22.04 的 1.7.9 → 1.8.0-1 升级均通过。

部署服务器到 GitHub 的额外全文件读取在单个资产等待响应时触发 90 秒读超时；本机到 GitHub 的 15 文件全量回验和服务器读取的 latest 元数据均已成功，因此记录为服务器网络路径限制，不计为资产差异或发布失败。

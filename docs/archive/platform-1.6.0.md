# 1.6.0 平台验收原文（历史）

以下保留首版结果与故障诊断。当前可重复步骤见 [Linux 流程](../gui-vm-validation.md)和 [Windows 流程](../gui-win10-validation.md)；最终身份以 [validation-1.6.0.md](../validation-1.6.0.md) 为准。旧通过结果不证明当前版本通过。

## Linux 首版

| 检查项 | Ubuntu 22.04 | Ubuntu 24.04 | Debian 12 | Debian 13 |
| --- | --- | --- | --- | --- |
| 干净 VM 启动 / `apt` 安装 | 通过 | 通过 | 通过 | 通过 |
| `offscreen` 启动 | 通过 | 通过 | 通过 | 通过 |
| Xvfb/X11 启动 | 通过 | 通过 | 通过 | 通过 |
| 同版本重装 | 通过 | 通过 | 通过 | 通过 |
| 跨版本升级 | 未验证 | 未验证 | 未验证 | 未验证 |
| 卸载与用户数据保留 | 通过 | 通过 | 通过 | 通过 |
| 可见 XFCE 桌面、中文路径、文件选择器 | 通过 | 通过 | 通过 | 通过 |
| 中文输入法（IME） | 未验证 | 未验证 | 未验证 | 未验证 |
| Wayland 启动 | 未验证 | 通过；Weston 无头 compositor | 未验证 | 通过；Weston 无头 compositor |
| 真实登录和下载 | 未验证 | 未验证 | 未验证 | 未验证 |

### 2026-10-04 本轮执行

本轮版本是 `1.6.0-1`，首轮候选 `.deb` SHA256 为 `af7e10efbfc6df94635213adc1389f639362fa70e2abf814d6573cf0ffbf233e`。`dpkg-deb -f` 确认为 `amd64`，Maintainer 为 `Koril <dingjinghui33@163.com>`，Depends 包含 `ffmpeg` 及 Qt/X11 系统库。开发基线提交为 `26083783445940ac2371f4a41cda7f23358df9c7`，最终源码由 `v1.6.0` 标签确定；最终文件 SHA256 以发行页的 `release-manifest.json` 与 `SHA256SUMS.txt` 为准，避免把发行包自身包含的文档哈希作为自引用。宿主机使用 Vagrant 2.4.9、VirtualBox 7.0.12。文档或发行包变化后，必须使用新 SHA256 复验，复验日志保存于本地忽略目录。

- Ubuntu 22.04：使用独立的 `ubuntu2204clean` VM（box `ubuntu/jammy64` 版本 `20241002.0.0`）从本发行版仓库解析依赖并安装，系统提供 FFmpeg 4.4.2；`offscreen`、Xvfb/X11、同版本重装后自检均通过，卸载后用户目录标记文件保留。真实 XFCE/X11 桌面截图确认主窗口和中文标签正常显示；文件选择器中选择现有 `/home/vagrant/Downloads` 和 `/home/vagrant/下载测试` 后，“保存到”字段正确回填。截图及 apt/自检日志位于 `dist/gui/validation/ubuntu2204/`。
- Debian 12：box `debian/bookworm64` 版本 `12.20250126.1`，系统提供 FFmpeg 5.1.9；同一候选包的安装、两种无头启动、同版本重装、卸载及数据保留均通过。真实 XFCE/X11 桌面截图确认中文标签可读；文件选择器显示现有 `下载测试` 目录，点选后 `Choose` 按钮变为可用，确认后主窗口回填 `/home/vagrant/下载测试`。截图及日志位于 `dist/gui/validation/debian12/`。
- Ubuntu 24.04.3：box `bento/ubuntu-24.04` 版本 `202510.26.0`；安装、offscreen、Xvfb/X11、同版本重装、卸载和数据保留通过。真实 XFCE/X11 桌面确认中文标签正常，选择 `/home/vagrant/下载测试` 后保存目录字段正确更新。额外安装 Weston 13，使用无头 Wayland compositor 运行 `QT_QPA_PLATFORM=wayland bilix-gui --smoke-test` 通过；这验证了 Wayland 协议启动，不代表已验收 GNOME/KDE 的完整 Wayland 桌面交互。日志和截图位于 `dist/gui/validation/ubuntu2404/`。
- Debian 13.1：box `bento/debian-13` 版本 `202510.26.0`，系统 FFmpeg 7.1.5；安装、offscreen、Xvfb/X11、同版本重装、卸载及用户数据保留均通过。真实 XFCE/X11 桌面显示中文标签；文件选择器识别 `/home/vagrant/下载测试`，确认选择后主窗口字段正确更新。无头 Weston/Wayland 启动自检通过，范围同上述 Ubuntu 24.04 测试。日志和截图位于 `dist/gui/validation/debian13/`。

Debian 13 的初始 box 使用旧 HTTP 重定向软件源，首次依赖下载很慢；测试时改用 Debian 官方 HTTPS CDN，仍由 apt 的已签名索引与包校验确定内容并执行安装。`provision.sh` 固定改用该官方入口，并跳过这些专用测试 VM 不需要的源码/翻译索引。此调整只用于仓库创建的测试 VM，不修改宿主机或用户已有虚拟机的软件源。

中文路径是用系统剪贴板粘贴，或在文件选择器中用鼠标选择；这验证了路径显示和交互，**尚未验证中文输入法（IME）键入**。当前也尚未使用受保护的测试账号做真实登录/下载，且没有旧 GUI 正式发行包可做跨版本升级。box 的原始 `.box` 文件校验值本轮未保留；重建长期镜像缓存时应记录 SHA256。

最终发布 deb 的 SHA256 为 `d6ba0f21662b924559eae4be045eeeb454866941c326601ae2e558419a500f26`，四目标重新安装/启动/重装/卸载/保留数据通过，证据为 `dist/gui/validation/final-matrix.json` 及各目标日志。它与前文 `af7e…` 首轮候选不同；最终结果见[1.6.0 版本记录](../validation-1.6.0.md)。本次维护新增的独立日志/配置保留检查需按新增脚本另外留证，不继承旧脚本结果。


## Windows 首版

## 2026-10-03/04 本轮结果

| 项目 | `1.6.0.dev0` 预览包 | `1.6.0` 正式候选 |
| --- | --- | --- |
| Windows 10 x64 build 19045 与 Guest Additions 7.0.12 | 通过 | 通过 |
| Manifest 中三个产物的大小/SHA-256 | 通过 | 通过 |
| Windows 专用 `SHA256SUMS` 与 manifest 一致 | 旧包按旧格式校验 | 通过 |
| 中文路径绿色版自检两次 | 通过 | 通过 |
| 同渠道旧版升级 | 未验证 | 未验证；没有可用的旧稳定版安装包 |
| 安装、已安装版自检、卸载与用户数据保留 | 预览包直接 Guest Control 安装失败并回滚；未用交互登录重试 | 通过；`candidate-result.json` 记录 14 项检查成功 |
| 真实桌面主窗口及中文标签 | 未验证 | 通过；中文清晰，无方框字形 |
| 拼音输入法候选和中文提交 | 未验证 | 通过 |
| 原生保存目录选择器导航与选择后字段更新 | 未验证 | 通过 |
| 扫码登录、真实下载、Windows 11 | 未验证 | 未验证 |

早期通过 Guest Control 直接运行 Inno Setup 时，安装在创建 HKCU 卸载项时报 `RegCreateKeyEx` 错误 5，并回滚，退出码 4。诊断显示进程用户与 `USERPROFILE` 均为 `koril`，但其 SID hive 未加载；使用 `LoadUserProfile` 后 hive 存在，用户对卸载分支有完整权限，临时注册表项创建和删除成功。正式候选通过该方式完成实际安装、已安装程序自检、卸载和用户数据保留。该问题属于 VM 的 Guest Control 登录方式，不是安装包故障；未更改用户长期注册表 ACL。

正式候选的可见桌面截图是 `main-window.png`、`chinese-ime.png`、`folder-chooser.png` 与 `folder-selected.png`，均位于本地忽略目录 `dist/gui/validation/win10/`。截图遮盖了 VM 用户名或文件选择器的个人位置导航栏。正式候选曾因源码 ZIP 误收本地 `.vagrant` 状态而重包；上述安装与桌面测试使用清理后的包，Manifest 的三项 SHA-256 检查通过。最终发布包若因文档或构建内容变化再打包，须以最终 `release-manifest-windows.json` 复跑脚本；此前候选测试不能直接替代最终哈希验收。

2026-10-04 重编译后的候选曾在“自检退出后立即卸载”时出现 EXE 删除失败：安装与自检均通过，卸载日志记录 EXE 暂被占用，且初始卸载进程返回时清理助手仍在工作。后续诊断确认该 EXE 的运行进程数为零，文件锁已释放。验收脚本因此加入上述文件锁及清理完成等待；修复后必须重新运行完整验收，最终结果和文件哈希由本地 `final-result.json` 与公开发行说明记录。

最终复验已完成：`dist/gui/validation/win10/final-result.json` 记录 1.6.0 正式文件的 15 项检查通过，最终产物哈希见[版本记录](../validation-1.6.0.md)。原文的“必须重新运行”描述当时修复要求；最终结果已补齐。本次维护新增的数据内容与旧版自检检查属于后续脚本，须另记实际执行范围。

# GUI 跨发行版虚拟机验证

本流程使用仓库内的 [Vagrant 配置](../tests/vm/Vagrantfile)管理专用测试虚拟机，不读取或修改 `C:\Project\vagrant` 中已有的虚拟机。Linux 目标为 Ubuntu 22.04、Ubuntu 24.04、Debian 12 和 Debian 13 的 amd64 版本；Windows 10 的绿色版与安装版验收另行记录。Windows 11 暂不纳入首版验证范围。

## 环境与构建原则

- 宿主机需要 VirtualBox、Vagrant、PowerShell，以及能获取 Ubuntu/Debian 软件包和 Python 构建依赖的网络。一次只启动一个 VM。构建机 `ubuntu2204` 使用 4 vCPU、6 GiB 内存，其他 VM 使用 2 vCPU、4 GiB 内存；大约要为 Ubuntu 构建缓存和多个虚拟磁盘预留数十 GiB。
- `.deb` **仅在 Ubuntu 22.04 amd64** 编译。构建脚本把明确列出的源码、测试和锁文件复制到 VM 的 ext4 后再运行，避免直接在 VirtualBox 共享文件夹中编译。当前 `uv` 的独立解释器索引还没有 3.14.8 构建，脚本从 [python.org 官方 3.14.8 源码](https://www.python.org/downloads/release/python-3148/)下载并校验 SHA256，在 VM 内编译所需的 CPython 3.14.8；之后使用 `uv.lock`、PySide6-Essentials 6.11.2 和 Nuitka 4.2.2，执行离线 pytest、Ruff、冻结程序的 `--smoke-test`，然后打包 `.deb`。产物和日志写回忽略的 `dist/gui/`。
- 每个安装目标从新的 VM 开始，检查包 SHA256、用本发行版的 `apt` 解析依赖并安装、检查桌面入口和图标、运行 Qt `offscreen` 与 Xvfb/X11 的启动自检、重装、卸载，并验证隔离用户目录中的标记文件仍在。**同版本重装并不等于跨版本升级**；有旧的正式 GUI 包时再做真正升级及降级行为测试。
- `offscreen` 和 Xvfb 能发现动态库、插件、启动和基础交互错误，不能证明窗口字体、缩放、输入法、文件选择器、二维码在真实桌面上正常。发行前每种发行版仍需可见桌面检查；账号登录和真实下载需要受保护的测试账号并单独记录。

可见桌面检查在完成基础安装验收后，针对需要检查的 VM 单独执行（以 Debian 12 为例）：

```powershell
cd tests/vm
vagrant up debian12 --provider=virtualbox
vagrant ssh debian12 -c "sudo sh /bilix-host/tests/vm/desktop-setup.sh"
vagrant reload debian12
vagrant ssh debian12 -c "sudo apt-get install -y /bilix-host/dist/gui/djhx-bilix-gui_*_amd64.deb"
vagrant ssh debian12 -c "setsid -f env DISPLAY=:0 XAUTHORITY=/home/vagrant/.Xauthority bilix-gui >/tmp/bilix-gui-visible.log 2>&1 </dev/null"
```

`desktop-setup.sh` 只在本项目测试 VM 中安装 XFCE/LightDM、中文字体和 X11 操作工具，设置测试用户 `vagrant` 自动登录。维护者可打开该 VM 的 VirtualBox 窗口，或用 `VBoxManage controlvm bilix-validation-debian12 screenshotpng <截图路径>` 获取虚拟显示截图，确认主窗口、中文输入、文件选择器和二维码状态。截图与日志应保存在忽略的 `dist/gui/validation/<目标>/`，标出实际操作内容。服务器型 box 加装 XFCE 的这一步需要较多下载与磁盘空间。

## 可重复运行

在仓库根目录用 PowerShell 执行：

```powershell
./tests/vm/run-linux-matrix.ps1
```

脚本先用 Git 的 NUL 分隔文件列表创建源码白名单，再清理本项目 `tests/vm` 对应的旧测试 VM、创建 Ubuntu 22.04 构建机、构建并关机，然后依次重建四个目标 VM 安装同一 `.deb`。Ubuntu 22.04 安装验收使用单独的 `ubuntu2204clean` VM，保留构建机的编译环境以便修复后重新打包。白名单传给无 `.git` 元数据的 guest，发行源码包只能纳入 Git 可见文件，避免误收 `.vagrant` 私钥或本地缓存。失败即停止，故障 VM 留在现场供排查。产物在 `dist/gui/`，每机日志在 `dist/gui/validation/<目标>/`；这些目录被 Git 忽略。若 `.deb` 已构建，可按目标重跑：

未用 `-Maintainer '姓名 <邮箱>'` 指定维护者时，构建脚本使用仓库提交历史中已公开的 `Koril <dingjinghui33@163.com>`。若维护者在发布前指定其他地址，应重新打包、重新核对哈希，并用最终包重复安装验收。

```powershell
./tests/vm/run-linux-matrix.ps1 -SkipBuild -Targets debian12
```

手动分步执行时，在 `tests/vm` 目录中运行：

```powershell
vagrant validate
python ./write-source-manifest.py
vagrant up ubuntu2204 --provider=virtualbox
vagrant ssh ubuntu2204 -c "bash /bilix-host/tests/vm/build-ubuntu2204.sh"
vagrant halt ubuntu2204
vagrant up ubuntu2204clean --provider=virtualbox
vagrant ssh ubuntu2204clean -c "bash /bilix-host/tests/vm/accept-deb.sh ubuntu2204"
vagrant halt ubuntu2204clean
vagrant up debian12 --provider=virtualbox
vagrant ssh debian12 -c "bash /bilix-host/tests/vm/accept-deb.sh debian12"
vagrant halt debian12
```

只销毁本项目定义的专用 VM。`Vagrantfile` 固定了四个 box 的版本，但 [HCP Vagrant 公共 Registry 计划在 2026 年底停止服务](https://www.hashicorp.com/en/blog/hcp-vagrant-deprecation-important-dates-and-migration-guidance)；长期复现时应把经许可取得的 `.box` 缓存在私有位置，保存每个 box 的 SHA256，并通过 `BILIX_BOX_UBUNTU2204`、`BILIX_BOX_UBUNTU2404`、`BILIX_BOX_DEBIAN12`、`BILIX_BOX_DEBIAN13` 环境变量改用本地/私有 box 名称。不要把 Windows 镜像或私人账号配置提交到 Git。

若 Windows OpenSSH 提示 Vagrant 默认 RSA 私钥权限过宽，`Vagrantfile` 支持把该默认密钥复制到被 Git 忽略的 `tests/vm/.vagrant/keys/vagrant.key.rsa` 并只给当前用户读权限。这样无需改动用户原有的 `C:\Users\<用户名>\.vagrant.d`；复制后必须核对 ACL，不能把密钥移入可提交目录。本轮测试机出现过此问题，限制本地副本 ACL 后 SSH 恢复。

## 每次发布的验收记录

每次候选版本在此文件或新的版本记录中填写具体版本、提交 SHA、`.deb` SHA256、box SHA256、系统版本、执行时间与结果。失败项记录错误日志和修复后重新运行的结果。没有执行的项目标成“未验证”，不能推断通过。

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

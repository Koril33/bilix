# Linux GUI 构建与原生验收

使用本仓库 [tests/vm/Vagrantfile](../tests/vm/Vagrantfile) 的专用 VM。目标为 Ubuntu 22.04/24.04、Debian 12/13 amd64；deb 只在 Ubuntu 22.04 构建。测试不读取或修改用户 `C:\Project\vagrant` 中的 VM。历史首轮结果已保留在 [archive/platform-1.6.0.md](archive/platform-1.6.0.md)，当前结论填入当版验收记录。

## 前置条件与范围

Windows 宿主需要 PowerShell、Vagrant、VirtualBox，以及获取 box、系统依赖与 Python 源码的网络。构建 VM 为 4 vCPU/6 GiB，其余 2 vCPU/4 GiB；为构建缓存和磁盘预留数十 GiB，一次只启动一个目标。

脚本仅识别/管理本项目命名的 `bilix-validation-*` VM，检查 VM UUID、配置路径和专用标记后才销毁重建。失败会保留现场。运行前确认本轮允许重建这些测试机，不能把已有应用环境宣称为干净安装环境。

源码白名单来自 Git 可见文件，复制至 guest ext4 构建；不在共享目录编译、不纳入 `.vagrant` 私钥或缓存。解释器安装脚本核对官方源码 SHA256 后编译 CPython 3.14.8，锁文件固定 GUI/build 依赖。

## 一个入口

在仓库根目录：

```powershell
./tests/vm/run-linux-matrix.ps1
```

它生成白名单、构建 deb 并关机，再依次重建四个验收目标，按 manifest 选定候选，核对 SHA256、apt 依赖、offscreen/Xvfb 启动、桌面入口/图标、同版重装、卸载与配置/下载内容保留。Ubuntu 22.04 安装目标是独立 `ubuntu2204clean`，不把有开发依赖的构建机当作干净目标。

关键参数：

| 参数 | 行为 |
| --- | --- |
| `-SkipBuild -ArtifactDir <目录>` | 验收已经集合的候选；按 manifest 选择同版本 deb |
| `-PriorDeb <原始旧版deb>` | 实际旧→新升级、APT 降级策略、旧版启动、配置/下载哈希保留 |
| `-Targets ubuntu2204,debian12` | 仅运行所选验收目标；完整发行范围仍须逐项记录 |
| `-SkipBuild -PrepareOnly` | 重建/准备验收 VM 后关机，等待后续候选 |
| `-SkipBuild -ReusePrepared` | 使用已核对的专用 VM；不销毁，不能自动证明本轮干净 |
| `-Maintainer 'Name <email@example.org>'` | 覆盖构建 deb 的维护者元数据 |

例如候选已在 `dist/release-<版本>`，将参数替换为当前真实目录和已校验旧包：

```powershell
./tests/vm/run-linux-matrix.ps1 -SkipBuild `
  -ArtifactDir 'dist/release-<版本>' -PriorDeb 'dist/prior/<旧版deb>'
```

尖括号为占位值，不能照原样执行。未提供旧包时不做跨版升级；同版重装不算升级。脚本对 checksum 输入兼容 CRLF，不修改原清单或产物。

产物为 `dist/gui/`；构建和目标日志保存于独立 `validation/<目标>/<本轮标识>/`，以脚本输出路径为准。记录版本、提交/工作树、deb 与 box SHA256、系统、时间、每步结果。box 版本在 Vagrantfile 固定；长期复现应保留获准使用的 box 和哈希，使用 `BILIX_BOX_UBUNTU2204`、`BILIX_BOX_UBUNTU2404`、`BILIX_BOX_DEBIAN12`、`BILIX_BOX_DEBIAN13` 指向本地/私有 box。不要提交镜像或密钥。

## 可见 X11 与真实操作

基础安装通过后单独准备可见桌面。以下在 `tests/vm` 执行，以 Debian 12 为例：

```powershell
vagrant up debian12 --provider=virtualbox
vagrant ssh debian12 -c "sudo sh /bilix-host/tests/vm/desktop-setup.sh"
vagrant reload debian12
```

`desktop-setup.sh` 为本项目测试用户准备 XFCE/LightDM、中文字体和 X11 工具。安装 **manifest 选定的精确 deb** 后，在已登录桌面运行 `bilix-gui`，检查中文 IME 输入/提交、目录选择器回填、二维码、键盘、缩放和窗口退出。不要用 `*_amd64.deb` 通配符选择多个旧候选。

VM 登录由维护者使用本机保存的测试凭据；认证/锁屏页面不由脚本填写。SSH 使用 `vagrant ssh <目标>` 的专用测试密钥。口令不进入文档、日志或命令参数，生产部署仍使用 bilix 的专用 SSH 密钥。

可见窗口、IME、文件选择器与授权框由维护者手动或经授权的界面工具操作；SSH/CLI 负责包管理、自检、进程和结果核对。历史 `native-x11-acceptance.py` 包含 xdotool 输入/窗口控制，不作为无上下文 AI 可直接执行的当前通用入口。

## 完整 Wayland

[full-wayland-acceptance.py](../tests/vm/full-wayland-acceptance.py) 必须在已登录、可见的 GNOME 或 KDE Wayland 会话中运行。先准备最终 deb 与 `/home/vagrant/bilix-work/.venv` 的 GUI 运行环境；该脚本不安装桌面、不填写认证页：

```powershell
vagrant ssh ubuntu2204 -c '/home/vagrant/bilix-work/.venv/bin/python /bilix-host/tests/vm/full-wayland-acceptance.py --desktop GNOME'
vagrant ssh ubuntu2204 -c '/home/vagrant/bilix-work/.venv/bin/python /bilix-host/tests/vm/full-wayland-acceptance.py --desktop KDE'
```

分别进入对应会话后执行，结果位于 `build/validation/native/`。核对 VM 显卡、3D 和显示配置，Vagrant reload 会重新应用 Vagrantfile；某版使用过的桌面/分辨率不是下一版默认事实。

冻结程序与生产窗口的脚本动作不等同真实物理 IME 输入。无头 Weston 只证明协议启动；Xvfb/Qt offscreen 不证明完整 Wayland。Linux GUI 更新授权必须从实际桌面发起；SSH 没有授权代理而失败不能用 sudo 安装替代此项。

## 判定

按 [testing.md](testing.md) 与 [validation-template.md](validation-template.md) 填写通过/失败/未验证/不适用。授权账号下载、APT 公网验签/升级、可见桌面、IME 和各 Wayland 会话分别留证；不能从自动矩阵成功推断它们通过。生产服务器和其他 VM 不在此流程范围。

# 安装与更新

1.7.6 开始，Windows 10 或以上 x64 GUI 的绿色版、安装版，以及 Ubuntu 22.04/24.04、Debian 12/13 amd64 deb 支持应用内更新。1.7.5 及更早版本先手动安装新版。CLI、pip 和源码环境继续使用原环境的包管理命令升级。

## 应用内更新

启动时检查一次，之后每 30 分钟检查；默认开启，托盘隐藏时仍检查。设置中可关闭自动检查，帮助菜单“检查更新”始终可用。

发现新版后后台下载当前安装形式所需的文件，左下角显示进度，可以取消。GitHub 不可用或包校验失败时改用 `https://bilix.djhx.site`。元数据 Ed25519 验签和安装包大小/SHA256 校验全部通过后，才显示“更新”。不会自动安装。

点击“更新”后，等待当前整批账号或下载操作完成，再备份配置、退出、安装并重新打开。等待期间可以取消等待。草稿和列表历史不会跨重启保留，已下载文件不受影响。

1.7.9 修复了绿色版退出后未替换/重启的问题。旧 portable 客户端使用自身携带的协调器，下载新包不能修正旧逻辑；1.7.6–1.7.8 绿色版用户需要一次手动替换，步骤见[修复与迁移](portable-update-fix.md#用户迁移)。遇到点击后退出但未更新，保留事务诊断供本地排查。实际发行和验收状态见[版本记录](validation-1.7.9.md)。

- **Windows 绿色版**：更新原 EXE，即使改名或位于中文/空格路径也适用。成功后上一版本保存在同目录、原文件名追加 `.previous.exe`；下一次更新成功前保留。目录不可写或其他实例占用时保留下载包，可手动替换。
- **Windows 安装版**：使用原安装目录，显示 Inno 安装向导；取消或安装失败时保留诊断，安装成功而新版启动失败需按提示人工恢复。不自动重启操作系统。
- **Linux deb**：弹出系统管理员授权窗口，授权后通过 APT 安装本次已验证的 deb，再以原普通用户启动 GUI。取消授权则保留包并重新打开旧版；无桌面授权代理时使用下述手动命令。GUI 不收集管理员密码，不以 root 运行。

更新按钮旁“更新文件”可打开缓存。事务的 `helper.log`、`install.log`、`result.json` 和配置备份位于用户缓存 `djhx-bilix/updates/transactions/`（Windows 缓存路径含 `Cache`）。配置备份不复制账号 token。

## 手动安装和官网备用下载

[GitHub Release](https://github.com/Koril33/bilix/releases/latest) 和 [官网](https://bilix.djhx.site/) 提供相同发行文件。官网备用文件使用 `/releases/v版本号/文件名`，各版 `SHA256SUMS.txt` 可用于手动核对。Windows 绿色版同时提供许可证/对应源码 ZIP，请一并保存。

退出应用后，绿色版替换 EXE；安装版运行新版 Setup；Linux：

```bash
# 将 VERSION 换为发行页所选版本，文件名以下载结果为准。
sudo apt install ./djhx-bilix-gui_VERSION-1_amd64.deb
```

卸载和升级保留用户目录内配置及下载文件；手动恢复较旧 Windows 安装版可能要先卸载新版。

## Ubuntu/Debian 的签名 APT 源

源地址为 `https://bilix.djhx.site/apt/`，suite 为 `stable`，component 为 `main`，架构为 `amd64`。独立 APT 公钥完整指纹：

```text
201A 20E1 04EF 3C72 CE57 3F7E 6132 3BAA 3BB8 7821
```

本源已经上线，Ubuntu 22.04/24.04 和 Debian 12/13 的 Signed-By 验签与跨版本升级均通过，详见 [验收记录](validation-1.7.6.md)。首次配置：

```bash
sudo apt update
sudo apt install curl gnupg
sudo install -d -m 755 /etc/apt/keyrings
curl -fsSLo /tmp/bilix-archive-key.asc \
  https://bilix.djhx.site/apt/keys/bilix-archive-key.asc
gpg --show-keys --with-fingerprint /tmp/bilix-archive-key.asc
# 核对上面完整指纹后安装公钥。
sudo install -m 644 /tmp/bilix-archive-key.asc /etc/apt/keyrings/bilix-archive-keyring.asc
sudo tee /etc/apt/sources.list.d/bilix.sources >/dev/null <<'EOF'
Types: deb
URIs: https://bilix.djhx.site/apt/
Suites: stable
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/bilix-archive-keyring.asc
EOF
sudo apt update
sudo apt install djhx-bilix-gui
```

之后可以随系统软件一起更新，或只运行 `sudo apt install --only-upgrade djhx-bilix-gui`。GUI 不会自动添加源，也不会替用户升级整个系统。APT 源使用官网服务器，仍可随时下载 deb 本地安装。

# 应用更新开发与发布指南

日期：2026-10-11。依据：[已确认的更新方案](application-update-plan.md)。D03、D04 已获维护者批准，本文记录 1.7.6 的实现契约与发布步骤。完整自动回归、实际安装事务与公网发布结果见 [1.7.6 验收记录](validation-1.7.6.md)，不以早期试编译结果代替发行验收。

## 1. 实现范围与入口

| 部分 | 入口 | 行为 |
| --- | --- | --- |
| 元数据验证 | [protocol.py](../src/djhx_bilix/updater/protocol.py) | Ed25519 验原始字节、拒绝重复键/未知 schema、序号防倒退、清单 SHA256 绑定、限制来源与安装身份 |
| 网络与缓存 | [client.py](../src/djhx_bilix/updater/client.py) | GitHub 优先、服务器备用；文件损坏也回退；仅下载当前 GUI 包；缓存重新校验与跨实例准备锁 |
| GUI | [updates.py](../src/djhx_bilix/gui/updates.py) | 启动和每 30 分钟检查；设置开关；帮助里的手动检查；左下角进度、取消、更新按钮、更新文件入口 |
| 退出与安装 | [apply.py](../src/djhx_bilix/updater/apply.py)、[processes.py](../src/djhx_bilix/updater/processes.py) | 独立协调器等待真正退出，再验证并替换/安装；普通用户重启与简单启动结果 |
| Windows 安装器 | [bilix-gui.iss](../scripts/installer/bilix-gui.iss) | `/BILIXUPDATE` 抑制安装器自身重启入口，协调器成为唯一重启者；保留向导和禁止自动重启系统 |
| Linux 授权 | [polkit action](../scripts/installer/site.djhx.bilix.update.policy) | 固定系统程序 + `--install-deb`，每次管理员授权；不允许 GUI 以 root 运行 |
| 签名与镜像 | [update_release.py](../scripts/update_release.py)、[publish_update.py](../scripts/publish_update.py) | 本地签名；完整验签/文件核验后上传，最后切换服务器 stable 入口 |
| APT 与 HTTP | [publish_apt.sh](../scripts/publish_apt.sh)、[Nginx locations](../scripts/server/bilix-update-locations.conf) | 独立 GPG 签名静态快照、保留旧索引/包；资源缺失明确 404 |

CLI 不导入或调度更新器，`cryptography` 只加入 GUI 可选依赖。pip/源码 GUI 没有冻结发行身份，手动检查会说明应使用原环境管理方式升级。Windows onefile、standalone 和 Linux standalone 构建分别嵌入 `distribution.json`，不把该身份文件写进源码或普通 wheel。

GUI 点击更新时，正在执行的整批操作继续完成；等待期间可以取消等待。不会在单个视频结束时抢占本批剩余任务。更新下载和账号/媒体工作线程独立，托盘隐藏也继续检查。真正退出则取消网络准备并等待更新线程结束。

## 2. 协议 1

正式入口固定为：

```text
https://github.com/Koril33/bilix/releases/latest/download/stable.json
https://bilix.djhx.site/updates/stable.json
```

对应签名均为原地址追加 `.sig`。各版同内容快照放在 GitHub 正式 Release，以及 `https://bilix.djhx.site/releases/vX.Y.Z/`。每个版本的四份文件是 `stable.json`、`stable.json.sig`、`update-manifest.json`、`update-manifest.json.sig`。禁止在发布后重写这些版本文件。

两类 JSON 均使用 UTF-8，`schema: 1`、`product: "bilix"`、`channel: "stable"`。签名覆盖**文件原始字节**，格式化、更换换行或排序后都必须重新签名。元数据上限 256 KiB，更新包上限 2 GiB；未知 schema、重复键、错平台/架构、危险文件名和非预期 URL 均拒绝。

`stable.json` 的必要字段：

```json
{
  "schema": 1,
  "product": "bilix",
  "channel": "stable",
  "version": "X.Y.Z",
  "release_tag": "vX.Y.Z",
  "metadata_sequence": 1,
  "issued_at": "UTC ISO 8601 时间",
  "manifest_bytes": 1234,
  "manifest_sha256": "实际清单原字节的 64 位小写 SHA256",
  "manifest_urls": [
    "https://github.com/Koril33/bilix/releases/download/vX.Y.Z/update-manifest.json",
    "https://bilix.djhx.site/releases/vX.Y.Z/update-manifest.json"
  ]
}
```

示例占位值不可直接上线。`metadata_sequence` 为正整数，每次正式渠道变更递增；相同序号只能发布完全相同的字节。客户端在验签并验证清单后保存已见序号和渠道哈希，拒绝序号倒退或同序号换内容。首期不设置 `expires_at`，因此不能发现长期重放仍有合法签名的旧 JSON；`issued_at` 只是发布信息，不冒充新鲜度证明。

`update-manifest.json` 包含同一版本/标签、`published_at`、`release_notes_url`、`min_updater_schema: 1`、`config_compatibility: "backup-before-migration"` 和 `artifacts`。发布工具导入最终发行集合全部文件的真实哈希，GUI 按下面三个身份选择唯一安装包：

| artifact_id | platform / arch | package_type / install_scope | package_version / 系统约束 |
| --- | --- | --- | --- |
| windows-x64-portable | windows / x64 | portable / user | X.Y.Z；Windows 10 或以上 |
| windows-x64-installer | windows / x64 | installer / user | X.Y.Z；Windows 10 或以上 |
| linux-amd64-deb | linux / amd64 | deb / system | X.Y.Z-N，正整数修订；glibc 2.35 或以上 |

各安装记录必须有 `filename`、`bytes`、`sha256`、`urls`、`os_constraints`；两个 URL 固定由版本标签和文件名生成，不接受清单下发命令、本地路径或安装参数。支持 GitHub 官方资产 CDN 的 HTTPS 重定向，拒绝 HTTP、URL 用户密码和其他来源。更新请求不使用 Bilibili 会话、cookies 或 token。

相同应用版本的 Linux 修订用 `dpkg --compare-versions` 比较；发行目录可用 `vX.Y.Z-rN`，不覆盖旧文件。正式 stable 只接受三段版本，预览安装不自动跨入 stable。

`.sig` 是小型 JSON 容器：

```json
{
  "format": 1,
  "algorithm": "Ed25519",
  "key_id": "bilix-ed25519-d9accaf9f50348e6",
  "signature": "64 字节 Ed25519 签名的标准 Base64"
}
```

公钥用标准 Base64 编码的 32 字节 Ed25519 原始公钥，随 [update-keys.json](../src/djhx_bilix/assets/update-keys.json) 交付。网络提供的公钥仅用于公开核对，**不能自动新增信任根**。验签依赖锁定 `cryptography 50.0.2`；Python 3.11 及现有 3.14 构建对应 wheel 见 [官方发行](https://pypi.org/project/cryptography/50.0.2/) 和 [变更记录](https://cryptography.io/en/50.0.2/changelog/)。

## 3. 本地密钥保管

本轮生成的应用更新 key ID 是 `bilix-ed25519-d9accaf9f50348e6`。维护者电脑上：

```text
私钥：C:\Users\ABC\.bilix-release\keys\update-ed25519.key
本机备份：C:\Users\ABC\.bilix-release\backup\update-ed25519.key
SSH 上传私钥：C:\Users\ABC\.ssh\bilix-release-ed25519
```

这三者用途不同，更新签名私钥是 32 字节原始密钥，不能当 SSH key 使用。两份应用私钥已移除继承访问权限，仅授予当前维护者账户访问；内容不进入仓库、公开包或服务器。

本机备份不抵御整盘损坏。按 D04 已完成受保护备份和实际恢复签名验证；建议维护者另存到自己的加密离线介质或安全设备，本轮没有验证异地介质。备份不能上传 Web 服务器。独立 APT GPG 密钥在 Linux 发布环境中生成、备份并恢复验证，不复用应用或 SSH 私钥。APT 公钥指纹为 `201A20E104EF3C72CE573F7E61323BAA3BB87821`，私钥留在仓库外的 `/home/vagrant/.bilix-release/apt-gnupg`；另有维护者 Windows 私有目录内的受保护备份。

以后新建密钥的命令仅供灾备/另一个项目参考；**不要对现有密钥重复执行**，工具拒绝覆盖旧私钥和信任文件：

```powershell
uv run --locked --extra gui python scripts/update_release.py keygen `
  --private-key C:/Users/ABC/.bilix-release/keys/update-ed25519.key `
  --backup-key C:/Users/ABC/.bilix-release/backup/update-ed25519.key
```

更换密钥要有意更新内置公钥，并通过仍受信的新版本或人工安装交付；首期不实现网络自动换根。

## 4. 安装事务与恢复

更新包通过完整校验后才显示“更新”。点击按钮允许开始安装；草稿、列表历史和当前会话不跨重启持久化，更新状态提示明确说明这一点。

1. 等当前工作线程整批结束，阻止新操作，保存偏好。
2. 把 `config.toml`、`gui.ini` 备份到本次事务目录，不复制/迁移 `token.txt`。
3. 准备独立协调器并等待它写就绪标记：portable 复制外部 EXE，standalone 复制完整运行时到用户缓存，避免安装时协调器被删除或 DLL 缺失。这不是重新下载另一个平台的包。
4. 应用执行真正退出；协调器等待 GUI 和 onefile 外壳，检测同路径其他实例；不杀其他进程、不只隐藏到托盘。
5. 安装前重新验签和校验缓存。Windows portable 在原目录写新文件并验证，重命名保留旧 EXE；Inno 保留向导并使用 `/NORESTART`；Linux 发起 polkit 授权。
6. 协调器以原普通用户启动新 GUI。新 GUI 创建主窗口并进入事件循环后写版本结果标记；最多等待 60 秒。这是首期简单启动确认，不证明任意后续操作都正常。

绿色版新程序确认启动后，旧 EXE 保存在原文件名追加 `.previous.exe` 的位置；下一次更新成功前保留这份备份。新 EXE 已退出而启动失败时恢复本次旧 EXE；如果新进程仍占用文件，保留事务备份并报告手动恢复，不强行结束它。替换第二步失败会立即恢复旧目标。只读位置/空间不足/其他副本占用时不提权覆盖，更新包可从“更新文件”入口取出，供用户手动升级。

Inno 原有安装失败恢复与新版启动失败分开记录：安装失败看 `install.log` 和原 `runtime.previous`；安装成功而启动失败时提供诊断和人工恢复提示，不承诺自动回滚整个安装。旧安装器会拒绝降级，人工恢复可能要先卸载新版再安装已验证的旧版；用户配置和下载目录独立保留。

Linux 调用固定 `/usr/lib/djhx-bilix-gui/bilix-gui --install-deb`，在导入 Qt 前分派。root 入口再次验证内置公钥签名，把用户缓存 deb 复制到 root 控制的临时目录后验证该副本，检查内部包名/版本/amd64，再调用固定 `apt-get -y --no-remove ... install`；拒绝降级，不运行来自清单的命令，不启动 root GUI。deb 打包显式规范目录/可执行文件为 0755，数据和不可执行库为 0644，并由 dpkg 设置 root 所有权，防止提权入口加载可写库或公钥。`pkexec --disable-internal-agent` 要求桌面授权代理；取消/无代理时保留包并重新打开普通用户应用。[pkexec 参数与授权模型](https://polkit.pages.freedesktop.org/polkit/pkexec.1.html)

事务记录位于平台 `djhx-bilix` 用户缓存的 `updates/transactions/<随机ID>/`，包含配置备份、`helper.log`、`install.log`、请求/启动/结果标记和协调器副本。普通下载缓存按 SHA256 分目录，重新使用前仍须验签和验证文件；缓存不是信任根。中断下载的 `.part` 不拼接到其他镜像。

## 5. 第一份正式签名发行

必须完成实际平台升级验收，再按既有 [构建发行指南](gui-build-and-release.md) 构建全部产物。1.7.6 从最终产品源码重新冻结，1.7.5 仅作为已发行升级基线。

1. 构建 Windows onefile/standalone、Inno、Linux deb、CLI 和 Python 产物，收集许可和源码，执行原有最终发行集合校验。
2. 在全新 staging 目录签名；首次序号为 1，之后必须大于已发布序号。示例 `X.Y.Z` 要替换成实际版本：

```powershell
uv run --locked --extra gui python scripts/update_release.py sign `
  --directory dist/release-X.Y.Z `
  --private-key C:/Users/ABC/.bilix-release/keys/update-ed25519.key `
  --sequence 1
```

工具校对最终集合所有文件，确保三类 GUI 安装包齐备，验证自己生成的签名后输出四份文件及公开 `update-keys.json`。不覆盖已签元数据；如产物改变，重建 staging，再签新发行。私钥只在本地读取，不打印内容。

3. 建 GitHub 草稿，附全部原发行文件、四份元数据/签名和公开密钥；在不可变发行发布前完成资产上传。服务器同字节镜像使用：

```powershell
uv run --locked --extra gui python scripts/publish_update.py `
  --directory dist/release-X.Y.Z `
  --ssh-key C:/Users/ABC/.ssh/bilix-release-ed25519
```

该工具上传到 `bilix@djhx.site` 的临时目录，服务器校验后移动到 `/releases/vX.Y.Z/`，拒绝覆盖已存在版本，最后更新 `/updates/stable.json[.sig]` 和公开密钥。上传锁防止同时发布；失败的 `.staging-*` 留待维护者核查，工具不递归删除公开版本。两份 stable 文件无法作为一个普通文件原子切换，短暂不同步必须靠验签失败/稍后重试处理，不能跳过签名。

4. 第一次上线由管理员把 [locations 配置](../scripts/server/bilix-update-locations.conf) 加入现有 HTTPS server，再执行 `nginx -t` 和平滑 reload。资源路径缺失必须 404，不能落到官网 HTML 200；JSON 使用 no-cache，版本文件 immutable。不要上传私钥或把发布账户加到 sudo。
5. 验证服务器所有产物、JSON/签名 HTTPS 地址和 GitHub 草稿资产，发布 GitHub latest。两端切换窗口允许验签失败后重试，整个版本文件齐备前不要让任一渠道入口引用它。首次正式上线期间还须核对 GitHub 实际 CDN 与 TLS 在打包运行时可用。

## 6. 独立签名 APT 源

在维护者 Linux 工作站或构建 VM 中安装 `aptly`、`gnupg`、`dpkg`、`python3`，私钥保存在仓库外的 `GNUPGHOME`。1.7.6 使用独立 GPG 签名的 `stable/main/amd64` 源，公开 URL 和四发行版安装结果见验收记录。deb 显式使用 xz，以兼容 Ubuntu 22.04 自带的 aptly 1.4。

```bash
export GNUPGHOME="$HOME/.bilix-release/apt-gnupg"
install -d -m 700 "$GNUPGHOME"
# 交互设置并妥善备份独立密钥；不要把口令写进脚本或命令行。
gpg --quick-generate-key 'BiliX APT <dingjinghui33@163.com>' ed25519 sign 0
gpg --list-secret-keys --with-colons
# 将下面 FULL_FINGERPRINT 换成刚生成密钥的完整指纹。
sh scripts/publish_apt.sh /path/to/djhx-bilix-gui_X.Y.Z-1_amd64.deb \
  "$HOME/.bilix-release/apt-work" FULL_FINGERPRINT
```

脚本使用 `stable/main`、amd64、`Acquire-By-Hash`；首次 publish，之后 snapshot/switch 并 `-skip-cleanup`。不关闭签名，不强制短 Valid-Until，不设置每周重签；不能因此宣称防止长期冻结。切换参数与行为依据 [aptly publish switch](https://www.aptly.info/doc/aptly/publish/switch/)。

将输出 `public/` **内容**上传到服务器 `/var/www/bilix.djhx.site/apt/`。先上传 pool 与 by-hash 文件，再上传其他索引，**最后替换签名 InRelease/Release.gpg 和 Release**；不直接覆盖一半生成中的本地仓库，不删除旧 pool/by-hash。APT 使用自有服务器，GitHub Release 不是 APT 的第二源。首次发布需从实际公开 URL 验证签名/哈希及至少一个 Ubuntu/Debian 安装，再核对其余目标的依赖。

公布独立 APT 公钥完整指纹后，用户首次配置：

```bash
sudo apt update
sudo apt install curl gnupg
sudo install -d -m 755 /etc/apt/keyrings
curl -fsSLo /tmp/bilix-archive-key.asc \
  https://bilix.djhx.site/apt/keys/bilix-archive-key.asc
gpg --show-keys --with-fingerprint /tmp/bilix-archive-key.asc
# 核对项目公布的完整指纹，再安装 keyring。
sudo install -m 644 /tmp/bilix-archive-key.asc /etc/apt/keyrings/bilix-archive-keyring.asc
sudo tee /etc/apt/sources.list.d/bilix.sources >/dev/null <<'EOF'
Types: deb
URIs: https://bilix.djhx.site/apt/
Suites: stable
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/bilix-archive-keyring.asc
EOF
sudo apt update && sudo apt upgrade
```

不要在源尚未上线时把上述命令宣传成已可用，也不使用 `apt-key add`/`trusted=yes`。保留 `sudo apt install ./新版.deb` 永久备用；GUI 不代用户执行全系统 `apt upgrade`，不自动添加 APT 源。

## 7. 验收与发行

维护者指定 1.7.6 做较全面验收。协议、真实 HTTPS 传输与双源故障、缓存篡改、取消、绿色替换恢复、配置备份、root 暂存与身份限制、GUI 开关/周期/等待本批/托盘退出纳入 [更新测试](../tests/updates/test_protocol.py)、[传输测试](../tests/updates/test_transport.py) 和 [GUI 测试](../tests/gui/test_updates_gui.py)。这些自动检查与真实 Windows/Linux 安装事务、公网 APT 源验收分别记录，不能互相代替。

```powershell
uv run --locked --extra gui --group gui-test pytest tests/updates `
  tests/gui/test_updates_gui.py tests/gui/test_ui_fixes_gui.py tests/gui/test_compact_gui.py `
  tests/test_gui_build_identity.py tests/test_gui_deb_packaging.py tests/test_gui_licenses.py -q
```

Windows CPython 3.14.8 和最低版本 3.11.2 完整 GUI profile 各通过 403 项；3.11 的 CLI 隔离环境通过 305 项且未安装 Qt/cryptography。Ubuntu 22.04 通过 397 项，6 项 Windows 专用跳过有对应 Windows 通过证据。真实冻结程序、两种 Windows 包、四发行版 deb、公网 APT、发布回下载、许可与源码核对的最终结果以 [1.7.6 验收记录](validation-1.7.6.md) 为准。

应用签名和 APT 签名备份均实际恢复并签名验证；公钥随发行公开，私钥没有进入仓库、归档或 Web 服务器。异地离线备份建议由维护者另行保存。CLI 构建显式排除 updater/Qt/cryptography；GUI 材料包含新增 cryptography 的 Apache/BSD notices。

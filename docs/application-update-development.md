# 应用更新协议与实现

原生 GUI 自 1.7.6 提供签名更新；CLI、pip/uv 和源码运行按原安装方式升级。当前发布/部署命令集中在 [releasing.md](releasing.md)，用户操作见 [gui-updating.md](gui-updating.md)，缺陷见 [workflow-issues.md](workflow-issues.md)。初次上线指南和当时环境/计数保留在 [archive/update-1.7.6.md](archive/update-1.7.6.md)。

## 实现入口

| 部分 | 入口 | 契约 |
| --- | --- | --- |
| 验签/身份 | [protocol.py](../src/djhx_bilix/updater/protocol.py) | Ed25519 验原字节，拒绝重复键、未知 schema、错身份和危险地址 |
| 获取/缓存 | [client.py](../src/djhx_bilix/updater/client.py) | GitHub 优先、官网备用；缓存重验签/哈希，仅选当前 GUI 包 |
| 界面 | [gui/updates.py](../src/djhx_bilix/gui/updates.py) | 启动及每 30 分钟检查，自动下载/可取消，验完后点击安装 |
| 安装协调 | [apply.py](../src/djhx_bilix/updater/apply.py)、[processes.py](../src/djhx_bilix/updater/processes.py) | 等待真正退出、复核包、替换/安装、普通用户重启与结果 |
| Windows 安装器 | [bilix-gui.iss](../scripts/installer/bilix-gui.iss) | 用户安装向导；更新抑制安装器自身重启，由协调器一次重启 |
| Linux 授权 | [polkit action](../scripts/installer/site.djhx.bilix.update.policy) | 固定系统入口、管理员授权、普通用户 GUI |
| 本地签名/镜像 | [update_release.py](../scripts/update_release.py)、[publish_update.py](../scripts/publish_update.py) | 八项集合校验，本地签名，bilix 镜像上传后切 stable |
| APT/HTTP | [publish_apt.sh](../scripts/publish_apt.sh)、[publish_apt.py](../scripts/publish_apt.py)、[Nginx locations](../scripts/server/bilix-update-locations.conf) | 本地独立 GPG 快照，完整树验签后按顺序上传/切换；签名索引非整体原子，缺失资源明确 404 |

`cryptography` 仅在 GUI extra。冻结 Windows onefile/standalone 与 Linux standalone 嵌入 `distribution.json` 和受信公钥；普通 wheel/源码无冻结发行身份。

## 协议 1

正式入口及对应 `.sig`：

```text
https://github.com/Koril33/bilix/releases/latest/download/stable.json
https://bilix.djhx.site/updates/stable.json
```

版本快照放在 GitHub 正式 Release 与官网 `/releases/vX.Y.Z/`，包含 `stable.json`、`stable.json.sig`、`update-manifest.json`、`update-manifest.json.sig`。发布后不可改写。JSON 为 UTF-8，签名覆盖文件原字节；格式化或换行变化使签名失效。元数据最多 256 KiB，包最多 2 GiB。

`stable.json` 必须提供 schema 1、product `bilix`、channel `stable`、应用版本/标签、正整数 `metadata_sequence`、`issued_at`、清单字节数/SHA256/两源 URL。每次正式渠道变更递增序号；同序号只能用完全相同字节。客户端保存已见序号和渠道哈希，拒绝倒退与同序号换内容。首期无 `expires_at`，无法发现一直重放的合法旧元数据；`issued_at` 不证明新鲜度。

`update-manifest.json` 提供同版本/标签、发布时间、说明 URL、最低 updater schema、配置兼容策略与所有最终文件哈希。GUI 按下列身份选择唯一包：

| artifact_id | 平台/架构 | 类型/范围 | 版本与系统约束 |
| --- | --- | --- | --- |
| windows-x64-portable | windows/x64 | portable/user | X.Y.Z；Windows 10+ |
| windows-x64-installer | windows/x64 | installer/user | X.Y.Z；Windows 10+ |
| linux-amd64-deb | linux/amd64 | deb/system | X.Y.Z-N；glibc ≥2.35 |

每项有安全 filename、bytes、sha256、urls、os_constraints。URL 固定为版本标签和文件名，不接受远端命令、路径或安装参数。支持 GitHub 官方 CDN 的 HTTPS 重定向，拒绝 HTTP、URL 用户密码和其他来源。更新请求不携带 Bilibili Cookie/token。

Linux 同应用版本修订用 dpkg 比较，独立版本目录可为 `vX.Y.Z-rN`；默认完整集合工具仍按源码应用版本与默认修订组织，修订发布须另核对工具接口，不直接覆盖原目录。stable 只接受三段版本，Preview 不自动跨入 stable。

签名容器使用 format 1、algorithm `Ed25519`、key_id、64 字节签名 Base64。受信公钥为 [update-keys.json](../src/djhx_bilix/assets/update-keys.json) 的 32 字节原始公钥 Base64；网络公钥仅供公开核对，不能自动加入信任根。

## 安装事务与恢复

点击前只准备包；下载/验证不抢占媒体/账号线程。点击后等待活动和等待批次结束，可取消等待；真正退出取消网络准备并等待 worker。草稿/队列/会话历史不跨重启，已完成下载保留。

1. 保存偏好并备份 `config.toml`、`gui.ini`，不复制 `token.txt`。
2. 在用户缓存准备独立协调器：portable 复制旧外部 EXE，standalone 复制完整 runtime；它必须在目标运行目录被替换后仍可执行。
3. 等 GUI、onefile 外壳及同路径实例真正退出，不杀其他进程、不用隐藏托盘代替退出。
4. 协调器再次验签/校验缓存，按发行身份安装。
5. 原普通用户启动新 GUI，主窗口/事件循环就绪后写版本标记，最多等待 60 秒；这只证明基础启动。

portable 新包先写目标目录并校验，旧 EXE 备份为原文件名追加 `.previous.exe`。替换失败恢复旧目标；新进程已退出但不就绪时恢复旧 EXE，仍占用时保留诊断供手动恢复。只读位置/空间不足/其他副本占用不提权覆盖。**安装协调器来自旧客户端**，新包中的修复不能自动改变旧协调器；当前迁移限制见问题登记。

Inno 使用 `/NORESTART` 与 `/BILIXUPDATE`，安装失败恢复和安装成功后启动失败分别记录。后者不承诺自动回滚完整安装，人工恢复旧版可能先卸载新版。

Linux 固定入口为 `/usr/lib/djhx-bilix-gui/bilix-gui --install-deb`，在导入 Qt 前分派。root 再次验签，将 deb 复制到 root 控制临时目录后核验包名、版本、amd64，再调用固定 apt-get install；拒绝降级。deb 中系统入口/库/公钥均不可由普通用户写。pkexec 要求桌面授权代理，取消/无代理保留包并回到普通用户应用；不运行 root GUI。

缓存事务位于用户 `djhx-bilix/updates/transactions/<ID>/`（Windows 含 Cache），包括配置备份、helper/install 日志、请求/启动/结果与协调器副本。缓存按哈希保存且重新使用必复验；它不是信任根，也不是持久下载队列。

## 密钥与发布

应用 Ed25519、APT GPG、SSH 密钥相互独立，现有私钥继续留在仓库外，正常发布不运行 keygen。更换信任根必须有意更新内置公钥，并经仍受信的新版本或人工安装交付；首期没有网络自动换根。

当前 APT 公钥完整指纹为 `201A20E104EF3C72CE573F7E61323BAA3BB87821`。历史本机备份恢复验证只证明当时材料可恢复，不替代后续保护/灾备。私钥不上传 Web 服务器、不进入公开归档。

发布按 [releasing.md](releasing.md) 冻结/校验/签名，服务器全用 `bilix@djhx.site` 与既有专用 SSH 密钥；应用更新、APT、官网各自公开回验。Nginx/TLS/首次系统配置由管理员管理，正常资源部署不用 sudo。

## 验证边界

自动协议/传输/恢复测试在 `tests/updates/`，界面检查在 `tests/gui/test_updates_gui.py`。真实 frozen portable/installer/deb、安装故障、系统授权及双源 HTTPS 行为按 [testing.md](testing.md) 和平台流程另行验证。准确计数与环境写在当版记录；1.7.6 初次上线结果见 [validation-1.7.6.md](validation-1.7.6.md)，不能沿用它证明当前候选。

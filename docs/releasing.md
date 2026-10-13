# 维护者发布与部署流程

本项目在本地测试、原生构建并手动发布。普通推送、标签和 PyPI 上传不会自动部署官网。本文是当前流程；当版结果使用 [验收模板](validation-template.md)，历史结果从 [文档索引](README.md) 查找。

公开版本、标签和同版本 PyPI 文件保持不可变。修正产品或发行材料必须使用未发布的新版本；不要用本文重包已发布的 1.7.8。当前缺陷和流程缺口见 [workflow-issues.md](workflow-issues.md)。

## 1. 冻结候选与证据

1. 查看当前缺陷、未实现功能和改动范围；将实际发布范围写入 CHANGELOG，发布日期在正式发布前保持未发布。
2. 版本唯一来源为 `src/djhx_bilix/__init__.py`；同步 `uv.lock`、发行文档和页面版本链接，审查 Git diff 与暂存内容。
3. 按 [testing.md](testing.md) 完成影响范围的回归，绑定提交、工作树、工具链、平台和最终输入哈希。产品或构建输入变更须重编译受影响程序。
4. 运行凭据扫描并复核发现；确认 FFmpeg/Qt/运行依赖许可和对应源码获取材料完整。

```powershell
uv run --locked python scripts/check_secrets.py --scope working-tree
uv run --locked python scripts/check_secrets.py --scope history
$version = uv run --locked python -c "from djhx_bilix import __version__; print(__version__)"
$releaseDir = "dist/release-$version"
$sshKey = Join-Path $env:USERPROFILE '.ssh/bilix-release-ed25519'
```

扫描依赖独立安装的 Gitleaks，缺失时按脚本报错准备它；不关闭扫描来取得通过。真实 Cookie、token、密码、二维码和私钥不得进入仓库、归档、日志或命令文本。发生泄露先撤销凭据，删除文件或本地 logout 不足以证明服务器会话撤销。FFmpeg 来源与许可见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 2. Python 包与最低版本验证

```powershell
uv build --out-dir "dist/python-$version"
uvx twine check "dist/python-$version/djhx_bilix-$version-py3-none-any.whl" `
  "dist/python-$version/djhx_bilix-$version.tar.gz"
```

在本轮隔离虚拟环境安装最终 wheel，验证元数据、两个 CLI 命令名、模块入口、帮助/doctor/纠错/补全与 GUI extra。CLI 环境不得安装 Qt/cryptography。最低支持 Python 3.11 单独执行；完整 GUI 回归还需 pytest-qt。不要覆盖日常工具安装来证明候选可用。

例如隔离 CLI 环境：

```powershell
uv venv --python 3.11 "build/wheel-cli-$version"
$wheelPython = "build/wheel-cli-$version/Scripts/python.exe"
uv pip install --python $wheelPython "dist/python-$version/djhx_bilix-$version-py3-none-any.whl"
& $wheelPython -c "import importlib.metadata as m; print(m.version('djhx-bilix'))"
& $wheelPython -m djhx_bilix --help
& $wheelPython -m djhx_bilix doctor
```

Linux 解释器路径为对应环境的 `bin/python`。这是包安装/入口检查，不等同完整最低版本回归。wheel/sdist 的路径、内容、版本与许可由最终集合检查继续验证。

## 3. 构建、集合与最终只读检查

Windows CLI 按 [build.md](build.md#windows-cli-exe)，GUI 两平台按 [gui-build-and-release.md](gui-build-and-release.md) 原生构建和验收。同一发行的八项产物必须来自同一产品源码版本：

| 类别 | 最终文件 |
| --- | --- |
| Windows GUI | Portable EXE、Setup EXE、许可证/源码 ZIP |
| Linux GUI | amd64 deb、对应源码 tar.gz |
| Python | wheel、sdist |
| Windows CLI | EXE/许可/源码 ZIP |

将两平台 GUI 产物及平台清单放在 `dist/gui/`，Python 放在 `dist/python-$version/`，CLI 放在 `dist/cli/`，然后：

```powershell
uv run --locked --extra gui python scripts/assemble_release.py
uv run --locked --extra gui --group gui-test python scripts/validate.py `
  --profile gui --strict-skips --release-dir $releaseDir
```

集合脚本调用 GUI 汇总并生成 `dist/release-$version/`、八项 `release-manifest.json` 和 `SHA256SUMS.txt`；它会写文件。第二条命令只读复核集合并重新运行离线回归，不用于改写公开包。Linux 审查平台专用 skip 时按 [测试规范](testing.md) 处理。

归档不得含 `.git`、`.vagrant`、私钥、登录材料、下载媒体或构建缓存。冻结程序编译来源、源码逐文件对应、真实安装/升级与可见桌面证据另行核对；只比较版本号或最终哈希不证明编译来源。文档/许可重包也要刷新对应材料和清单。

### 1.7.1 最终材料收尾

当版两种源码快照与输入比对记录已保留在 [历史材料说明](archive/release-1.7.1-materials.md)。这是历史事实，当前版本按上面的最终冻结流程执行。

## 4. 本地签名

应用 Ed25519 私钥、APT GPG 私钥和 SSH 部署密钥是三种独立材料，均留在仓库外。已有信任根和签名密钥继续使用；正常发布不要重新 keygen。协议与恢复契约见 [application-update-development.md](application-update-development.md)。

签名前核对两处当前 stable 的已发布序号；新正式渠道序号必须更大，不从历史示例复制 `1`。在未签过的最终集合中执行：

```powershell
$updateKey = Join-Path $env:USERPROFILE '.bilix-release/keys/update-ed25519.key'
# 先将 $sequence 设置为已核对的下一个正整数。
uv run --locked --extra gui python scripts/update_release.py sign `
  --directory $releaseDir --private-key $updateKey --sequence $sequence
```

工具核验最终集合，输出并自验 `stable.json`、`stable.json.sig`、`update-manifest.json`、`update-manifest.json.sig` 和公开 `update-keys.json`。签名绑定原始字节；签名后不改文件、换行或内容。发现输入变化须准备新的候选，不能覆盖已公开版本。

<a id="标签镜像与页面"></a>

## 5. 标签、镜像与页面

最终代码与产物对应后才创建新标签。先准备公开发行说明文件，明确已验证平台与接受限制；GitHub 草稿应包含八项产物、最终 manifest/SHA256、四份签名元数据及公开密钥。不要上传整个 build 目录或采用未经核对的通配符。GitHub 草稿不作为可用的 latest 渠道。

服务器常规部署全部使用 **`bilix@djhx.site`** 和维护者已有的 **`.ssh/bilix-release-ed25519`**，覆盖安装包、签名更新、APT 和官网。脚本使用 BatchMode/IdentitiesOnly，不用服务器密码、不切换管理员账号、不申请 sudo。权限漂移交由管理员恢复项目目录权限；Nginx/TLS/服务配置另属系统维护。

已签发行镜像与 stable 切换：

```powershell
uv run --locked --extra gui python scripts/publish_update.py `
  --directory $releaseDir --ssh-key $sshKey
```

脚本验签并核对所有文件，上传服务器 staging、校验 SHA256、拒绝覆盖已存在版本，最后更新 `/updates/stable.json[.sig]`。版本文件位于 `/var/www/bilix.djhx.site/releases/v<版本>/`。两份 stable 的短暂不同步只能等待重新验签，不跳过签名。完整包齐备前不得让公开渠道引用该版本。

将确认的源码提交/新标签同步到 GitHub 与实际维护的 Gitea 镜像，再发布 GitHub 草稿。镜像代码与镜像发行资产分别记录；只推标签不算发行文件镜像完成。PyPI 使用环境提供的 `UV_PUBLISH_TOKEN`：

```powershell
uv publish "$releaseDir/djhx_bilix-$version-py3-none-any.whl" `
  "$releaseDir/djhx_bilix-$version.tar.gz"
```

官网唯一源码为 [site/bilix.html](../site/bilix.html)。先完成 [页面检查](../site/README.md)，并确认下载链接指向完整公开版本，再部署：

```powershell
uv run --locked python scripts/deploy_site.py --check --ssh-key $sshKey
uv run --locked python scripts/deploy_site.py --ssh-key $sshKey
```

页面脚本备份旧首页、校验上传哈希并原子替换 `/var/www/bilix.djhx.site/index.html`。SSH 成功后仍需 HTTPS 回读哈希和链接检查。官网不会随 Git/PyPI 自动更新。

## 6. APT 发布

APT 使用独立 GPG 签名，源为 `https://bilix.djhx.site/apt/`、`stable/main`、amd64。维护者 Linux 发布环境保留仓库外的私钥及**同一持久 aptly 工作目录**，以保留旧 pool/by-hash；正常发布不新建密钥、不清空工作目录。

```bash
# 使用现有受保护的 GNUPGHOME 与已核对最终 deb。
export GNUPGHOME="$HOME/.bilix-release/apt-gnupg"
sh scripts/publish_apt.sh /path/to/final.deb \
  "$HOME/.bilix-release/apt-work" 201A20E104EF3C72CE573F7E61323BAA3BB87821
```

`publish_apt.sh` 只生成并验签本地 `public/`。仓库的 [publish_apt.py](../scripts/publish_apt.py) 负责上传与切换；本地需要 Python ≥3.11、PATH 中的 gpg/gpgv 与 OpenSSH，服务器需要 python3。保留 aptly public 输出的全部实际文件，不只复制 deb、Packages 或部分 by-hash。

aptly 可以只发布 `Contents-amd64.gz`，同时在 Release 声明压缩文件与解压原文的哈希；未压缩 Contents 返回 404 属于正常发布方式，不要人为补文件。核验须检查 `.gz` 本身，再用解压内容核对原文大小及摘要；真正缺失的 Packages、压缩索引、包或必要 by-hash 仍应失败。此行为见 [aptly 1.4 的索引实现](https://github.com/aptly-dev/aptly/blob/v1.4.0/deb/index_files.go#L75-L94)。

aptly 的 `by-hash/Packages*`、`by-hash/Contents*` 等名字别名可能是指向同一 public 内散列实体的符号链接。发布工具只接收普通文件并省略这些别名；保留所有签名索引、包和散列实体。可在 Linux 发布机导出到全新目录：

```bash
apt_source="$HOME/.bilix-release/apt-work/public"
apt_export="$HOME/.bilix-release/apt-public-export"
mkdir "$apt_export"
(cd "$apt_source" && find . -type f -print0 | tar --null -T - -cf -) | tar -C "$apt_export" -xf -
```

将这个普通文件导出目录受控复制到本机忽略的 `build/apt-public/` 后，在仓库根目录使用既有 SSH 密钥：

```powershell
$aptPublic = 'build/apt-public'
Get-Command gpg, gpgv, ssh, scp
uv run --locked python scripts/publish_apt.py --directory $aptPublic --ssh-key $sshKey --check
uv run --locked python scripts/publish_apt.py --directory $aptPublic --ssh-key $sshKey
```

`--check` 验现有独立公钥、双签名、Release/Packages/by-hash 与包哈希，再只读检查服务器身份/权限/不可变文件冲突，不上传或建服务器 lock/staging。实际发布复制并复验固定快照，使用 bilix 发布锁和 staging，按 pool/by-hash → 普通索引 → Release.gpg/Release/InRelease 的顺序切换，不删除旧文件。

三份签名索引分别切换。失败保留 staging 的 manifest、upload.tar 和 status.json（阶段/已完成文件）；核查后重跑相同 public 目录。网络中断若留下 `.publish-lock`，先确认没有仍在运行的发布，核对 owner token 与对应 staging，再按工具诊断恢复；不要删除其他发布的锁或未知路径。

2026-10-13，工具已实际发布 1.7.9，核对并上传 50 个实体文件；已有包和 by-hash 保留，两个逻辑 Contents 由 `.gz` 解压核验。真实 HTTPS 和目标系统升级结果见[本版验收](validation-1.7.9.md)，后续维护项见 [workflow-issues.md](workflow-issues.md)。

用户配置与独立 APT 公钥指纹见 [gui-updating.md](gui-updating.md)。GUI 不自动添加源、不执行全系统升级。

## 7. 公开回验与完成条件

每个渠道独立确认：

- GitHub/官网：回下载全部产物、manifest、SHA256 和签名文件；与本地原字节/哈希一致，版本目录缺失资源返回 404。
- 更新：两处 stable 与签名完整验签，序号/版本一致，三种 GUI 身份选择正确，冻结客户端可检查/下载；切换窗口失败能稍后恢复。
- PyPI：公开安装指定版本，核对元数据、入口、许可与文件哈希。
- APT：从公开 HTTPS 验证签名/索引/包，确认候选版本与目标系统安装或升级；本地 aptly 验签不能代替它。
- 官网：HTTPS 页面 SHA256、当前版本、下载链接、APT 说明与本地一致。

最终在 `docs/validation-<版本>.md` 填写提交/标签、八项哈希、工具链、测试和各渠道状态。脱敏原始日志留在忽略的 `build/`；没有执行的系统、权限、IME 或事务不写通过。发布阻塞与未测限制按 [结果判定](testing.md#结果判定与发布门槛) 处理。

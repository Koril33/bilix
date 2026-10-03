# 维护者发布流程

本项目本地检查、构建并手动上传。推送提交或标签不自动发布。以下以 1.5.0 为例说明流程；当前发行状态以 PyPI 与 GitHub Releases 为准。

## 发布材料与凭据确认

1. 2026-10-03 维护者确认历史 Bilibili 凭据已经失效，本地审计报告按要求删除。今后的泄露须先撤销相应凭据；仅删除文件或执行本地 logout 不足以证明服务器会话撤销。
2. 1.5.0 使用官方 FFmpeg 7.1.5 的明确源码构建。源码归档、许可、构建脚本和哈希记录均已纳入仓库；打包时须保持它们与内置程序一致。见 [第三方声明](../THIRD_PARTY_NOTICES.md)。

这两项应在发布记录中明确确认。它们不能由成功构建、补充一个官网链接或创建 Git 标签代替。

## 版本与代码检查

- 版本唯一来源为 `src/djhx_bilix/__init__.py`；使用从未发布过的新版本号，同步 uv.lock 与 CHANGELOG。
- 在 [CHANGELOG](../CHANGELOG.md) 记录面向用户的变化与实际发布日期。发布前保留“未发布”状态。
- 完成 [构建文档](build.md) 的 Ruff、pytest、系统/解释器与媒体检查。
- 运行 `python scripts/check_secrets.py --scope working-tree`；另运行 history 检查并复核所有发现。测试数据只允许明确虚构值。
- 审查 `git diff`、暂存内容与页面。只提交明确需要的文件，不使用包含私密材料的宽泛目录导入。

## Python 候选包

```shell
uv build --out-dir dist/candidate
uvx twine check dist/candidate/djhx_bilix-1.5.0-py3-none-any.whl dist/candidate/djhx_bilix-1.5.0.tar.gz
```

检查归档清单：应含统一源码、LICENSE、第三方声明；sdist 还包括文档、页面、脚本与测试。不得包含 `.git`、`.env`、token、Cookie、二维码、下载媒体、审计原始报告或构建缓存。

使用隔离工具目录安装候选 wheel（uv 的 `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` 可指向 `build` 内专用目录），检查版本、帮助、doctor、参数纠错与 shell 补全。不要在日常工具环境中强制替换已发布版来证明候选包可用。必要时在最新允许依赖下另做验证，记录实际版本。

PyPI 凭据通过发布环境的 `UV_PUBLISH_TOKEN` 提供，不在命令文本或仓库中保存。材料确认并取得维护者的发布授权后，明确列出本轮产物：

```shell
uv publish dist/candidate/djhx_bilix-1.5.0-py3-none-any.whl dist/candidate/djhx_bilix-1.5.0.tar.gz
```

上传后从 PyPI 安装该版本，核对元数据、文件哈希、版本与命令行为。PyPI 不能覆盖同版本文件；失败修正须使用新版本号。

## Windows 发行

按 [Windows 构建](build.md#windows-exe) 生成并运行真实 exe。发布检查须包含 PowerShell 5.1/7 补全，以及中文/空格路径、最小 PATH、cp1252 环境与参数错误。

推荐发行 zip，包含 `bilix.exe`、LICENSE、THIRD_PARTY_NOTICES、简短使用说明、FFmpeg 完整对应源码与构建材料，以及 Python 和运行依赖许可。standalone 模式必须包含完整运行目录。

onefile 模式可用同一构建环境运行打包脚本，它将 FFmpeg 完整对应源码与构建脚本直接放入 zip，并收集 Python 与运行依赖的许可：

```shell
python scripts/package_windows.py build/windows/bilix.exe dist/candidate/bilix-1.5.0-windows-x64.zip
```

```powershell
Get-FileHash -Algorithm SHA256 'build/windows/bilix.exe'
```

为最终上传的每个文件生成 `SHA256SUMS.txt`。校验文件记录归档或 exe 本身的哈希，不使用某个中间文件替代。发布记录应包含版本、Git commit、解释器/工具链、测试结果、FFmpeg 来源与源码归档哈希。

## 标签、镜像与页面

只有最终代码与产物一致后才创建版本标签（例如 `v1.5.0`）。推送普通提交、标签和上传发行文件是发布步骤，历史清理与强制推送属于另行协调的维护操作。不要为了普通发布覆盖现有标签。

在 GitHub 与实际维护的镜像发行页填写同一版本说明并上传已验证文件，下载后核对 SHA256。旧发行文件保留其真实状态，不能把新功能写成旧版本已有功能。

项目页面唯一源码为 `site/bilix.html`。完成 [页面验证](../site/README.md) 后复制到现有网站；它不会随包上传或 Git 推送自动部署。正式发布后同步 README、CHANGELOG 和页面的未发布提示，保留 FFmpeg 与许可链接。

## 发布记录

本地记录保存于忽略的 `build`，公开发行说明只包含脱敏结果。实际未运行的系统、解释器、下载权限或二进制测试不得标为通过。当前资料缺口、尚未撤销的凭据或失败检查应阻止正式发布，而不是从记录中省略。

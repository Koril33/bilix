# 官网页面维护

官网为 `https://bilix.djhx.site/`，唯一页面源码是 [bilix.html](bilix.html)，部署为 `/var/www/bilix.djhx.site/index.html`。CSS、JavaScript、图标和背景全部内嵌，没有构建步骤、外部字体或框架。本轮维护版本为 1.7.9，实际发布和部署状态见[验收记录](../docs/validation-1.7.9.md)。未公开候选不能提前部署为已发布页面。

下载主入口始终指向 GitHub latest，备用链接使用官网同版本的不可变文件。版本查询失败仍保留发行链接，关闭 JavaScript 后命令/APT 说明仍可读。每次正式发行只在资源齐备后更新备用链接并部署页面。

## 本地预览与核对

在仓库根目录：

```powershell
uv run --locked python -m http.server 8765 --bind 127.0.0.1 --directory site
```

打开 `http://127.0.0.1:8765/bilix.html`；结束预览用 Ctrl+C。修改图标时同步页面和 favicon 的内嵌 SVG，与 [应用图标](../src/djhx_bilix/assets/bilix.svg) 保持一致。

页面变化检查：

- 宽屏与 390/320px：无页面横向溢出，长命令只在代码块内滚动。
- 版本查询成功/失败/超时、关闭 JavaScript、减少动画偏好。
- 全部链接的键盘前后遍历与窄屏代码块滚动。
- GitHub/Gitea/PyPI/文档、备用下载、SHA256/配套源码链接。
- CLI 命令、原生支持范围、更新与 APT 说明符合当前正式发行；待办不写成已有功能。

当前文档从 [docs/README.md](../docs/README.md) 进入，实际范围见对应验收记录，缺陷见 [workflow-issues.md](../docs/workflow-issues.md)。仓库页面提交、发行渠道和线上部署分别记录。

## 浏览器脚本

[validate_site.py](../scripts/validate_site.py) 使用独立 Playwright 环境与已有 Chrome，不将测试依赖加入应用依赖。示例：

```powershell
uv venv build/venv-site-check
uv pip install --python build/venv-site-check/Scripts/python.exe playwright
& build/venv-site-check/Scripts/python.exe scripts/validate_site.py
```

Linux 解释器路径为 `build/venv-site-check/bin/python`。默认使用已安装 Chrome，其他现有 Chrome/Chromium 通过 `--browser-executable <完整路径>` 指定。

脚本启动/关闭临时本地服务器，默认运行八种查询响应 × 三种宽度，再检查减少动画，共 25 个确定性场景。mock 的历史版本号只是测试样本，不是当前发布声明。通过 `--live-api` 额外观察真实 GitHub API；fallback 文案不算在线查询成功。

证据默认位于 `build/validation/site/<本轮标识>/`，包含源码 SHA256、浏览器版本、结果 JSON 和宽窄屏截图；`--output` 选择新的证据目录。记录本轮 Playwright/Python 实际版本，人工核对截图。Markdown 链接检查仅检查本地文件存在，不替代浏览器、远程 URL 和 HTTPS 核验。

历史 1.7.1 的 25 项通过与当时观察到的 v1.7.0 已保留在 [validation-1.7.1.md](../docs/validation-1.7.1.md)，不沿用它证明当前页面通过。

## 部署

先完成本地核对，并确认正式发行全部备用资源已公开。服务器页面、安装包、签名更新和 APT 均使用 **`bilix@djhx.site`** 与已有 **`.ssh/bilix-release-ed25519`**，不使用服务器密码或 sudo。仓库/包上传不会自动部署页面。

```powershell
$sshKey = Join-Path $env:USERPROFILE '.ssh/bilix-release-ed25519'
uv run --locked python scripts/deploy_site.py --check --ssh-key $sshKey
uv run --locked python scripts/deploy_site.py --ssh-key $sshKey
```

`--check` 只读核对身份/目录权限。实际部署验上传哈希、备份旧首页并原子替换；失败 staging 保留供排查。Nginx/TLS/服务与项目权限恢复由管理员处理，常规资源发布仍使用 bilix。

部署后 HTTPS 回读页面 SHA256，与本地一致；再次核对正式版本、下载/源码/校验链接与 APT 说明。SSH 成功不代表公网已更新。完整发布顺序见 [releasing.md](../docs/releasing.md#5-标签镜像与页面)，不要提前将候选写成已发布。

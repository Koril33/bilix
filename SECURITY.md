# 安全政策

安全修复优先面向最新源码与最新发行版本；旧分支不承诺独立维护。当前最新发行版与支持状态以 GitHub Releases 为准。

## 报告漏洞

优先在 [GitHub Security](https://github.com/Koril33/bilix/security) 查看是否开放私密漏洞报告。若尚未开放，先创建仅包含“需要私密沟通安全问题”的普通 Issue，与维护者协调渠道；不要在公开 Issue 中描述可利用细节或粘贴凭据。本项目不承诺固定响应时限。

报告可包含受影响版本、操作系统、最小复现、影响与建议修复。使用虚构凭据与可公开的测试数据；不要使用他人账号验证问题。

## 凭据与数据

扫码凭据保存在用户配置目录的 `token.txt`；不在仓库中维护账号、Cookie 或发布 token。CLI 不打印登录响应和秘密，公开 JSON 不含签名 CDN 地址。用户应保护本地用户目录，并在共享日志时再次脱敏。

以下内容禁止进入提交或发行包：真实 `SESSDATA` / `bili_jct`、账号 token、二维码 key/URL、刷新地址、PyPI/API token、私钥和包含秘密的 `.env`。`.gitignore` 是预防措施，无法清除已提交的历史内容。

测试使用明确标识的虚构凭据；不要为了让扫描通过而屏蔽整个测试目录、提交或文件。扫描使用默认 Gitleaks 规则与本项目的 Bilibili Cookie 规则。

## 本地检查

安装 [Gitleaks](https://github.com/gitleaks/gitleaks)，在项目根目录运行：

```shell
python scripts/check_secrets.py --scope working-tree
python scripts/check_secrets.py --scope history
```

工具只输出规则、路径、行号与提交，不输出秘密值。工作区扫描复制 Git 跟踪文件与未忽略的新文件；不扫描 `.venv`、本地凭据与构建缓存。历史扫描使用 `--all` 覆盖本地可见分支、标签与其他 refs，报告保存在忽略的 `build/security`。

## 发现泄露后

先撤销或轮换相应凭据，再决定是否清理历史。对于 Bilibili 登录 Cookie，请通过账号侧的会话/设备管理使受影响登录失效，再重新扫码；本地 `blx auth logout` 仅删除本地文件，不代表服务器侧会话已撤销。PyPI token 应在 PyPI 账号设置中撤销后重新创建。

历史清理需要协调所有分支、标签、镜像与协作者。重写提交、强制推送及修改远程标签属于单独维护操作；检查工具不会执行这些操作。已存在的 fork、克隆或平台缓存也可能保留旧秘密。参考 [GitHub 清理指南](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。

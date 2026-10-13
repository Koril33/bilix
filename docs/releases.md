# 旧版本迁移

版本变化见 [CHANGELOG](../CHANGELOG.md)，安装与升级见 [gui-updating.md](gui-updating.md)。CLI、GUI 和旧兼容入口共用 `src/djhx_bilix`，不保留第二套业务实现。

| 旧用法或行为 | 当前用法或行为 |
| --- | --- |
| `python main.py`、根目录业务脚本 | `uv run blx` 或 `python -m djhx_bilix` |
| `blx video URL` | 保持兼容，推荐 `blx download URL` |
| `blx user --login` / `blx user` | 保持兼容，推荐 `blx auth login` / `blx auth status` |
| CLI EXE 直接传 URL、`-i`、`-o` | 转入同一 CLI；`-o` 仍为输入文件 |
| 固定默认清晰度 | 默认选择实际可获取的最高流，精确要求加 `--strict` |
| 根目录 `cookie.txt` | 不自动读取，重新扫码 |
| 用户目录旧格式 `token.txt` | 在内存兼容原格式，不自动改写 |
| 旧 CLI EXE 自替换脚本 | 从发行页手动更新；Python 使用原包管理器 |
| 已有同名输出 | 默认跳过且不重新校验，需要重下用 `--overwrite` |

升级和卸载保留用户配置及下载目录。普通下载失败保留 `.bilix-*` 供排查；GUI 会话内暂停续传不读取旧任务残留，跨重启队列/续传尚未实现。

GUI 从 1.6.0 开始，1.7.6 起原生包支持签名更新。1.7.5 及以前先手动安装当前稳定版；CLI、pip/uv 和源码运行按原方式升级。已知 portable 问题与候选修复状态见 [workflow-issues.md](workflow-issues.md)，旧协调器不会因下载新包自动改变。

Windows 新安装器有同渠道降级保护；已公开的 1.6.0 旧安装器没有该逻辑。手动恢复旧安装版可能须先卸载新版，再安装已核对的旧包。APT 显式降级由包管理策略控制。稳定跨版升级使用原始公开旧包；Preview 的独立身份和同版重装不算升级测试。

行为/权限详见 [usage.md](usage.md)、[accounts.md](accounts.md)、[architecture.md](architecture.md)。历史实际结果保留在各版验收记录；当前功能待办见 [backlog.md](backlog.md)，完整索引见 [README.md](README.md)。
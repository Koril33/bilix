# 贡献指南

欢迎报告问题、改进文档或提交代码。提交前请先查看现有问题与 [架构说明](docs/architecture.md)，避免增加第二套业务入口。

## 本地开发

```shell
git clone https://github.com/Koril33/bilix.git
cd bilix
uv sync --locked
uv run blx --help
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
```

Python 3.11–3.14 为支持范围。媒体集成测试需要具备 lavfi、libx264/libx265 与 ffprobe 的完整 FFmpeg；缺少能力时会明确 skip。测试样本使用合成媒体，不提交实际视频或个人登录信息。

## 提交问题与修改

普通问题使用 [GitHub Issues](https://github.com/Koril33/bilix/issues)。描述软件版本、操作系统、复现命令、期望与实际结果，并附脱敏错误信息。不要公开 Cookie、token、二维码、账号标识或签名 CDN 地址；安全问题按 [SECURITY.md](SECURITY.md) 处理。

代码修改保持范围集中，遵循 Ruff 与现有模块分工。为可能破坏数据或凭据安全的修改补充有意义的回归；文档和页面修改检查链接、移动端、键盘访问与命令示例。提交 PR 时说明修改原因与实际执行的检查。

贡献遵循项目的 [GPL-3.0-only](LICENSE)，不增加用途限制。讨论保持尊重，聚焦问题与事实。不要添加 Actions 工作流；本项目的测试、构建与发布在本地执行。

## 发布与页面

贡献者无需发布新版本。维护者遵循 [构建说明](docs/build.md) 与 [发布流程](docs/releasing.md)。静态页面的入口、链接和预览方法见 [site/README.md](site/README.md)。

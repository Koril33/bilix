# 旧版本迁移

1.4.0 起统一使用 `src/djhx_bilix`；1.4.1 修复 Windows 非 UTF-8 终端中文输出。版本变化见 [CHANGELOG](../CHANGELOG.md)。

| 旧用法或行为 | 新版用法或行为 |
| --- | --- |
| `python main.py` | `uv run blx` 或 `python -m djhx_bilix` |
| 根目录业务脚本/第二套实现 | 唯一实现为 `src/djhx_bilix` |
| `blx video URL` | 仍兼容；推荐 `blx download URL` |
| `blx user --login` / `blx user` | 仍兼容；推荐 `blx auth login` / `blx auth status` |
| exe 直接传 URL、`-i`、`-o` | 仍转入相同 CLI |
| 默认尝试固定清晰度 | 默认选择实际可获取的最高流；精确要求加 `--strict` |
| 根目录 cookie.txt | 不再自动读取，请重新扫码 |
| 用户配置目录 token.txt | 自动在内存中兼容旧格式，无需重新登录 |
| 删除/替换自身的 exe 自更新脚本 | 通过发行页更新 exe |
| 旧版同名下载文件 | 默认跳过；需要重新下载时使用 `--overwrite` |

下载文件和用户配置目录不随升级删除。旧版本生成的文件不会在默认跳过时重新验证；发生过下载完整性问题的文件建议显式覆盖重新下载。失败保留 `.bilix-*` 临时材料，目前不实现断点续传。

具体账号流程见 [普通账号与会员权限](accounts.md)，构建和发布方法见 [打包与验证](build.md)，模块职责和事务边界见 [架构说明](architecture.md)。

本次验证的环境、样本和限制见 [验证记录](validation-1.4.0.md)。

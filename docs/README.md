# 文档索引

首次接手从 [handoff.md](handoff.md) 开始。当前命令和流程以下表为准；版本指南描述当版设计，验收记录描述当时实际结果。未实现功能见 [backlog.md](backlog.md)，缺陷、测试与发布流程问题见 [workflow-issues.md](workflow-issues.md)。

## 当前使用与开发

| 任务 | 入口 |
| --- | --- |
| 项目介绍、安装与快速开始 | [项目 README](../README.md) |
| 从零建立环境、判断事实与工作边界 | [开发交接](handoff.md) |
| CLI 参数、配置、输出与退出码 | [usage.md](usage.md) |
| 登录、权限与排错 | [accounts.md](accounts.md) |
| GUI 下载、队列、设置与快捷键 | [gui-usage.md](gui-usage.md) |
| GUI 手动/应用内更新与签名 APT 源 | [gui-updating.md](gui-updating.md) |
| shell 补全与兼容指令 | [completion.md](completion.md) · [迁移说明](releases.md) |
| 模块职责与下载事务 | [architecture.md](architecture.md) |
| 源码运行、Python/Windows CLI 构建 | [build.md](build.md) |
| GUI Windows/Linux 原生构建与许可 | [gui-build-and-release.md](gui-build-and-release.md) |
| 统一离线验证、平台门槛与证据 | [testing.md](testing.md) |
| Linux VM 构建/验收 | [gui-vm-validation.md](gui-vm-validation.md) |
| Windows 原生包/VM 验收 | [gui-win10-validation.md](gui-win10-validation.md) |
| 八项集合、签名、发布与四类服务器部署 | [releasing.md](releasing.md) |
| 更新协议与安装恢复契约 | [application-update-development.md](application-update-development.md) |
| 官网预览、浏览器检查与部署 | [site/README.md](../site/README.md) |
| 贡献、安全、第三方材料 | [CONTRIBUTING](../CONTRIBUTING.md) · [SECURITY](../SECURITY.md) · [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md) |
| 已发布范围与后续工作 | [roadmap.md](roadmap.md) · [backlog.md](backlog.md) |
| 当前缺陷与流程问题 | [workflow-issues.md](workflow-issues.md) |
| portable 更新修复候选与旧版手动迁移 | [portable-update-fix.md](portable-update-fix.md) |

## 版本验收

公开结论必须绑定版本、提交与最终哈希；本地原始日志/截图在忽略目录，clone 不会取得它们。新版本复制 [validation-template.md](validation-template.md)，不修改历史结论来表示新版本通过。

| 版本 | 当版记录 |
| --- | --- |
| 1.7.9 | [validation-1.7.9.md](validation-1.7.9.md) |
| 1.7.8 | [validation-1.7.8.md](validation-1.7.8.md) |
| 1.7.7 | [validation-1.7.7.md](validation-1.7.7.md) |
| 1.7.6 | [validation-1.7.6.md](validation-1.7.6.md) |
| 1.7.5 | [validation-1.7.5.md](validation-1.7.5.md) |
| 1.7.4 | [validation-1.7.4.md](validation-1.7.4.md) |
| 1.7.3 | [validation-1.7.3.md](validation-1.7.3.md) |
| 1.7.2 | [validation-1.7.2.md](validation-1.7.2.md) |
| 1.7.1 | [validation-1.7.1.md](validation-1.7.1.md) |
| 1.7.0 | [validation-1.7.0.md](validation-1.7.0.md) |
| 1.6.0 | [validation-1.6.0.md](validation-1.6.0.md) |
| 1.5.0 / 1.4.0 | [validation-1.5.0.md](validation-1.5.0.md) · [validation-1.4.0.md](validation-1.4.0.md) |

## 历史设计与研究

这些文件保留决策来源、曾发现的问题和版本场景 ID，不能直接作为当前待办或当前发布命令。功能完成状态以源码、当版验收和当前登记表为准。

| 材料 | 范围 |
| --- | --- |
| [cli-gui-ux-review.md](cli-gui-ux-review.md) | 1.6.0 基线上的 1.7.x 任务/UX 设计与验收 ID |
| [validation-1.7-design.md](validation-1.7-design.md) | 隔离原型验证；不证明生产实现 |
| [gui-update-guide-1.7.3.md](gui-update-guide-1.7.3.md) | 当版简洁布局设计 |
| [gui-update-guide-1.7.4.md](gui-update-guide-1.7.4.md) | 当版列表、对话框、托盘方案 |
| [gui-update-guide-1.7.7.md](gui-update-guide-1.7.7.md) | 当版偏好、主题、快捷键与传输反馈 |
| [gui-update-guide-1.7.8.md](gui-update-guide-1.7.8.md) | 当版 F01–F14、队列与会话续传契约 |
| [application-update-plan.md](application-update-plan.md) | 1.7.6 已确认更新方案与初次部署准备 |
| [gui-technology-evaluation.md](gui-technology-evaluation.md) | 首版技术选型调研 |
| [gui-distribution-and-updates.md](gui-distribution-and-updates.md) | 自动更新实现前的发行调研 |
| [gui-usability-review.md](gui-usability-review.md) · [gui-usability-assessment.md](gui-usability-assessment.md) | 1.7.1 界面评审与对应判断 |
| [handoff-1.7.1.md](handoff-1.7.1.md) | 当版收尾交接 |
| [archive/release-1.7.1-materials.md](archive/release-1.7.1-materials.md) | 当版内嵌/外部源码快照差异 |
| [archive/platform-1.6.0.md](archive/platform-1.6.0.md) | 首版 Windows/Linux 原生验收原文 |
| [archive/update-1.7.6.md](archive/update-1.7.6.md) | 首次更新渠道/APT 上线步骤与证据 |
| [archive/version-decisions.md](archive/version-decisions.md) | 版本安排、延期和当时授权范围 |

历史指南保留原路径；通用流程中的旧结果已独立归档。当前候选状态与公开发行状态分别记录。

# 已发布范围与后续安排

这是版本范围索引。当前未实现功能集中在 [backlog.md](backlog.md)，缺陷和流程问题集中在 [workflow-issues.md](workflow-issues.md)；构建/测试/发布从 [README.md](README.md) 进入。历史决策、曾顺延的安排和当时授权范围保留在 [archive/version-decisions.md](archive/version-decisions.md)。

| 版本 | 已发布范围 | 当版证据 |
| --- | --- | --- |
| 1.7.0 | 共享任务/尝试、信息/预览、会话重试、配置来源、安装器保护 | [验收](validation-1.7.0.md) |
| 1.7.1 | 原生桌面/IME/DPI/Wayland、安装故障与性能基线、页面/验证工具收尾 | [验收](validation-1.7.1.md) |
| 1.7.2 | 原创应用图标，GUI/CLI/安装器统一 | [验收](validation-1.7.2.md) |
| 1.7.3 | 紧凑布局、统一列表、按需预览/详情/设置 | [验收](validation-1.7.3.md) |
| 1.7.4 | 列表主窗口、新建下载对话框、主动解析、托盘/通知 | [验收](validation-1.7.4.md) |
| 1.7.5 | 通知/关闭/账号/进度/关于窗口改善 | [验收](validation-1.7.5.md) |
| 1.7.6 | 签名 GUI 更新、GitHub/官网双源、Linux 授权安装、独立签名 APT | [验收](validation-1.7.6.md) |
| 1.7.7 | GUI 偏好、快捷键、三模式主题、共享传输速度/ETA | [验收](validation-1.7.7.md) |
| 1.7.8 | F01–F14、运行中追加、单项取消/会话暂停续传、1–4 项并发、代理/命名模板 | [验收](validation-1.7.8.md) |

“已发布”表示当时完成版本交付；当前已知缺陷、回归和后续修复以问题登记为准。每版测试范围不同，表格不宣称所有平台/权限场景都测过。

后续版本尚未冻结。JSONL/公开错误码、配置编辑、stdin、共用诊断导出、跨重启历史/续传、限速、更新增强和新平台按 backlog 逐项确定前置、契约与验收，不重做已发布的队列、并发和会话内续传。各版设计文档保留原场景 ID，用于理解决策，不作为当前未完成清单。

候选使用 [testing.md](testing.md)、[validation-template.md](validation-template.md) 和 [releasing.md](releasing.md)。升级基线选取本轮实际原始稳定包并记录哈希，长期保留 1.6.0 的真实限制。公开文件/标签保持不可变；产品或发行材料修正用新版本。
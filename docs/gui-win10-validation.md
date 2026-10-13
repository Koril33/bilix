# Windows GUI 原生验收

在明确选定的 Windows 10 x64 专用测试 VM 中验证绿色版和 Inno Setup 安装版。不要重建/删除用户已有 VM 或操作其他测试机。VM 身份、快照、系统 build、Guest Additions、用户与测试路径按本轮环境记录，不能沿用首版机器信息。首版结果已归档至 [archive/platform-1.6.0.md](archive/platform-1.6.0.md)。

## 最小可重复流程

使用不含开发运行时的干净 Windows 用户环境，登录可见桌面。把当轮最终候选与脚本复制到 guest：Windows 三项 GUI 文件、`release-manifest-windows.json`/`SHA256SUMS-windows.txt`，或完整发行的 `release-manifest.json`/`SHA256SUMS.txt`。按 manifest 校验身份/哈希，不从任意旧目录拿 EXE。

在 **guest 的已登录普通用户 PowerShell** 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tests\platform\windows\validate-gui.ps1 `
  -ArtifactDir 'C:\bilix-validation\artifacts' `
  -ResultDir 'C:\bilix-validation\results' -Install -RequireWindows10
```

路径是本轮测试目录示例，先确认文件已复制。实际稳定升级加 `-PriorSetup 'C:\bilix-validation\prior\<旧安装器>'`，旧文件应来自原始公开发行并已核对哈希。Preview 的独立 AppId 和同版重装不能代替稳定旧→新升级。

[validate-gui.ps1](../tests/platform/windows/validate-gui.ps1) 核对 OS build、三项产物大小/SHA256、校验清单，绿色版在中文路径启动两次，安装并检查许可/源码，验证已安装程序、同版重装、卸载与隔离配置/下载内容哈希。自检退出后最多等待 15 秒释放 EXE 文件锁，卸载后再等待清理完成；永久残留会失败。

本轮结果写入 `results/<UTC时间>-<随机数>/result.json` 与安装/自检日志。复制脱敏结果回宿主忽略的 `build/validation/` 或 `dist/gui/validation/`，记录 VM/包/源码身份和实际范围。

## Guest Control 方式

VirtualBox Guest Control 即使指定 `--profile` 也可能未加载用户 HKCU hive，导致 Inno 无法写卸载项。此时用 [run-guest-validation.ps1](../tests/platform/windows/run-guest-validation.ps1)，它以 `LoadUserProfile` 启动同一测试用户，并在启动前删除 guest 临时凭据文件。

参数为 `-ArtifactDir`、`-ResultDir`、`-CredentialFile`、`-UserName`、`-UserDomain`，可加 `-Install -RequireWindows10 -PriorSetup`。认证材料由维护者在忽略的私有临时位置准备，通过 Guest Control 的 `--passwordfile` 使用，不放命令行明文、不回显、不提交。外层复制与执行须用 try/finally 清理宿主与 guest 临时文件；优先使用上面的交互登录方式减少认证传递。

控制 VM 前用 VBoxManage 核对名称、UUID、配置路径与快照。已有运行 VM 不必重启；关闭用正常 ACPI 关机并确认 poweroff，不强制断电。原生桌面检查仍需交互会话，后台自检不代替它。

## 安装与更新事务

| 风险 | 已提交驱动 | 前置条件/边界 |
| --- | --- | --- |
| portable 完整冻结 GUI 交接 | [validate-portable-handoff.ps1](../tests/platform/windows/validate-portable-handoff.ps1) | 非提权交互会话；独立冻结测试入口与合法签名生产候选；真实两 PID/退出句柄/替换/备份/生产启动确认，重跑步骤见[修复说明](portable-update-fix.md#重跑冻结交接) |
| 同渠道升级、降级拒绝、Preview 隔离、写入失败恢复/文件占用 | [validate-installer-transactions.ps1](../tests/platform/windows/validate-installer-transactions.ps1) | FixtureRoot、PriorSetup、ResultDir；加载普通用户 profile；需本轮冻结测试 fixture |
| 更新安装故障 | [validate-update-install-failures.ps1](../tests/platform/windows/validate-update-install-failures.ps1) | CLI 静默事务；脚本固定 1.7.5 基线，先参数化/核对再用于新候选 |
| 用户主动取消 | [validate-user-cancellation.ps1](../tests/platform/windows/validate-user-cancellation.ps1) | 维护者手动点取消，脚本只启动与核对结果；固定 1.7.0 基线/1.7.1 路径，不能照搬到当前版本 |
| 磁盘耗尽 | [validate-disk-exhaustion.ps1](../tests/platform/windows/validate-disk-exhaustion.ps1) | CLI 事务和测试卷操作；固定旧版基线/目录，须先适配当前候选与专用卷 |
| 原生窗口/输入/性能 | [launch-native-desktop.ps1](../tests/platform/windows/launch-native-desktop.ps1) 与 `scripts/native_windows_benchmark.py` | 可见桌面与同环境对比；自动动作不证明真实 IME |

CLI 事务驱动与可见界面操作分开。历史 [validate-updates.ps1](../tests/platform/windows/validate-updates.ps1) 通过 user32 发送按钮/关闭消息，含模拟安装向导操作，保留用于理解旧证据。当前安装向导、更新点击、取消与重启由维护者手动或经授权的界面工具操作，CLI 核对进程/文件/事务结果；AI 不直接继承旧 PowerShell 窗口控制步骤。

驱动已入仓库，但部分签名 fixture 生成步骤仍只存在忽略的 `build/release-1.7.8/`，另有旧版基线硬编码。新 clone 不具备这些输入；先按 [handoff.md](handoff.md#自动化边界) 与 [workflow-issues.md](workflow-issues.md) 补齐/核对公开入口，不能伪称一条命令已覆盖全部事务。

安装器的 `ValidationFailure` 仅用于受控故障 fixture，正式发行不得定义。小 runtime fixture 证明安装脚本行为，不替代最终完整包升级。新安装器有降级保护，原始 1.6.0 旧安装器没有该逻辑。安装失败恢复、安装成功后启动失败、磁盘耗尽、用户取消、断电分别留证。

## 可见桌面与结果

在真实冻结 GUI 中检查中文字形、微软拼音候选与中文提交、原生保存目录导航/回填、二维码、快捷键、缩放和窗口/托盘生命周期。更新检查涵盖中文/空格/改名路径、退出等待、文件占用、系统安装向导与普通用户重启；当前 portable 问题状态见 [workflow-issues.md](workflow-issues.md)。

截图分享前遮盖个人路径、账号、二维码和其他桌面内容。每项记录版本、源码/产物哈希、系统、会话、缩放、时间和结果；Windows 11 未单独验证时不写通过。按 [testing.md](testing.md) 新建当版记录，不继承首版结果。

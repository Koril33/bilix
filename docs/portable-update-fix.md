# Windows 绿色版更新修复与迁移

日期：2026-10-13。修复版本为 **1.7.9**；发行状态和实际验收范围见[本版记录](validation-1.7.9.md)。源码回归及 Windows 10 冻结程序完整交接已通过。用户已选择“修复后续更新＋一次手动迁移”，本次不增加旧版失败更新接管界面。

## 用户迁移

1. 从[官网](https://bilix.djhx.site/)或[GitHub Releases](https://github.com/Koril33/bilix/releases)选择正式发行的 1.7.9 或更新版本，下载 Windows x64 绿色 EXE，并按发行页的 SHA256 校验。
2. 通过“文件 → 退出”退出所有旧 BiliX；仅关窗口可能仍在托盘运行。确认相关程序已经退出。
3. 在原目录把旧 EXE 改名留作备份，再把新版放到原 EXE 的路径。原来改过文件名的，继续使用原文件名。
4. 打开新版，核对“关于 BiliX”的版本及原配置。不要删除配置目录、登录文件或已下载媒体。

1.7.7 等旧版执行更新时，会把**旧程序自身**复制为外部协调器。下载的新包无法修正正在执行的旧逻辑，因此此次迁移需要手动替换；新版之后的自动更新才使用修复后的协调器。不要把缓存中的下载成功视为原 EXE 已更新。

若新版本启动失败，退出新程序后恢复备份。涉及个人路径的事务日志仅用于本地排查；公开反馈先脱敏。

## 已确认的问题

用户报告：1.7.7 绿色版下载完成，点击“更新”后旧程序退出，随后没有替换或重新打开。源码审查和真实 Windows 子进程测试确认了一条可以产生同样现象的缺陷；尚不能据此断言每一次历史失败均由它引起。

原 `process_image()` 用 `QueryFullProcessImageNameW` 推断进程是否存在。进程已退出、但启动器仍保留其句柄时，`OpenProcess` 仍可成功，路径查询却失败；更新器把它当成“无法确认是否退出”。`apply_update()` 已接受交接，此时旧 GUI 可以退出，但旧实现只有成功等待后才显示错误或恢复程序，因此用户只看到退出。

Windows 明确规定进程句柄在关闭前仍有效，即使进程已终止。[Microsoft 进程句柄说明](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)；进程对象可以等待，零超时返回当前信号状态，句柄须具备 `SYNCHRONIZE` 权限。[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)

原 Windows portable 验收脚本直接手写 `request.json`，其中 `processes=[]`，再启动协调器。它验证了替换和重启，却跳过旧 GUI 交接、真实 onefile 父/子进程退出等待。公开客户端回验也只下载和验签。这是本次必须补上的测试缺口。

## 主流方案与本次取舍

| 方案 | 官方行为 | 本项目取舍 |
| --- | --- | --- |
| [Velopack](https://docs.velopack.io/reference/cs/Velopack/UpdateManager) | 下载与应用分开；应用更新并退出，再重新启动。外部 `Update.exe` 承担更新事务。 | 沿用现有外部协调器模型；本次不迁移发行格式或引入新的更新框架。 |
| [WinSparkle](https://github.com/vslavik/winsparkle/blob/master/include/winsparkle.h) | 提供是否可退出与退出请求回调，让应用协调工作结束和关闭，再安装更新。 | 保留“整批任务结束后更新”和 Qt 工作线程结束后退出，补全交接回归。 |
| [VS Code ZIP portable](https://code.visualstudio.com/docs/setup/portable) | Windows ZIP 便携方式不支持自动更新，需要手动迁移到新版并保留数据。 | 用于此次旧版迁移说明；修复后的 BiliX 继续提供自动更新。 |
| [Windows 文件替换](https://learn.microsoft.com/en-us/windows/win32/fileio/moving-and-replacing-files) | 文件占用和共享方式会限制移动/替换；系统提供替换、备份和延迟到重启的机制。 | 等本应用退出后原路径替换、保留备份和启动确认；不把重启系统或强杀其他实例作为正常更新方式。 |

## 实现与验证要求

- [processes.py](../src/djhx_bilix/updater/processes.py)：打开查询及同步句柄，先检查进程信号；路径查询失败时在同一句柄上再次检查退出竞态。只把明确不存在的 PID 当作退出，权限或系统错误仍报错。退出码 259 本身不作为运行状态。
- [apply.py](../src/djhx_bilix/updater/apply.py)：交接已接受后，等待阶段出错也显示原因和事务目录。只有确认旧程序退出后才考虑恢复启动，避免因状态不明再启动第二实例。
- [updates.py](../src/djhx_bilix/gui/updates.py)：交接失败保留错误和“重试更新”入口；重试仍重新校验缓存，不让旧的“就绪”文案覆盖失败。

专项回归覆盖真实 Windows 存活/退出进程、启动器保留句柄、退出码 0/259、查询期间退出、PID 指向另一程序、查询权限错误；同时覆盖 Qt 交接失败反馈、线程结束后退出、等待失败时原 EXE 不变且不重复启动。原有验签、占用、替换失败恢复及启动失败恢复用例继续执行。

冻结验收须经过真实生产 GUI 组件、`handoff()`、复制自身协调器、非空父/子进程记录、真正退出、原路径替换、生产新版启动和 `startup.json/result.json`。测试专用入口只用于冻结验收，不进入发行程序。受控本地签名包的事务测试与公开网络版本发现分开记录，不宣称旧 1.7.7 已被新包自动修复。

## 重跑冻结交接

在具备[Windows 构建环境](gui-build-and-release.md#windows)的 checkout 中，分别生成生产程序和独立测试程序：

```powershell
uv run --locked --extra gui --group build python scripts/build_gui_windows.py --mode onefile
uv run --locked --extra gui --group build python scripts/build_gui_windows.py --test-portable-handoff
$version = uv run --locked python -c "from djhx_bilix import __version__; print(__version__)"
$fixture = "build/portable-handoff-$version-$([guid]::NewGuid().ToString('N'))"
$signingKey = Join-Path $env:USERPROFILE '.bilix-release/keys/update-ed25519.key'
uv run --locked --extra gui python scripts/prepare_portable_handoff.py `
  --package build/gui/windows/onefile/BiliX-GUI.exe --version $version `
  --private-key $signingKey --output $fixture
```

签名只在维护者本机进行，使用与内置信任根匹配的既有密钥；不要生成新根覆盖项目公钥。没有发布密钥的开发人员仍可构建和执行离线回归，签名冻结验收需维护者提供合法测试材料。

向专用 Windows VM 复制测试 EXE、整个 fixture 和[验收脚本](../tests/platform/windows/validate-portable-handoff.ps1)。不用复制私钥。在已登录的普通用户桌面中，以非提权 PowerShell 执行：

```powershell
.\validate-portable-handoff.ps1 -TestExecutable .\handoff-test.exe `
  -Bundle .\fixture -ResultDir .\results
```

测试 EXE 来自 `build/gui/windows-portable-handoff-test/onefile/BiliX-GUI.exe`；fixture 中的生产 EXE 来自第一个构建。脚本保留旧进程句柄，使用独立配置和中文/空格目录，输出一轮唯一 `result.json`，只清理自己启动的测试进程。它自动触发测试程序自身的 Qt 按钮，随后使用未改写的生产协调器和生产新版入口；不操作系统授权窗口。

后续文档入口：[构建](build.md)、[测试](testing.md)、[发布部署](releasing.md)。未完成事项及状态分别维护在[需求登记](backlog.md)和[流程问题登记](workflow-issues.md)。

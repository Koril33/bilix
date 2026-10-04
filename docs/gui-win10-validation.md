# Windows 10 GUI 虚拟机验收

此流程验收 Windows 10 x64 的绿色版和 Inno Setup 安装版。测试 VM 为已有的 `C:\VirtualMachine\Windows10\Windows10.vbox`，VirtualBox 名称 `Windows10`。本轮开始前已建立快照 `bilix-gui-pretest-20261003`（UUID `03ae0f5b-6044-4962-b183-930e3cff6b3e`）。只对这个 VM 做复制、运行、正常关机和启动操作；不要重建或删除 VM，也不要修改其他虚拟机。Windows 11 暂不在本轮范围。

## 准备和执行

在宿主机确认目标和快照，再启动 VM。已有运行中的 VM 不必重启。

```powershell
$vbox = 'C:\Software\VirtualBox\VBoxManage.exe'
& $vbox showvminfo Windows10 --machinereadable
& $vbox snapshot Windows10 list --machinereadable
& $vbox startvm Windows10 --type gui
```

测试使用用户自己保管的 VM 凭据。把它写入被 Git 忽略的临时文件；不要把口令放在命令参数、日志或文档中。下面是完整执行示例，从创建临时文件到复制、验收都由同一个外层 `try/finally` 保护，复制失败也会清理凭据。读取方式不回显输入，也不在文件末尾添加换行。

```powershell
$privateDir = Join-Path (Resolve-Path 'dist/gui').Path 'validation'
New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
$passwordFile = Join-Path $privateDir 'win10-vm-password.txt'
$vm = 'Windows10'
$user = 'koril'
$guest = 'C:\Users\koril\AppData\Local\Temp\bilix-validation'
$guestCredential = "$guest\vm-credential.tmp"
$release = (Resolve-Path 'dist/gui').Path
try {
    $secure = Read-Host 'Windows VM password' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        [IO.File]::WriteAllText($passwordFile,
            [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr),
            [Text.Encoding]::ASCII)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    & $vbox guestcontrol $vm mkdir --parents --username $user --passwordfile $passwordFile `
        "$guest\artifacts" "$guest\results"
    if ($LASTEXITCODE -ne 0) { throw 'Guest directory creation failed' }
    $names = @(
        'BiliX-GUI-Portable-1.6.0-windows-x64.exe',
        'BiliX-GUI-Setup-1.6.0-windows-x64.exe',
        'BiliX-GUI-licenses-and-source-1.6.0-windows-x64.zip',
        'release-manifest-windows.json', 'SHA256SUMS-windows.txt'
    )
    foreach ($name in $names) {
        & $vbox guestcontrol $vm copyto --username $user --passwordfile $passwordFile `
            (Join-Path $release $name) "$guest\artifacts\$name"
        if ($LASTEXITCODE -ne 0) { throw "Copy failed: $name" }
    }
    foreach ($name in @('validate-gui.ps1', 'run-guest-validation.ps1')) {
        & $vbox guestcontrol $vm copyto --username $user --passwordfile $passwordFile `
            (Join-Path 'tests/platform/windows' $name) "$guest\$name"
        if ($LASTEXITCODE -ne 0) { throw "Copy failed: $name" }
    }
    & $vbox guestcontrol $vm copyto --username $user --passwordfile $passwordFile `
        $passwordFile $guestCredential
    if ($LASTEXITCODE -ne 0) { throw 'Credential copy failed' }
    & $vbox guestcontrol $vm run --profile `
        --exe 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
        --username $user --passwordfile $passwordFile `
        --wait-stdout --wait-stderr --timeout 1800000 -- `
        powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File "$guest\run-guest-validation.ps1" `
        -ArtifactDir "$guest\artifacts" -ResultDir "$guest\results" `
        -CredentialFile $guestCredential -UserName $user -UserDomain 'DESKTOP-GP5G2Q3' `
        -Install -RequireWindows10
    if ($LASTEXITCODE -ne 0) { throw 'VM validation failed; inspect result.json and setup.log' }
} finally {
    if (Test-Path -LiteralPath $passwordFile) {
        & $vbox guestcontrol $vm rm --username $user --passwordfile $passwordFile $guestCredential 2>$null
    }
    Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
}
```

`VBoxManage guestcontrol copyto` 在这个 VirtualBox 版本中应指定每个文件的完整目标路径。`validate-gui.ps1` 核对 OS build、三个产物的大小/SHA-256 和 Windows 专用校验和；它把绿色版复制到中文路径，在隔离配置目录中启动两次，静默安装并检查许可/源码，运行已安装程序自检，再卸载并确认用户数据标记保留。可选 `-PriorSetup` 可验收同一安装渠道的旧版本升级，要求旧版号小于目标版本。`1.6.0.dev0` 与 `1.6.0` 的 Inno Setup AppId 不同，不能用二者的连续安装声称完成跨版本升级。

VM 未登录交互桌面时，Guest Control 即使指定 `--profile` 也可能没有加载用户的 `HKEY_USERS\<SID>` hive，无法写入 HKCU 卸载项。[run-guest-validation.ps1](../tests/platform/windows/run-guest-validation.ps1) 使用 `LoadUserProfile` 启动同一用户的子进程，并在启动前删除客体临时凭据文件。示例的用户名、域和客体路径应替换为实际测试 VM 的值；每次运行需重新提供凭据。

验收脚本将每次结果写入 VM `results/<UTC时间>-<随机数>/result.json`。源码 ZIP 检查会拒绝 `.vagrant`、私钥等本地状态路径。出现失败时用 `guestcontrol copyfrom` 将 `result.json` 和安装日志复制回被忽略的 `dist/gui/validation/`，分析后保留证据。正常关机用 `controlvm Windows10 acpipowerbutton`，确认 `VMState="poweroff"`；需要重新打开窗口时再用 `startvm Windows10 --type gui`。不要强制断电。

可见界面必须在 VM 的交互桌面中验收，Guest Control 的后台进程自检不代替这一步。登录桌面后启动绿色版，检查主窗口中文字形，使用中文拼音输入法在文本框内输入并提交中文，打开原生“选择保存目录”对话框，进入测试目录后点选“选择文件夹”，再确认“保存到”字段更新。可用 `VBoxManage controlvm Windows10 screenshotpng <路径>` 留图；分享前裁掉桌面，并遮盖个人目录、账号等信息。此次可复核的裁剪图位于被 Git 忽略的 `dist/gui/validation/win10/`。

## 2026-10-03/04 本轮结果

| 项目 | `1.6.0.dev0` 预览包 | `1.6.0` 正式候选 |
| --- | --- | --- |
| Windows 10 x64 build 19045 与 Guest Additions 7.0.12 | 通过 | 通过 |
| Manifest 中三个产物的大小/SHA-256 | 通过 | 通过 |
| Windows 专用 `SHA256SUMS` 与 manifest 一致 | 旧包按旧格式校验 | 通过 |
| 中文路径绿色版自检两次 | 通过 | 通过 |
| 同渠道旧版升级 | 未验证 | 未验证；没有可用的旧稳定版安装包 |
| 安装、已安装版自检、卸载与用户数据保留 | 预览包直接 Guest Control 安装失败并回滚；未用交互登录重试 | 通过；`candidate-result.json` 记录 14 项检查成功 |
| 真实桌面主窗口及中文标签 | 未验证 | 通过；中文清晰，无方框字形 |
| 拼音输入法候选和中文提交 | 未验证 | 通过 |
| 原生保存目录选择器导航与选择后字段更新 | 未验证 | 通过 |
| 扫码登录、真实下载、Windows 11 | 未验证 | 未验证 |

早期通过 Guest Control 直接运行 Inno Setup 时，安装在创建 HKCU 卸载项时报 `RegCreateKeyEx` 错误 5，并回滚，退出码 4。诊断显示进程用户与 `USERPROFILE` 均为 `koril`，但其 SID hive 未加载；使用 `LoadUserProfile` 后 hive 存在，用户对卸载分支有完整权限，临时注册表项创建和删除成功。正式候选通过该方式完成实际安装、已安装程序自检、卸载和用户数据保留。该问题属于 VM 的 Guest Control 登录方式，不是安装包故障；未更改用户长期注册表 ACL。

正式候选的可见桌面截图是 `main-window.png`、`chinese-ime.png`、`folder-chooser.png` 与 `folder-selected.png`，均位于本地忽略目录 `dist/gui/validation/win10/`。截图遮盖了 VM 用户名或文件选择器的个人位置导航栏。正式候选曾因源码 ZIP 误收本地 `.vagrant` 状态而重包；上述安装与桌面测试使用清理后的包，Manifest 的三项 SHA-256 检查通过。最终发布包若因文档或构建内容变化再打包，须以最终 `release-manifest-windows.json` 复跑脚本；此前候选测试不能直接替代最终哈希验收。

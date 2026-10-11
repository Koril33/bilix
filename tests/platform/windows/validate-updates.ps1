# Real frozen updater transactions; run only in the dedicated Windows 10 VM.
param(
    [Parameter(Mandatory=$true)][string]$FixtureRoot,
    [Parameter(Mandatory=$true)][string]$ResultDir,
    [string]$PriorSetup,
    [switch]$InstallerOnly,
    [switch]$InstallerStartupOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$build=[int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
if ($build -lt 19041 -or $build -ge 22000) {throw 'Dedicated Windows 10 VM required'}
$fixture=[IO.Path]::GetFullPath($FixtureRoot)
$root=Join-Path $ResultDir ('updater-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $root | Out-Null
$env:BILIX_CONFIG_DIR=Join-Path $root 'profile'
$env:BILIX_DOWNLOAD_DIR=Join-Path $root 'downloads'
New-Item -ItemType Directory -Force -Path $env:BILIX_CONFIG_DIR,$env:BILIX_DOWNLOAD_DIR | Out-Null
[IO.File]::WriteAllText((Join-Path $env:BILIX_CONFIG_DIR 'gui.ini'),"[General]`nautomaticUpdates=false`n",(New-Object Text.UTF8Encoding($false)))
[IO.File]::WriteAllText((Join-Path $env:BILIX_CONFIG_DIR 'config.toml'),"quality = '480p'`n",(New-Object Text.UTF8Encoding($false)))
$local=[Environment]::GetFolderPath('LocalApplicationData')
$transactions=Join-Path $local 'djhx-bilix\Cache\updates\transactions'
New-Item -ItemType Directory -Force -Path $transactions | Out-Null
$checks=New-Object 'System.Collections.Generic.List[object]'
$script:seenWindows=New-Object 'System.Collections.Generic.HashSet[string]'
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class BilixUpdateWindows {
 public delegate bool Callback(IntPtr h,IntPtr unused);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Callback cb,IntPtr unused);
 [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent,Callback cb,IntPtr unused);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder b,int count);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h,uint message,IntPtr w,IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder b,int count);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint message,IntPtr w,IntPtr l);
}
'@
function Digest([string]$Path) {(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Tree([int]$ProcessId) {
    $ids=New-Object 'System.Collections.Generic.List[int]';$ids.Add($ProcessId)
    $all=@(Get-CimInstance Win32_Process)
    for ($i=0;$i -lt $ids.Count;$i++) {
        foreach($child in @($all | Where-Object {$_.ParentProcessId -eq $ids[$i]})) {
            if(-not $ids.Contains([int]$child.ProcessId)) {$ids.Add([int]$child.ProcessId)}
        }
    }
    return @($ids.ToArray())
}
function Stop-TestTree([int]$ProcessId) {
    $ids=@(Tree $ProcessId)
    [Array]::Reverse($ids)
    foreach($id in $ids) {Stop-Process -Id $id -ErrorAction SilentlyContinue}
}
function Close-Error([int]$ProcessId) {
    $script:dialogIds=@(Tree $ProcessId)
    $callback=[BilixUpdateWindows+Callback]{param($h,$unused)
        [uint32]$owner=0;[void][BilixUpdateWindows]::GetWindowThreadProcessId($h,[ref]$owner)
        $title=New-Object Text.StringBuilder 256;[void][BilixUpdateWindows]::GetWindowText($h,$title,256)
        if($script:dialogIds -contains [int]$owner -and $title.ToString() -eq 'BiliX 更新') {
            [void][BilixUpdateWindows]::PostMessage($h,0x10,[IntPtr]::Zero,[IntPtr]::Zero)
        }
        return $true
    }
    [void][BilixUpdateWindows]::EnumWindows($callback,[IntPtr]::Zero)
}
function Wait-File([string]$Path,[int]$Seconds=120) {
    $until=[DateTime]::UtcNow.AddSeconds($Seconds)
    while([DateTime]::UtcNow -lt $until) {
        if(Test-Path -LiteralPath $Path) {return}
        Start-Sleep -Milliseconds 200
    }
    throw "Timed out waiting for $Path"
}
function Start-TestApp([string]$Executable) {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$Executable;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
    return [Diagnostics.Process]::Start($start)
}
function Run-Portable([string]$Case,[string]$Bundle,[string]$Expected,[bool]$Occupied=$false,[bool]$OtherCopy=$false) {
    $caseRoot=Join-Path $root $Case
    New-Item -ItemType Directory -Force -Path $caseRoot | Out-Null
    $target=Join-Path $caseRoot '我的 BiliX.exe'
    Copy-Item -LiteralPath (Join-Path $fixture 'prior.exe') -Destination $target
    $old=Digest $target
    $helper=Join-Path $caseRoot 'coordinator.exe'
    Copy-Item -LiteralPath (Join-Path $fixture 'helper.exe') -Destination $helper
    $id=[Guid]::NewGuid().ToString('N');$transaction=Join-Path $transactions $id
    New-Item -ItemType Directory -Force -Path $transaction | Out-Null
    $channel=Get-Content -LiteralPath (Join-Path $Bundle 'stable.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $oldProcess=$null;$lock=$null;$newIds=@()
    if ($OtherCopy) {$oldProcess=Start-TestApp $target;Start-Sleep -Seconds 3}
    if ($Occupied) {$lock=[IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
    $request=@{schema=1;artifact_id='windows-x64-portable';directory=$Bundle;target=$target;old_sha256=$old;version=$channel.version;processes=@()}
    [IO.File]::WriteAllText((Join-Path $transaction 'request.json'),($request|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$helper;$start.Arguments='--apply-update "'+$transaction+'"';$start.UseShellExecute=$false;$start.CreateNoWindow=$true
    $process=[Diagnostics.Process]::Start($start)
    try {
        Wait-File (Join-Path $transaction 'result.json')
        $result=Get-Content -LiteralPath (Join-Path $transaction 'result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if($result.status -cne $Expected) {throw "$Case unexpected result: $($result|ConvertTo-Json -Compress)"}
        if($Expected -eq 'success') {
            $manifest=Get-Content -LiteralPath (Join-Path $Bundle 'update-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            $artifact=@($manifest.artifacts|Where-Object {$_.artifact_id -eq 'windows-x64-portable'})[0]
            if((Digest $target) -cne $artifact.sha256 -or (Digest ($target+'.previous.exe')) -cne $old) {throw 'Replacement/previous EXE differs'}
            $startup=Get-Content -LiteralPath (Join-Path $transaction 'startup.json') -Raw | ConvertFrom-Json
            if($startup.version -cne $channel.version) {throw 'New GUI did not acknowledge startup'}
        } else {
            if((Digest $target) -cne $old) {throw "$Case changed original EXE"}
            Close-Error $process.Id
        }
        if(-not $process.WaitForExit(20000)) {Close-Error $process.Id;if(-not $process.WaitForExit(10000)){throw 'Helper did not exit'}}
        $checks.Add(@{case=$Case;result=$result;transaction=$transaction;old_sha256=$old;target_sha256=(Digest $target)})|Out-Null
    } finally {
        if($lock){$lock.Dispose()}
        if($oldProcess){Stop-TestTree $oldProcess.Id;$oldProcess.Dispose()}
        if(-not $process.HasExited){Close-Error $process.Id;Stop-TestTree $process.Id}
        $process.Dispose()
        # Only programs launched from this unique test path are stopped.
        foreach($app in @(Get-CimInstance Win32_Process|Where-Object {$_.ExecutablePath -eq $target})) {Stop-TestTree ([int]$app.ProcessId)}
    }
}
function Click-Installer([int]$ProcessId,[bool]$Cancel) {
    $script:wizardIds=@(Tree $ProcessId);$script:cancelWizard=$Cancel
    $callback=[BilixUpdateWindows+Callback]{param($h,$unused)
        [uint32]$owner=0;[void][BilixUpdateWindows]::GetWindowThreadProcessId($h,[ref]$owner)
        $class=New-Object Text.StringBuilder 128;[void][BilixUpdateWindows]::GetClassName($h,$class,128)
        if($script:wizardIds -contains [int]$owner) {
            $title=New-Object Text.StringBuilder 256;[void][BilixUpdateWindows]::GetWindowText($h,$title,256)
            $description=$class.ToString()+' '+$title.ToString()
            if($script:seenWindows.Add($description)) {
                [IO.File]::AppendAllText((Join-Path $root 'wizard-windows.txt'),$description+"`n")
            }
        }
        if($script:wizardIds -contains [int]$owner -and $class.ToString() -eq 'TSelectLanguageForm') {
            $language=[BilixUpdateWindows+Callback]{param($control,$unusedChild)
                $type=New-Object Text.StringBuilder 128;[void][BilixUpdateWindows]::GetClassName($control,$type,128)
                $text=New-Object Text.StringBuilder 128;[void][BilixUpdateWindows]::GetWindowText($control,$text,128)
                if($type.ToString() -match 'Button$' -and $text.ToString() -match '确定|OK') {
                    [void][BilixUpdateWindows]::PostMessage($control,0xF5,[IntPtr]::Zero,[IntPtr]::Zero)
                }
                return $true
            }
            [void][BilixUpdateWindows]::EnumChildWindows($h,$language,[IntPtr]::Zero)
        } elseif($script:wizardIds -contains [int]$owner -and $class.ToString() -eq 'TWizardForm') {
            if($script:cancelWizard) {
                [void][BilixUpdateWindows]::PostMessage($h,0x10,[IntPtr]::Zero,[IntPtr]::Zero)
            } else {
                $children=[BilixUpdateWindows+Callback]{param($control,$unusedChild)
                    $text=New-Object Text.StringBuilder 512;[void][BilixUpdateWindows]::GetWindowText($control,$text,512)
                    $type=New-Object Text.StringBuilder 128;[void][BilixUpdateWindows]::GetClassName($control,$type,128)
                    if([BilixUpdateWindows]::IsWindowVisible($control) -and [BilixUpdateWindows]::IsWindowEnabled($control)) {
                        if(($type.ToString() -eq 'TNewRadioButton' -and $text.ToString() -match '接受|同意|accept' -and $text.ToString() -notmatch '不|not') -or ($type.ToString() -eq 'TNewButton' -and $text.ToString() -match '下一步|安装|完成|Next|Install|Finish')) {
                            [void][BilixUpdateWindows]::PostMessage($control,0xF5,[IntPtr]::Zero,[IntPtr]::Zero)
                        }
                    }
                    return $true
                }
                [void][BilixUpdateWindows]::EnumChildWindows($h,$children,[IntPtr]::Zero)
            }
        } elseif($script:cancelWizard -and $script:wizardIds -contains [int]$owner -and $class.ToString() -eq '#32770') {
            [void][BilixUpdateWindows]::PostMessage($h,0x111,[IntPtr]6,[IntPtr]::Zero)
        }
        return $true
    }
    [void][BilixUpdateWindows]::EnumWindows($callback,[IntPtr]::Zero)
}
function Run-Inno([string]$Case,[bool]$Cancel,[bool]$StartupFailure=$false) {
    if(-not $PriorSetup) {return}
    $caseRoot=Join-Path $root $Case;New-Item -ItemType Directory -Force -Path $caseRoot|Out-Null
    $installation=Join-Path $caseRoot 'installation'
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$PriorSetup;$start.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="'+$installation+'"';$start.UseShellExecute=$false
    $oldSetup=[Diagnostics.Process]::Start($start)
    if(-not $oldSetup.WaitForExit(180000) -or $oldSetup.ExitCode -ne 0) {throw 'Could not install the real prior version'}
    $oldSetup.Dispose()
    $target=Join-Path $installation 'runtime\BiliX-GUI.exe';$old=Digest $target
    $transaction=Join-Path $transactions ([Guid]::NewGuid().ToString('N'));New-Item -ItemType Directory -Path $transaction|Out-Null
    $bundle=Join-Path $fixture $(if($StartupFailure){'installer-bad-startup'}else{'installer-valid'})
    $channel=Get-Content -LiteralPath (Join-Path $bundle 'stable.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $request=@{schema=1;artifact_id='windows-x64-installer';directory=$bundle;target=$target;old_sha256=$old;version=$channel.version;processes=@()}
    [IO.File]::WriteAllText((Join-Path $transaction 'request.json'),($request|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)))
    $helper=Join-Path $caseRoot 'coordinator.exe';Copy-Item -LiteralPath (Join-Path $fixture 'helper.exe') -Destination $helper
    $start.FileName=$helper;$start.Arguments='--apply-update "'+$transaction+'"'
    $process=[Diagnostics.Process]::Start($start)
    try {
        $until=[DateTime]::UtcNow.AddSeconds(180)
        while(-not (Test-Path -LiteralPath (Join-Path $transaction 'result.json')) -and [DateTime]::UtcNow -lt $until) {
            Click-Installer $process.Id $Cancel;Start-Sleep -Milliseconds 300
        }
        Wait-File (Join-Path $transaction 'result.json') 1
        $result=Get-Content -LiteralPath (Join-Path $transaction 'result.json') -Raw -Encoding UTF8|ConvertFrom-Json
        if($Cancel) {
            if($result.status -ne 'failed' -or $result.installed -or (Digest $target) -ne $old) {throw 'Cancelled installer changed prior runtime'}
            Close-Error $process.Id
        } else {
            if($StartupFailure) {
                if($result.status -ne 'failed' -or -not $result.installed -or (Digest $target) -eq $old) {throw 'Installed startup failure was incorrectly classified'}
                Close-Error $process.Id
            } elseif($result.status -ne 'success') {throw 'Installer updater did not acknowledge restart'}
            $version=(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1').DisplayVersion
            if($version -ne $channel.version) {throw 'Installation record does not match update'}
            if(-not $StartupFailure) {
                $startup=Get-Content -LiteralPath (Join-Path $transaction 'startup.json') -Raw|ConvertFrom-Json
                if($startup.version -ne $channel.version) {throw 'Installed GUI did not acknowledge startup'}
            }
        }
        if(-not $process.WaitForExit(20000)) {throw 'Installer coordinator did not exit'}
        $checks.Add(@{case=$Case;result=$result;transaction=$transaction;target_sha256=(Digest $target)})|Out-Null
    } finally {
        if(-not $process.HasExited){Close-Error $process.Id;Stop-TestTree $process.Id}
        $ownedLock=Join-Path $transactions 'windows-x64-installer.lock'
        if((Test-Path -LiteralPath $ownedLock) -and [IO.File]::ReadAllText($ownedLock) -eq [string]$process.Id) {
            Remove-Item -LiteralPath $ownedLock
        }
        $process.Dispose()
        foreach($app in @(Get-CimInstance Win32_Process|Where-Object {$_.ExecutablePath -eq $target})) {Stop-TestTree ([int]$app.ProcessId)}
        Start-Sleep -Seconds 1
        $uninstall=@(Get-ChildItem -LiteralPath $installation -Filter 'unins*.exe')[0]
        $start.FileName=$uninstall.FullName;$start.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
        $cleanup=[Diagnostics.Process]::Start($start);[void]$cleanup.WaitForExit(120000);$cleanup.Dispose()
    }
}
$failure=$null
try {
    if(-not $InstallerOnly -and -not $InstallerStartupOnly) {
    Run-Portable 'portable-success' (Join-Path $fixture 'valid') 'success'
    Run-Portable 'occupied-file' (Join-Path $fixture 'valid') 'failed' $true
    Run-Portable 'other-instance' (Join-Path $fixture 'valid') 'failed' $false $true
    Run-Portable 'invalid-signature' (Join-Path $fixture 'bad-signature') 'failed'
    Run-Portable 'tampered-package' (Join-Path $fixture 'tampered') 'failed'
    Run-Portable 'startup-failure-restored' (Join-Path $fixture 'bad-executable') 'failed'
    }
    if($InstallerStartupOnly) {
        Run-Inno 'installer-startup-failure-manual-recovery' $false $true
    } else {
        Run-Inno 'installer-success' $false
        Run-Inno 'installer-cancel' $true
    }
} catch {$failure=$_.Exception.Message}
@{status=$(if($failure){'failed'}else{'passed'});checks=@($checks.ToArray());error=$failure;os_build=$build} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $root 'result.json') -Encoding UTF8
if($failure){throw $failure}
Write-Output "PASS frozen updater transactions: $root"

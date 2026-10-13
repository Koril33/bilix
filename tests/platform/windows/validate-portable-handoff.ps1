# Run from an ordinary user's interactive desktop. No UI automation is used.
# This is an offline signed transaction test, not public-network version discovery.
param(
    [Parameter(Mandatory=$true)][string]$TestExecutable,
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$ResultDir,
    [int]$TimeoutSeconds=240
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Assert-True([bool]$Condition,[string]$Message) {
    if(-not $Condition) {throw $Message}
}
function Digest([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Read-Json([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}
function Below-Directory([string]$Path,[string]$Directory) {
    $resolved=[IO.Path]::GetFullPath($Path)
    $prefix=[IO.Path]::GetFullPath($Directory).TrimEnd('\')+'\'
    return $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)
}
function Wait-Json([string]$Path,[DateTime]$Deadline) {
    while([DateTime]::UtcNow -lt $Deadline) {
        if(Test-Path -LiteralPath $Path -PathType Leaf) {return Read-Json $Path}
        Start-Sleep -Milliseconds 200
    }
    throw "Timed out waiting for $Path"
}
function Own-Processes {
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and (
            (Below-Directory $_.ExecutablePath $script:runRoot) -or
            ($script:helperRoot -and (Below-Directory $_.ExecutablePath $script:helperRoot))
        )
    })
}
function Stop-OwnProcesses {
    # Both roots are unique to this test. The helper root is accepted only after
    # its request.json has been tied to the executable in the unique run root.
    $owned=@(Own-Processes)
    $ids=@($owned | ForEach-Object {[int]$_.ProcessId})
    $ordered=@($owned | Sort-Object @{Expression={
        if($ids -contains [int]$_.ParentProcessId) {0} else {1}
    }})
    foreach($processItem in $ordered) {
        Stop-Process -Id ([int]$processItem.ProcessId) -ErrorAction SilentlyContinue
    }
}

$script:runRoot=Join-Path ([IO.Path]::GetFullPath($ResultDir)) (
    'portable-handoff-'+[Guid]::NewGuid().ToString('N')
)
$script:helperRoot=$null
New-Item -ItemType Directory -Path $script:runRoot | Out-Null
$checks=New-Object 'System.Collections.Generic.List[string]'
$record=[ordered]@{
    schema=1
    scope='offline-signed-portable-transaction'
    public_network_discovery=$false
    started_utc=[DateTime]::UtcNow.ToString('o')
    run_root=$script:runRoot
}
$oldProcess=$null
$failure=$null
$savedEnvironment=@{}
$environmentNames=@(
    'BILIX_CONFIG_DIR','BILIX_DOWNLOAD_DIR','BILIX_HANDOFF_FIXTURE','BILIX_HANDOFF_REPORT',
    'BILIX_FFMPEG','BILIX_PROXY','PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH',
    'QT_QPA_PLATFORM_PLUGIN_PATH','QT_QPA_PLATFORM','NUITKA_ONEFILE_PARENT',
    'NUITKA_ONEFILE_DIRECTORY','NUITKA_ONEFILE_START','NUITKA_ONEFILE_TIME_US',
    'NUITKA_ONEFILE_RANDOM','NUITKA_ORIGINAL_ARGV0','PATH'
)
try {
    Assert-True ($env:OS -eq 'Windows_NT') 'Windows is required'
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=New-Object Security.Principal.WindowsPrincipal($identity)
    Assert-True (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) 'Run with an ordinary user token, not an elevated administrator token'
    $session=[Diagnostics.Process]::GetCurrentProcess().SessionId
    Assert-True ($session -gt 0 -and [Environment]::UserInteractive) (
        'Run with the logged-in user interactive token, not Session 0 or a service token'
    )
    $record['session_id']=$session
    $record['ordinary_user']=$true
    $checks.Add('ordinary-interactive-user') | Out-Null

    $source=(Resolve-Path -LiteralPath $TestExecutable).Path
    $fixture=(Resolve-Path -LiteralPath $Bundle).Path
    $manifest=Read-Json (Join-Path $fixture 'update-manifest.json')
    $channel=Read-Json (Join-Path $fixture 'stable.json')
    $artifacts=@($manifest.artifacts | Where-Object {$_.artifact_id -eq 'windows-x64-portable'})
    Assert-True ($artifacts.Count -eq 1) 'Expected exactly one portable fixture artifact'
    $artifact=$artifacts[0]
    $package=Join-Path $fixture $artifact.filename
    Assert-True ((Digest $package) -ceq $artifact.sha256) 'Fixture package hash differs'
    Assert-True ($channel.version -ceq $manifest.version) 'Fixture versions differ'
    $record['version']=$channel.version
    $record['package_sha256']=Digest $package

    # Construct Unicode names without relying on PowerShell 5.1's source encoding.
    $unicode=([string][char]0x66F4)+([string][char]0x65B0)
    $applicationRoot=Join-Path $script:runRoot ($unicode+' space directory')
    $profile=Join-Path $script:runRoot 'isolated-profile'
    $downloads=Join-Path $script:runRoot 'downloads'
    New-Item -ItemType Directory -Path $applicationRoot,$profile,$downloads | Out-Null
    $target=Join-Path $applicationRoot ($unicode+' BiliX Renamed.exe')
    Copy-Item -LiteralPath $source -Destination $target
    $oldHash=Digest $target
    Assert-True ($oldHash -cne $artifact.sha256) (
        'Test entry and production payload must be different binaries'
    )
    $record['target']=$target
    $record['old_sha256']=$oldHash

    $sentinel=[Guid]::NewGuid().ToString('N')
    $utf8=New-Object Text.UTF8Encoding($false)
    $config=Join-Path $profile 'config.toml'
    $preferences=Join-Path $profile 'gui.ini'
    $downloadSentinel=Join-Path $downloads 'keep-after-update.txt'
    $profileSentinel=Join-Path $profile 'keep-after-update.txt'
    [IO.File]::WriteAllText($config,
        'download_dir = "'+$downloads.Replace('\','/')+'"'+[Environment]::NewLine,$utf8)
    [IO.File]::WriteAllText($preferences,
        "[v1]`nautomaticUpdates=false`nminimizeToTray=false`nhandoffSentinel=$sentinel`n",$utf8)
    [IO.File]::WriteAllText($downloadSentinel,$sentinel,$utf8)
    [IO.File]::WriteAllText($profileSentinel,$sentinel,$utf8)
    $configHash=Digest $config
    $sentinelHash=Digest $downloadSentinel
    $harnessPath=Join-Path $script:runRoot 'handoff-harness.json'

    foreach($name in $environmentNames) {
        $savedEnvironment[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
        [Environment]::SetEnvironmentVariable($name,$null,'Process')
    }
    $env:BILIX_CONFIG_DIR=$profile
    $env:BILIX_DOWNLOAD_DIR=$downloads
    $env:BILIX_HANDOFF_FIXTURE=$fixture
    $env:BILIX_HANDOFF_REPORT=$harnessPath
    $env:PATH=(Join-Path $env:SystemRoot 'System32')+';'+$env:SystemRoot+';'+(
        Join-Path $env:SystemRoot 'System32\Wbem'
    )+';'+(Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0')

    $oldProcess=Start-Process -FilePath $target -WorkingDirectory $applicationRoot `
        -WindowStyle Hidden -PassThru
    # Keep this Process object and its native handle alive through replacement.
    # It deliberately reproduces the old updater's terminated-process query failure.
    $heldProcessHandle=$oldProcess.Handle
    Assert-True ($heldProcessHandle -ne [IntPtr]::Zero) 'Could not retain the old process handle'
    $record['old_bootstrap_pid']=$oldProcess.Id
    $record['retained_old_process_handle']=$true
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $harness=$null
    while([DateTime]::UtcNow -lt $deadline) {
        if(Test-Path -LiteralPath $harnessPath) {
            $harness=Read-Json $harnessPath
            if($harness.stage -eq 'failed') {throw "GUI handoff failed: $($harness.error)"}
            if($harness.stage -eq 'accepted') {break}
        }
        Start-Sleep -Milliseconds 200
    }
    Assert-True ($null -ne $harness -and $harness.stage -eq 'accepted') (
        'The real GUI did not complete its update-button handoff'
    )
    Assert-True ($harness.executable -eq $target -and $harness.window_visible) (
        'The test did not run the renamed executable with its main window shown'
    )
    Assert-True ($harness.qt_platform -ceq 'windows') 'The GUI did not use native Windows Qt'
    Assert-True ($harness.parent_pid -eq $oldProcess.Id) 'The old onefile bootstrap was not recorded'
    $transaction=[IO.Path]::GetFullPath([string]$harness.transaction)
    $transactions=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) (
        'djhx-bilix\Cache\updates\transactions'
    )
    Assert-True ((Split-Path -Parent $transaction) -eq $transactions) 'Unexpected transaction root'
    Assert-True ((Split-Path -Leaf $transaction) -cmatch '^[a-f0-9]{32}$') 'Unexpected transaction ID'
    $request=Read-Json (Join-Path $transaction 'request.json')
    Assert-True ($request.target -eq $target -and $request.old_sha256 -ceq $oldHash) (
        'The production handoff request targets a different executable'
    )
    $script:helperRoot=Join-Path $transaction 'helper'
    Assert-True ((Digest (Join-Path $script:helperRoot 'BiliX-Update.exe')) -ceq $oldHash) (
        'Handoff did not copy its own executable as the independent helper'
    )
    $record['transaction']=$transaction
    $oldIds=@($request.processes | ForEach-Object {[int]$_.pid})
    Assert-True ($oldIds.Count -eq 2 -and $oldIds -contains $oldProcess.Id -and
        $oldIds -contains [int]$harness.pid) 'Request must contain the real bootstrap and GUI child'
    foreach($processItem in $request.processes) {
        Assert-True ($processItem.image -eq $target) 'Request contains a different executable image'
    }
    Assert-True (Test-Path -LiteralPath (Join-Path $transaction 'accepted.json')) (
        'Independent helper did not acknowledge readiness'
    )
    $checks.Add('real-gui-click-and-self-copy-handoff') | Out-Null
    Assert-True ($oldProcess.WaitForExit(30000)) 'Old onefile bootstrap did not exit'
    Assert-True ($oldProcess.ExitCode -eq 0) 'Old GUI did not exit successfully'
    $checks.Add('old-bootstrap-exited-with-retained-handle') | Out-Null

    $result=Wait-Json (Join-Path $transaction 'result.json') $deadline
    if($result.status -ne 'success') {throw "Update transaction failed: $($result.message)"}
    Assert-True ($result.version -ceq $channel.version) 'Transaction result has the wrong version'
    Assert-True ((Digest $target) -ceq $artifact.sha256) 'Production payload did not replace the target'
    Assert-True ((Digest ($target+'.previous.exe')) -ceq $oldHash) 'Previous EXE was not preserved'
    $checks.Add('replacement-and-previous-executable-hashes') | Out-Null

    $startup=Read-Json (Join-Path $transaction 'startup.json')
    Assert-True ($startup.version -ceq $channel.version) 'New production GUI did not acknowledge version'
    Assert-True (-not ($oldIds -contains [int]$startup.pid)) 'Startup acknowledgement came from an old PID'
    $updated=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $target})
    $gui=@($updated | Where-Object {$_.ProcessId -eq [int]$startup.pid})
    Assert-True ($updated.Count -eq 2 -and $gui.Count -eq 1) (
        'Expected one updated onefile instance: one bootstrap and one GUI child'
    )
    $bootstrap=@($updated | Where-Object {$_.ProcessId -eq $gui[0].ParentProcessId})
    Assert-True ($bootstrap.Count -eq 1) 'Updated GUI does not belong to its onefile bootstrap'
    foreach($processItem in $updated) {
        Assert-True ($processItem.SessionId -eq $session) 'Updated process left the interactive session'
        $owner=Invoke-CimMethod -InputObject $processItem -MethodName GetOwnerSid
        Assert-True ($owner.ReturnValue -eq 0 -and $owner.Sid -eq $identity.User.Value) (
            'Updated process is not running as the original ordinary user'
        )
    }
    # startup.json is written by the unmodified production GUI after its main
    # window is shown and its event loop has processed the startup callback.
    $record['startup']=$startup
    $record['updated_gui_pid']=[int]$startup.pid
    $record['updated_bootstrap_pid']=[int]$bootstrap[0].ProcessId
    $record['main_window_event_loop_acknowledged']=$true
    $checks.Add('single-production-gui-startup-in-original-user-session') | Out-Null

    Assert-True ((Digest $config) -ceq $configHash) 'Update changed config.toml'
    Assert-True ((Digest (Join-Path $transaction 'config-backup\config.toml')) -ceq $configHash) (
        'Preferences backup does not contain the original config.toml'
    )
    foreach($ini in @($preferences,(Join-Path $transaction 'config-backup\gui.ini'))) {
        Assert-True ((Get-Content -LiteralPath $ini -Raw -Encoding UTF8) -match (
            '(?m)^handoffSentinel='+[regex]::Escape($sentinel)+'\r?$'
        )) 'Update or backup lost the GUI preference sentinel'
    }
    Assert-True ((Digest $downloadSentinel) -ceq $sentinelHash -and
        (Digest $profileSentinel) -ceq $sentinelHash) 'Update changed user-data sentinels'
    Assert-True ((Digest $package) -ceq $artifact.sha256) 'Test changed the source fixture package'
    $checks.Add('configuration-preferences-and-downloads-preserved') | Out-Null
} catch {
    $failure=$_.Exception.Message
} finally {
    try {Stop-OwnProcesses} catch {
        if($failure) {$failure+='; cleanup: '+$_.Exception.Message}
        else {$failure='cleanup: '+$_.Exception.Message}
    }
    if($oldProcess) {$oldProcess.Dispose()}
    foreach($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name,$savedEnvironment[$name],'Process')
    }
    $record['status']=$(if($failure){'failed'}else{'passed'})
    $record['error']=$failure
    $record['checks']=@($checks.ToArray())
    $record['finished_utc']=[DateTime]::UtcNow.ToString('o')
    $resultPath=Join-Path $script:runRoot 'result.json'
    $record | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Output "Validation report: $resultPath"
}
if($failure) {throw $failure}
Write-Output 'PASS offline frozen portable GUI handoff, replacement and production restart'

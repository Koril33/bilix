# Use the already unlocked dedicated VM desktop; no password is stored in a task.
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Probe = '',
    [ValidateRange(30,1800)][int]$Seconds = 600
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$expected = [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'AppData\Local\Temp\bilix-171-validation'))
$rootPath = [IO.Path]::GetFullPath($Root)
$outputPath = [IO.Path]::GetFullPath($Output)
$exePath = [IO.Path]::GetFullPath($Executable)
if ($rootPath -cne $expected -or -not $outputPath.StartsWith($rootPath+'\',[StringComparison]::OrdinalIgnoreCase) -or -not $exePath.StartsWith($rootPath+'\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Only the dedicated 1.7.1 validation directory is allowed'
}
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw 'Executable missing' }
if ($Probe) {
    $probePath=[IO.Path]::GetFullPath($Probe)
    if (-not $probePath.StartsWith($rootPath+'\',[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $probePath -PathType Leaf)) {throw 'Probe must exist inside the validation root'}
}
$osBuild = [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
if ($osBuild -lt 19041 -or $osBuild -ge 22000) { throw 'Dedicated Windows 10 test VM required' }
$name = 'BilixValidationDesktop171-'+[Guid]::NewGuid().ToString('N')
$specFile = Join-Path $rootPath ($name+'.json')
$arguments = @()
if ($Probe) { $arguments = @('-u',$Probe,'--output',$outputPath,'--seconds',[string]$Seconds) }
$spec = @{exe=$exePath;arguments=$arguments;output=$outputPath;task=$name;seconds=$Seconds}
$spec | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $specFile -Encoding UTF8
$runner = Join-Path $rootPath ($name+'.ps1')
$body = @(
    'param([string]$SpecFile)',
    '$ErrorActionPreference="Stop"',
    'Start-Transcript -Path ($SpecFile+".log") -Force | Out-Null',
    '$spec=Get-Content -Raw -LiteralPath $SpecFile | ConvertFrom-Json',
    '$env:BILIX_CONFIG_DIR=Join-Path $spec.output "profile"',
    '$env:BILIX_DOWNLOAD_DIR=Join-Path $spec.output "downloads"',
    'Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue',
    '$session=[Diagnostics.Process]::GetCurrentProcess().SessionId',
    '$launch=[ordered]@{started_utc=[DateTime]::UtcNow.ToString("o");session_id=$session;task=$spec.task;memory_samples=@();status="running"}',
    '$arguments=(@($spec.arguments)|ForEach-Object {"`""+$_+"`""}) -join " "',
    '$start=New-Object Diagnostics.ProcessStartInfo',
    '$start.FileName=$spec.exe;$start.Arguments=$arguments;$start.UseShellExecute=$false;$start.CreateNoWindow=$true',
    '$clock=[Diagnostics.Stopwatch]::StartNew()',
    '$launch["launch_monotonic_seconds"]=[Diagnostics.Stopwatch]::GetTimestamp()/[Diagnostics.Stopwatch]::Frequency',
    '$process=[Diagnostics.Process]::Start($start)',
    '$launch["pid"]=$process.Id',
    '$report=Join-Path (Split-Path -Parent $spec.output) ((Split-Path -Leaf $spec.output)+"-process.json")',
    '$sample=New-Object "System.Collections.Generic.List[object]"',
    'try {',
    '  while (-not $process.HasExited -and $clock.Elapsed.TotalSeconds -lt ($spec.seconds+60)) {',
    '    $process.Refresh()',
    '    $sample.Add(@{ms=$clock.ElapsedMilliseconds;working_bytes=$process.WorkingSet64;private_bytes=$process.PrivateMemorySize64;handle=$process.MainWindowHandle.ToInt64()})',
    '    if (-not $launch.Contains("window_observed_ms") -and $process.MainWindowHandle -ne [IntPtr]::Zero) { $launch.window_observed_ms=$clock.ElapsedMilliseconds }',
    '    Start-Sleep -Milliseconds 200',
    '  }',
    '  if (-not $process.HasExited) { $launch.status="timeout";$process.Kill();$process.WaitForExit() } else { $launch.exit=$process.ExitCode;$launch.status="finished" }',
    '} finally {',
    '  $launch.memory_samples=@($sample.ToArray())',
    '  $launch | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8',
    '  $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$scheduler.GetFolder("\").DeleteTask($spec.task,0)',
    '  $process.Dispose()',
    '  Stop-Transcript | Out-Null',
    '}'
)
$body | Set-Content -LiteralPath $runner -Encoding UTF8
$scheduler=New-Object -ComObject Schedule.Service
$scheduler.Connect()
$task=$scheduler.NewTask(0)
$task.RegistrationInfo.Description='Temporary BiliX 1.7.1 native desktop validation, interactive token only'
$task.Principal.LogonType=3
$task.Principal.RunLevel=0
# Give the runner time to write evidence and remove its own task after the probe.
$task.Settings.ExecutionTimeLimit='PT'+[string]($Seconds+120)+'S'
$task.Settings.DisallowStartIfOnBatteries=$false
$task.Settings.StopIfGoingOnBatteries=$false
$task.Settings.Hidden=$true
$action=$task.Actions.Create(0)
$action.Path=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action.Arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$runner+'" -SpecFile "'+$specFile+'"'
$folder=$scheduler.GetFolder('\')
# TASK_LOGON_INTERACTIVE_TOKEN: existing signed-in user, no credentials persisted.
$registered=$folder.RegisterTaskDefinition($name,$task,6,$null,$null,3,$null)
$registered.Run($null) | Out-Null
Write-Output ('Native desktop task started: '+$name)

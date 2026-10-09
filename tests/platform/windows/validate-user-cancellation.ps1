# Real interactive cancellation; the caller presses the visible Cancel button.
param([string]$Root,[string]$Setup,[string]$PriorSetup,[string]$Output,[ValidateRange(60,1800)][int]$CancellationWaitSeconds=900)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$expected=[IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'AppData\Local\Temp\bilix-171-validation'))
if ([IO.Path]::GetFullPath($Root) -cne $expected) {throw 'Unexpected test root'}
foreach ($path in @($Setup,$PriorSetup,$Output)) {
    if (-not [IO.Path]::GetFullPath($path).StartsWith($expected+'\',[StringComparison]::OrdinalIgnoreCase)) {throw 'Path outside dedicated test root'}
}
if (Test-Path -LiteralPath $Output) {throw 'Evidence directory already exists'}
New-Item -ItemType Directory -Path $Output | Out-Null
$install=Join-Path $Output 'stable'
$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1'
$nativeKey='HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1'
$hadKey=Test-Path $key
$backup=Join-Path $Output 'original-uninstall.reg'
if ($hadKey) {& reg.exe export $nativeKey $backup /y | Out-Null; if ($LASTEXITCODE -ne 0) {throw 'Registry backup failed'}}
$profile=Join-Path $Output 'profile'
New-Item -ItemType Directory -Path $profile | Out-Null
$data=Join-Path $profile 'settings.json'
Set-Content -LiteralPath $data -Value '{"output_dir":"user retained directory"}' -Encoding ASCII
$beforeData=(Get-FileHash -LiteralPath $data).Hash
function Digest {return ((Get-ChildItem -LiteralPath (Join-Path $install 'runtime') -Recurse -File | Sort-Object FullName | ForEach-Object { $_.FullName.Substring($install.Length)+' '+(Get-FileHash -LiteralPath $_.FullName).Hash }) -join "`n")}
function Start-Installer([string]$Exe,[string]$Name,[bool]$Silent) {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$Exe
    $start.Arguments='/NORESTART /SP- /DIR="'+$install+'" /LOG="'+(Join-Path $Output ($Name+'.log'))+'"'
    if ($Silent) {$start.Arguments+=' /VERYSILENT /SUPPRESSMSGBOXES'}
    $start.UseShellExecute=$false
    return [Diagnostics.Process]::Start($start)
}
$record=[ordered]@{status='running';checks=@();interactive=$true;setup_sha256=(Get-FileHash -LiteralPath $Setup).Hash;prior_setup_sha256=(Get-FileHash -LiteralPath $PriorSetup).Hash;cancellation_wait_seconds=$CancellationWaitSeconds}
$process=$null
try {
    $process=Start-Installer $PriorSetup 'baseline-170' $true
    if (-not $process.WaitForExit(180000) -or $process.ExitCode -ne 0) {throw 'Prior installation failed'}
    $process.Dispose();$process=$null
    if ((Get-ItemProperty $key).DisplayVersion -cne '1.7.0') {throw 'Published baseline version differs'}
    $before=Digest
    $process=Start-Installer $Setup '171-user-cancel' $false
    $record['pid']=$process.Id
    $record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Output 'ready.json') -Encoding UTF8
    if (-not $process.WaitForExit($CancellationWaitSeconds*1000)) {throw 'Interactive cancellation timed out'}
    $record['exit']=$process.ExitCode
    if ($process.ExitCode -ne 2) {throw 'Expected normal Inno Setup cancellation exit 2'}
    $log=Get-Content -Raw -LiteralPath (Join-Path $Output '171-user-cancel.log') -Encoding UTF8
    if ($log -notmatch '(?im)(user|cancel|取消)') {throw 'No user cancellation in the actual installer log'}
    if ((Digest) -cne $before) {throw 'Old runtime changed after cancellation'}
    if ((Get-ItemProperty $key).DisplayVersion -cne '1.7.0') {throw 'Old registry version changed'}
    if ((Get-FileHash -LiteralPath $data).Hash -cne $beforeData) {throw 'User profile data changed'}
    if (Test-Path -LiteralPath (Join-Path $install 'runtime.previous')) {throw 'Runtime backup left behind'}
    $record['checks']=@('normal non-silent installer exit 2','actual user cancellation log','all old runtime hashes retained','old version registry retained','user profile data retained','no runtime.previous residue')
    $record['status']='passed'
} catch {$record['status']='failed';$record['error']=$_.Exception.Message}
finally {
    if ($process) {if (-not $process.HasExited) {$process.Kill();$process.WaitForExit()};$process.Dispose()}
    $uninstall=Join-Path $install 'unins000.exe'
    if (Test-Path -LiteralPath $uninstall) {$cleanup=Start-Installer $uninstall 'cleanup' $true;try {if (-not $cleanup.WaitForExit(120000) -or $cleanup.ExitCode -ne 0) {$record['status']='failed';$record['cleanup_error']='Uninstall failed'}} finally {$cleanup.Dispose()}}
    if ($hadKey) {& reg.exe import $backup | Out-Null} elseif (Test-Path $key) {Remove-Item -LiteralPath $key -Recurse -Force}
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Output 'result.json') -Encoding UTF8
}
if ($record.status -ne 'passed') {exit 1}

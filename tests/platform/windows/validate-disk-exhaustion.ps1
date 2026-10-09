# Actual I/O exhaustion on a bounded, disposable disk in the dedicated Win10 VM.
param([Parameter(Mandatory=$true)][string]$Root,[Parameter(Mandatory=$true)][string]$Setup,[Parameter(Mandatory=$true)][string]$PriorSetup)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$expected=[IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'AppData\Local\Temp\bilix-171-validation'))
if ([IO.Path]::GetFullPath($Root) -cne $expected) {throw 'Unexpected validation directory'}
foreach ($path in @($Setup,$PriorSetup)) {
    if (-not [IO.Path]::GetFullPath($path).StartsWith($expected+'\',[StringComparison]::OrdinalIgnoreCase)) {throw 'Installer outside validation directory'}
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {throw 'Installer missing'}
}
$build=[int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
if ($build -lt 19041 -or $build -ge 22000) {throw 'Dedicated Windows 10 VM required'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'VHD mounting requires an administrator token in the test VM'}
if (Test-Path 'R:\') {throw 'Reserved test drive R is already in use'}
$id=[Guid]::NewGuid().ToString('N')
$evidence=Join-Path $Root ('diskfull-'+$id)
New-Item -ItemType Directory -Path $evidence | Out-Null
$vhd=Join-Path $evidence 'bounded-1024MiB.vhd'
$label='Bilix171_'+$id.Substring(0,6)
$install='R:\bilix171-'+$id
$filler='R:\bilix171-'+$id+'-filler.bin'
$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1'
$regNative='HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1'
$backup=Join-Path $evidence 'original-uninstall.reg'
$hadRegistry=Test-Path $key
if ($hadRegistry) {& reg.exe export $regNative $backup /y | Out-Null; if ($LASTEXITCODE -ne 0) {throw 'Registry backup failed'}}
$data=Join-Path $evidence 'user-data-sentinel.txt'
Set-Content -LiteralPath $data -Value 'Independent user data must survive installer failure' -Encoding ASCII
$dataHash=(Get-FileHash -LiteralPath $data).Hash
$record=[ordered]@{status='running';os_build=$build;vhd_mib=1024;volume_label=$label;setup_sha256=(Get-FileHash -LiteralPath $Setup).Hash;prior_setup_sha256=(Get-FileHash -LiteralPath $PriorSetup).Hash;checks=@()}
$mounted=$false;$process=$null;$errorText=$null
function DiskPart([string[]]$Commands,[string]$Name) {
    $file=Join-Path $evidence ($Name+'.txt')
    $Commands | Set-Content -LiteralPath $file -Encoding ASCII
    & diskpart.exe /s $file | Set-Content -LiteralPath (Join-Path $evidence ($Name+'.log')) -Encoding UTF8
    if ($LASTEXITCODE -ne 0) {throw 'DiskPart failed'}
}
function Assert-Volume {
    $volume=Get-Volume -DriveLetter R
    if ($volume.FileSystemLabel -cne $label -or $volume.Size -gt 1GB) {throw 'Unexpected test volume'}
}
function Free-Space {return (New-Object IO.DriveInfo('R:\')).AvailableFreeSpace}
function Fill-Volume([long]$Keep) {
    Assert-Volume
    $buffer=New-Object byte[] (1MB)
    $stream=[IO.File]::Open($filler,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try {
        $stream.Position=$stream.Length
        while ((Free-Space) -gt ($Keep+1MB)) {$stream.Write($buffer,0,$buffer.Length)}
        $remaining=(Free-Space)-$Keep
        if ($remaining -gt 0) {$stream.Write($buffer,0,[int][Math]::Min($remaining,$buffer.Length))}
        $stream.Flush($true)
    } finally {$stream.Dispose()}
}
function Start-Setup([string]$Exe,[string]$Name) {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$Exe
    $start.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="'+$install+'" /LOG="'+(Join-Path $evidence ($Name+'.log'))+'"'
    $start.UseShellExecute=$false;$start.CreateNoWindow=$true
    return [Diagnostics.Process]::Start($start)
}
function Digest {
    return ((Get-ChildItem -LiteralPath (Join-Path $install 'runtime') -Recurse -File | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($install.Length)+' '+(Get-FileHash -LiteralPath $_.FullName).Hash
    }) -join "`n")
}
try {
    DiskPart @(('create vdisk file="'+$vhd+'" maximum=1024 type=expandable'),('select vdisk file="'+$vhd+'"'),'attach vdisk','create partition primary',('format fs=ntfs quick label='+$label),'assign letter=R') 'create-vhd'
    $mounted=$true;Assert-Volume
    $process=Start-Setup $PriorSetup 'published-170-install'
    if (-not $process.WaitForExit(180000) -or $process.ExitCode -ne 0) {throw 'Prior installation failed'}
    $process.Dispose();$process=$null
    if ((Get-ItemProperty $key).DisplayVersion -cne '1.7.0') {throw 'Expected published 1.7.0 baseline'}
    Set-Content -LiteralPath (Join-Path $install 'runtime\retained-old-runtime.txt') -Value 'Real disk-full rollback sentinel' -Encoding ASCII
    $before=Digest
    Fill-Volume (350MB)
    $record['before_free_bytes']=Free-Space
    $process=Start-Setup $Setup '171-real-diskfull'
    $deadline=[DateTime]::UtcNow.AddSeconds(60)
    while (-not (Test-Path -LiteralPath (Join-Path $install 'runtime.previous')) -and -not $process.HasExited -and [DateTime]::UtcNow -lt $deadline) {Start-Sleep -Milliseconds 10}
    if (-not (Test-Path -LiteralPath (Join-Path $install 'runtime.previous'))) {throw 'Installer did not reach runtime replacement; no actual write-failure evidence'}
    $record['replacement_observed_utc']=[DateTime]::UtcNow.ToString('o')
    Fill-Volume (512KB)
    $record['exhausted_free_bytes']=Free-Space
    if (-not $process.WaitForExit(180000)) {throw 'Disk-full installation timed out'}
    $record['installer_exit']=$process.ExitCode
    if ($process.ExitCode -eq 0) {throw 'Disk-full installer unexpectedly succeeded'}
    $log=Get-Content -Raw -LiteralPath (Join-Path $evidence '171-real-diskfull.log') -Encoding UTF8
    if ($log -notmatch '(?im)(disk full|not enough space|\b112\b|磁盘空间不足|磁碟空间不足)') {throw 'Installer log has no genuine disk-space I/O error'}
    if ((Digest) -cne $before) {throw 'Previous runtime was not fully restored'}
    if ((Get-ItemProperty $key).DisplayVersion -cne '1.7.0') {throw 'Registry version was changed on failure'}
    if ((Get-FileHash -LiteralPath $data).Hash -cne $dataHash) {throw 'User data sentinel changed'}
    if (Test-Path -LiteralPath (Join-Path $install 'runtime.previous')) {throw 'Unexpected leftover runtime backup'}
    $record['checks']=@('actual bounded NTFS exhaustion after runtime replacement','nonzero installer exit and disk-full I/O log','all previous runtime hashes restored','published version registry unchanged','user data unchanged','no leftover runtime.previous')
    $record['status']='passed'
} catch {$errorText=$_.Exception.Message;$record['status']='failed';$record['error']=$errorText}
finally {
    if ($process) {if (-not $process.HasExited) {$process.Kill();$process.WaitForExit()};$process.Dispose()}
    if ($mounted) {
        try {
            Assert-Volume
            if (Test-Path -LiteralPath $filler) {Remove-Item -LiteralPath $filler -Force}
            $uninstall=Join-Path $install 'unins000.exe'
            if (Test-Path -LiteralPath $uninstall) {$cleanup=Start-Setup $uninstall 'uninstall';try {if (-not $cleanup.WaitForExit(120000) -or $cleanup.ExitCode -ne 0) {throw 'Uninstall cleanup failed'}} finally {$cleanup.Dispose()}}
        } catch {$record['cleanup_error']=$_.Exception.Message;$record['status']='failed'}
    }
    if (Test-Path -LiteralPath $vhd) {
        try {
            DiskPart @(('select vdisk file="'+$vhd+'"'),'detach vdisk') 'detach-vhd'
            Remove-Item -LiteralPath $vhd -Force
            $record['vhd_cleaned']=$true
        } catch {$record['detach_error']=$_.Exception.Message;$record['status']='failed'}
    }
    if ($hadRegistry) {& reg.exe import $backup | Out-Null} elseif (Test-Path $key) {Remove-Item -LiteralPath $key -Recurse -Force}
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidence 'result.json') -Encoding UTF8
    Write-Output ('Evidence: '+$evidence)
    Write-Output ('Status: '+$record.status)
}
if ($record.status -ne 'passed') {exit 1}

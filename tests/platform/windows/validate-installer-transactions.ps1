# Compile fixtures from the production .iss, including ValidationFailure, then
# run only in the dedicated Win10 VM with a real loaded user profile.
param(
    [Parameter(Mandatory=$true)][string]$FixtureRoot,
    [Parameter(Mandatory=$true)][string]$PriorSetup,
    [Parameter(Mandatory=$true)][string]$ResultDir
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$build=[int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
if ($build -lt 19041 -or $build -ge 22000) { throw 'Dedicated Windows 10 VM required' }
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (-not (Test-Path "Registry::HKEY_USERS\$sid")) { throw 'Loaded user profile required' }
$root=[IO.Path]::GetFullPath((Join-Path $ResultDir ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-installer')))
New-Item -ItemType Directory -Force -Path $root | Out-Null
$stable=Join-Path $root 'stable'
$preview=Join-Path $root 'preview'
$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1'
$previewKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C32C73E4-B820-46EC-BD14-05A02A426AA8}_is1'
$checks=New-Object 'System.Collections.Generic.List[object]'
function Run-Setup([string]$Exe,[string]$Dir,[string]$Name,[bool]$Success,[string]$ExtraArguments='') {
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$Exe
    $start.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="'+$Dir+'" /LOG="'+(Join-Path $root ($Name+'.log'))+'" '+$ExtraArguments
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $p=[Diagnostics.Process]::Start($start)
    try {
        if (-not $p.WaitForExit(120000)) { $p.Kill(); throw "$Name timed out" }
        if (($p.ExitCode -eq 0) -ne $Success) { throw "$Name unexpected exit $($p.ExitCode)" }
        $checks.Add([ordered]@{name=$Name; exit=$p.ExitCode}) | Out-Null
    } finally { $p.Dispose() }
}
function Version([string]$RegistryKey,[string]$Expected) {
    if ((Get-ItemProperty $RegistryKey).DisplayVersion -cne $Expected) { throw "Registry version differs: $Expected" }
}
function Digest([string]$Dir) {
    $lines=@(Get-ChildItem -LiteralPath (Join-Path $Dir 'runtime') -Recurse -File | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Dir.Length)+' '+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    })
    return ($lines -join "`n")
}
$failure=$null
try {
    Run-Setup $PriorSetup $stable 'published-160-install' $true
    Version $key '1.6.0'
    Set-Content -LiteralPath (Join-Path $stable 'runtime\retain-old-runtime.txt') -Value 'old-runtime-sentinel' -Encoding ASCII
    $old=Digest $stable
    Run-Setup (Join-Path $FixtureRoot 'fault\BiliX-GUI-Setup-1.7.0-windows-x64.exe') $stable 'fault-after-runtime-write' $false
    if ((Digest $stable) -cne $old) { throw 'Failure did not restore the full previous runtime' }
    if (Test-Path (Join-Path $stable 'runtime.previous')) { throw 'Unexpected backup after successful restoration' }
    Version $key '1.6.0'
    $checks.Add(@{name='fault-restores-published-runtime-and-registry';passed=$true}) | Out-Null
    Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.7.0-windows-x64.exe') $stable 'fixture-170-upgrade' $true
    Version $key '1.7.0'
    $current=Digest $stable
    $lockedFile=Join-Path $stable 'runtime\BiliX-GUI.exe'
    if (-not (Test-Path -LiteralPath $lockedFile)) { throw 'Fixture executable is missing' }
    $lock=[IO.File]::Open($lockedFile,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.7.0-windows-x64.exe') $stable 'occupied-runtime-rejected' $false '/NOCLOSEAPPLICATIONS'
    } finally { $lock.Dispose() }
    if ((Digest $stable) -cne $current) { throw 'Occupied runtime was modified' }
    Version $key '1.7.0'
    $checks.Add(@{name='occupied-runtime-preserves-files-and-registry';passed=$true}) | Out-Null
    $originalAcl=Get-Acl -LiteralPath $stable
    $deniedAcl=Get-Acl -LiteralPath $stable
    $identity=New-Object Security.Principal.SecurityIdentifier($sid)
    $deny=New-Object Security.AccessControl.FileSystemAccessRule($identity,[Security.AccessControl.FileSystemRights]::CreateDirectories,[Security.AccessControl.AccessControlType]::Deny)
    $deniedAcl.AddAccessRule($deny)
    try {
        Set-Acl -LiteralPath $stable -AclObject $deniedAcl
        Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.7.0-windows-x64.exe') $stable 'unwritable-runtime-parent-rejected' $false
    } finally { Set-Acl -LiteralPath $stable -AclObject $originalAcl }
    if ((Digest $stable) -cne $current) { throw 'Permission failure modified runtime' }
    Version $key '1.7.0'
    $checks.Add(@{name='permission-failure-preserves-files-and-registry';passed=$true}) | Out-Null
    Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.6.9-windows-x64.exe') $stable 'lower-version-rejected' $false
    if ((Digest $stable) -cne $current) { throw 'Downgrade modified runtime' }
    Version $key '1.7.0'
    Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.7.0-windows-x64.exe') $stable 'same-version-reinstall' $true
    Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.10.0-windows-x64.exe') $stable 'numeric-110-upgrade' $true
    Version $key '1.10.0'
    $higher=Digest $stable
    Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.7.0-windows-x64.exe') $stable 'numeric-17-after-110-rejected' $false
    if ((Digest $stable) -cne $higher) { throw 'Numeric downgrade modified runtime' }
    Run-Setup (Join-Path $FixtureRoot 'BiliX-GUI-Setup-1.7.0.dev1-windows-x64.exe') $preview 'preview-channel-independent' $true
    Version $previewKey '1.7.0.dev1'
    Version $key '1.10.0'
    # The published 1.6.0 installer is immutable and has no downgrade guard.
    Run-Setup $PriorSetup $stable 'published-160-overwrites-higher-fixture' $true
    Version $key '1.6.0'
    $checks.Add(@{name='old-installer-downgrade-risk-confirmed';passed=$true}) | Out-Null
} catch { $failure=$_.Exception.Message }
finally {
    foreach ($dir in @($preview,$stable)) {
        $uninstaller=Join-Path $dir 'unins000.exe'
        if (Test-Path -LiteralPath $uninstaller) {
            try { Run-Setup $uninstaller $dir ('uninstall-'+(Split-Path $dir -Leaf)) $true }
            catch { if ($failure) { $failure+='; '+$_.Exception.Message } else { $failure=$_.Exception.Message } }
        }
    }
    $record=@{status=$(if ($failure) {'failed'} else {'passed'});error=$failure;checks=@($checks.ToArray());os_build=$build;fixture_scope='Production installer script with small runtime fixture; fault starts from the published full 1.6.0 runtime'}
    $report=Join-Path $root 'result.json'
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8
    Write-Output "Validation report: $report"
    Write-Output "Status: $($record.status)"
    if ($failure) { Write-Error $failure; exit 1 }
}

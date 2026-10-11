# Run only in the dedicated Windows 10 acceptance VM. Fault Setup is compiled
# from the production .iss with ValidationFailure; it is never a release asset.
param([Parameter(Mandatory=$true)][string]$PriorSetup,[Parameter(Mandatory=$true)][string]$CandidateSetup,[Parameter(Mandatory=$true)][string]$FaultSetup,[Parameter(Mandatory=$true)][string]$ResultDir)
$ErrorActionPreference='Stop'
$build=[int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
if($build -lt 19041 -or $build -ge 22000){throw 'Dedicated Windows 10 VM required'}
$root=Join-Path $ResultDir ('installer-failure-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root|Out-Null
$installation=Join-Path $root 'installation'
$key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{3C888838-39AF-40C1-839B-A89F07E908AD}_is1'
$checks=New-Object 'System.Collections.Generic.List[object]'
function Run-Setup([string]$Exe,[string]$Name,[bool]$Success) {
 $start=New-Object Diagnostics.ProcessStartInfo;$start.FileName=$Exe;$start.UseShellExecute=$false
 $start.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /BILIXUPDATE /NOCLOSEAPPLICATIONS /DIR="'+$installation+'" /LOG="'+(Join-Path $root ($Name+'.log'))+'"'
 $process=[Diagnostics.Process]::Start($start)
 try {if(-not $process.WaitForExit(180000)){throw 'Setup timed out'}
  if(($process.ExitCode -eq 0) -ne $Success){throw ($Name+' unexpected result '+$process.ExitCode)}
  $checks.Add(@{case=$Name;exit=$process.ExitCode})|Out-Null
 }finally{if(-not $process.HasExited){$process.Kill()};$process.Dispose()}
}
function Digest {
 return (@(Get-ChildItem -LiteralPath (Join-Path $installation 'runtime') -Recurse -File|Sort-Object FullName|ForEach-Object {$_.FullName.Substring($installation.Length)+' '+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}) -join "`n")
}
$failure=$null
try {
 Run-Setup $PriorSetup 'prior-175-install' $true
 if((Get-ItemProperty $key).DisplayVersion -ne '1.7.5'){throw 'Wrong upgrade baseline'}
 $before=Digest
 Run-Setup $FaultSetup 'missing-file-after-runtime-write' $false
 if((Digest) -cne $before -or (Get-ItemProperty $key).DisplayVersion -ne '1.7.5' -or (Test-Path (Join-Path $installation 'runtime.previous'))){throw 'Failed installer did not restore full runtime and registry'}
 $checks.Add(@{case='full-published-runtime-restored';passed=$true})|Out-Null
 $target=Join-Path $installation 'runtime\BiliX-GUI.exe'
 $lock=[IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 try {Run-Setup $CandidateSetup 'occupied-runtime-rejected' $false}finally{$lock.Dispose()}
 if((Digest) -cne $before -or (Get-ItemProperty $key).DisplayVersion -ne '1.7.5'){throw 'Occupied installation changed previous files or registry'}
 $checks.Add(@{case='occupied-runtime-retained';passed=$true})|Out-Null
}catch{$failure=$_.Exception.Message}
finally{
 if(Test-Path (Join-Path $installation 'unins000.exe')){
  $start=New-Object Diagnostics.ProcessStartInfo;$start.FileName=Join-Path $installation 'unins000.exe';$start.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART';$start.UseShellExecute=$false
  $process=[Diagnostics.Process]::Start($start);[void]$process.WaitForExit(120000);$process.Dispose()
 }
 @{status=$(if($failure){'failed'}else{'passed'});checks=@($checks.ToArray());error=$failure;os_build=$build} | ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $root 'result.json') -Encoding UTF8
}
if($failure){throw $failure}
Write-Output "PASS current Inno failure restoration: $root"

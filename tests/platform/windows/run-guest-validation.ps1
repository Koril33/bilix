# Run validate-gui.ps1 as a real Windows logon with its user profile loaded.
# VirtualBox Guest Control may otherwise map HKCU to a default read-only hive.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $ArtifactDir,
    [Parameter(Mandatory = $true)][string] $ResultDir,
    [Parameter(Mandatory = $true)][string] $CredentialFile,
    [Parameter(Mandatory = $true)][string] $UserName,
    [Parameter(Mandatory = $true)][string] $UserDomain,
    [switch] $Install,
    [switch] $RequireWindows10,
    [string] $PriorSetup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Quote-Argument {
    param([string] $Value)
    if ($Value.Contains('"')) { throw 'Argument contains a quote' }
    return '"' + $Value + '"'
}

$secret = [IO.File]::ReadAllText($CredentialFile, [Text.Encoding]::ASCII)
try {
    $password = ConvertTo-SecureString $secret -AsPlainText -Force
}
finally {
    $secret = $null
    Remove-Item -LiteralPath $CredentialFile -Force -ErrorAction SilentlyContinue
}

$validator = Join-Path $PSScriptRoot 'validate-gui.ps1'
if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
    throw "Missing validator: $validator"
}
$arguments = @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', (Quote-Argument $validator),
    '-ArtifactDir', (Quote-Argument $ArtifactDir),
    '-ResultDir', (Quote-Argument $ResultDir)
)
if ($Install) { $arguments += '-Install' }
if ($RequireWindows10) { $arguments += '-RequireWindows10' }
if ($PriorSetup) { $arguments += @('-PriorSetup', (Quote-Argument $PriorSetup)) }

$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$start.Arguments = $arguments -join ' '
$start.WorkingDirectory = $PSScriptRoot
$start.UserName = $UserName
$start.Domain = $UserDomain
$start.Password = $password
$start.LoadUserProfile = $true
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
try {
    if (-not $process.Start()) { throw 'Could not start credentialed validator process' }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(1800000)) {
        $process.Kill()
        throw 'Credentialed validator timed out after 30 minutes'
    }
    Write-Output $stdout.Result
    if ($stderr.Result) { [Console]::Error.WriteLine($stderr.Result) }
    exit $process.ExitCode
}
finally {
    $process.Dispose()
}

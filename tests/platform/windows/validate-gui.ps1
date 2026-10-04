# Windows PowerShell 5.1-compatible validation for release GUI artifacts.
# Run in a disposable Windows 10 x64 VM. -Install writes an HKCU uninstall entry.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ArtifactDir,
    [Parameter(Mandatory = $true)]
    [string] $ResultDir,
    [switch] $Install,
    [switch] $RequireWindows10,
    [string] $PriorSetup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-True {
    param([bool] $Condition, [string] $Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-CheckedProcess {
    param(
        [string] $Executable,
        [string] $Arguments,
        [string] $WorkingDirectory,
        [int] $TimeoutSeconds = 180,
        [hashtable] $Overrides = @{}
    )
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = $Arguments
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($name in @('PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM', 'BILIX_FFMPEG')) {
        $start.EnvironmentVariables.Remove($name)
    }
    foreach ($name in $Overrides.Keys) {
        $start.EnvironmentVariables[$name] = [string] $Overrides[$name]
    }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    try {
        Assert-True $process.Start() "Could not start $Executable"
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            & taskkill.exe /PID $process.Id /T /F *> $null
            throw "Timed out after $TimeoutSeconds seconds: $Executable $Arguments"
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout.Result
            Stderr = $stderr.Result
        }
    }
    finally {
        $process.Dispose()
    }
}

function Assert-Success {
    param($Result, [string] $Description)
    Assert-True ($Result.ExitCode -eq 0) "$Description failed with exit code $($Result.ExitCode). stderr: $($Result.Stderr)"
    $script:checks.Add($Description) | Out-Null
}

function Wait-ExecutableUnlocked {
    param([string] $Path, [int] $TimeoutSeconds = 15)
    # A signaled process handle can precede Windows releasing the executable's
    # image/file lock. Do not race an immediate uninstall against that cleanup.
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $handle = $null
        try {
            $handle = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            return
        }
        catch [IO.IOException] { }
        catch [UnauthorizedAccessException] { }
        finally { if ($handle) { $handle.Dispose() } }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'The exited GUI executable is still locked after 15 seconds'
}

function Wait-PathRemoved {
    param([string] $Path, [int] $TimeoutSeconds = 15)
    # Inno's initial uninstaller process may exit before its cleanup helper.
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (Test-Path -LiteralPath $Path) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Uninstall left the GUI executable behind' }
        Start-Sleep -Milliseconds 100
    }
}

function Get-RequiredArtifact {
    param($Manifest, [string] $Name, [string] $Directory)
    $entry = @($Manifest.artifacts | Where-Object { $_.name -ceq $Name })
    Assert-True ($entry.Count -eq 1) "Manifest must contain exactly one $Name"
    Assert-True ($Name -cmatch '^[A-Za-z0-9._-]+$') "Unsafe artifact name: $Name"
    $path = Join-Path $Directory $Name
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing artifact: $path"
    $file = Get-Item -LiteralPath $path
    Assert-True ($file.Length -eq [long] $entry[0].bytes) "Incorrect size: $Name"
    $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-True ($digest -ceq ([string] $entry[0].sha256).ToLowerInvariant()) "SHA-256 mismatch: $Name"
    $script:checks.Add("sha256:$Name") | Out-Null
    return $path
}

Assert-True ([Environment]::Is64BitOperatingSystem) 'Windows x64 is required'
$artifactRoot = (Resolve-Path -LiteralPath $ArtifactDir).Path
$resultRoot = [IO.Path]::GetFullPath($ResultDir)
New-Item -ItemType Directory -Path $resultRoot -Force | Out-Null
$runRoot = Join-Path $resultRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$checks = New-Object 'System.Collections.Generic.List[string]'
$failure = $null
$installed = $false
$installRoot = Join-Path $runRoot 'installed-app'
$profileRoot = Join-Path $runRoot 'profile'
$downloadRoot = Join-Path $runRoot 'downloads'
$osInfo = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$buildNumber = [int] $osInfo.CurrentBuildNumber
$record = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    os_product = [string] $osInfo.ProductName
    os_build = $buildNumber
    architecture = [string] $env:PROCESSOR_ARCHITECTURE
    machine = [string] $env:COMPUTERNAME
    artifact_dir = $artifactRoot
    checks = @()
    status = 'failed'
    error = $null
}

try {
    Assert-True (-not $PriorSetup -or $Install.IsPresent) '-PriorSetup requires -Install'
    if ($RequireWindows10) {
        Assert-True ($buildNumber -ge 19041 -and $buildNumber -lt 22000) "Expected Windows 10, found build $buildNumber"
        $checks.Add('windows10-build') | Out-Null
    }
    $manifestPath = Join-Path $artifactRoot 'release-manifest-windows.json'
    $platformManifest = Test-Path -LiteralPath $manifestPath -PathType Leaf
    if (-not $platformManifest) {
        $manifestPath = Join-Path $artifactRoot 'release-manifest.json'
    }
    Assert-True (Test-Path -LiteralPath $manifestPath -PathType Leaf) 'Missing Windows or complete release manifest'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $version = [string] $manifest.version
    Assert-True ($version -cmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?$') "Unexpected version in manifest: $version"
    $record['version'] = $version
    $record['manifest_sha256'] = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $portableName = "BiliX-GUI-Portable-$version-windows-x64.exe"
    $setupName = "BiliX-GUI-Setup-$version-windows-x64.exe"
    $sourceName = "BiliX-GUI-licenses-and-source-$version-windows-x64.zip"
    $portable = Get-RequiredArtifact $manifest $portableName $artifactRoot
    $setup = Get-RequiredArtifact $manifest $setupName $artifactRoot
    $source = Get-RequiredArtifact $manifest $sourceName $artifactRoot
    $expectedCount = if ($platformManifest) { 3 } else { 8 }
    Assert-True (@($manifest.artifacts).Count -eq $expectedCount) 'Release manifest has unexpected artifacts'
    $checksumsName = if ($platformManifest) { 'SHA256SUMS-windows.txt' } else { 'SHA256SUMS.txt' }
    $checksumsPath = Join-Path $artifactRoot $checksumsName
    Assert-True (Test-Path -LiteralPath $checksumsPath -PathType Leaf) "Missing $checksumsName"
    $actualSums = @(Get-Content -LiteralPath $checksumsPath -Encoding UTF8)
    $expectedSums = @($manifest.artifacts | ForEach-Object {
        ([string] $_.sha256).ToLowerInvariant() + '  ' + [string] $_.name
    })
    Assert-True ($actualSums.Count -eq $expectedSums.Count) 'Checksum line count differs from Windows manifest'
    for ($line = 0; $line -lt $expectedSums.Count; $line++) {
        Assert-True ($actualSums[$line] -ceq $expectedSums[$line]) "Checksum line $($line + 1) differs from Windows manifest"
    }
    $checks.Add("sha256sums:$checksumsName") | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($source)
    try {
        foreach ($entry in $archive.Entries) {
            $archivePath = $entry.FullName.Replace('\', '/')
            Assert-True (-not ($archivePath -match '(^|/)(\.vagrant|\.git|\.aws|\.codex)(/|$)|(^|/)(private_key|id_rsa|id_ed25519)$')) "Source archive contains a private state path: $archivePath"
        }
    }
    finally {
        $archive.Dispose()
    }
    $checks.Add('source-archive-excludes-private-state') | Out-Null

    # A Unicode path and isolated profile catch missing Qt plugins, FFmpeg, and path handling.
    $unicodeName = ([string][char]0x4E2D) + ([string][char]0x6587) + ' path'
    $portableRoot = Join-Path $runRoot $unicodeName
    New-Item -ItemType Directory -Path $portableRoot, $profileRoot, $downloadRoot -Force | Out-Null
    $profileSentinel = Join-Path $profileRoot 'keep-after-uninstall.txt'
    $downloadSentinel = Join-Path $downloadRoot 'keep-after-uninstall.txt'
    $configFile = Join-Path $profileRoot 'config.toml'
    Set-Content -LiteralPath $profileSentinel -Value 'BiliX validation profile' -Encoding ASCII
    Set-Content -LiteralPath $downloadSentinel -Value 'BiliX validation download' -Encoding ASCII
    [IO.File]::WriteAllText($configFile,
        ('download_dir = "' + $downloadRoot.Replace('\', '/') + '"') + [Environment]::NewLine,
        (New-Object Text.UTF8Encoding($false)))
    $configHash = (Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash
    $portableCopy = Join-Path $portableRoot $portableName
    Copy-Item -LiteralPath $portable -Destination $portableCopy
    $environment = @{
        BILIX_CONFIG_DIR = $profileRoot
        BILIX_DOWNLOAD_DIR = $downloadRoot
    }
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $smoke = Invoke-CheckedProcess $portableCopy '--smoke-test' $portableRoot 180 $environment
        Assert-Success $smoke "portable-smoke-$attempt"
    }

    if ($Install) {
        Assert-True ($RequireWindows10.IsPresent) 'Installer validation requires -RequireWindows10 to avoid installing on the host'
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        Assert-True (Test-Path -LiteralPath ("Registry::HKEY_USERS\" + $sid)) 'The current user registry hive is not loaded; run in an interactive logon or through run-guest-validation.ps1'
        $checks.Add('profile-hive-loaded') | Out-Null
        if ($PriorSetup) {
            $prior = (Resolve-Path -LiteralPath $PriorSetup).Path
            $priorName = Split-Path -Leaf $prior
            Assert-True ($priorName -cmatch '^BiliX-GUI-Setup-(?<version>[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?)-windows-x64\.exe$') 'PriorSetup must be a versioned BiliX Windows installer'
            $priorVersion = $Matches['version']
            $record['prior_setup'] = [ordered]@{
                version = $priorVersion
                name = $priorName
                sha256 = (Get-FileHash -LiteralPath $prior -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            $currentPreview = $version -match '\.dev[0-9]+$'
            $priorPreview = $priorName -match '\.dev[0-9]+-windows-x64\.exe$'
            Assert-True ($currentPreview -eq $priorPreview) 'PriorSetup and target must be in the same preview or stable installer channel'
            $priorParts = $priorVersion -split '\.dev'
            $currentParts = $version -split '\.dev'
            $priorCore = [version] $priorParts[0]
            $currentCore = [version] $currentParts[0]
            $isOlder = $priorCore -lt $currentCore
            if ($priorCore -eq $currentCore -and $currentPreview) {
                $isOlder = [int] $priorParts[1] -lt [int] $currentParts[1]
            }
            Assert-True $isOlder 'PriorSetup must be older than the target version'
            $priorRun = Invoke-CheckedProcess $prior ('/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $installRoot + '"') $runRoot 600
            Assert-Success $priorRun 'prior-setup-install'
            $installed = $true
            $priorExe = Join-Path $installRoot 'runtime\BiliX-GUI.exe'
            Assert-Success (Invoke-CheckedProcess $priorExe '--smoke-test' $installRoot 180 $environment) 'prior-installed-gui-smoke'
            Wait-ExecutableUnlocked $priorExe
        }
        $setupLog = Join-Path $runRoot 'setup.log'
        $arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="' + $installRoot + '" /LOG="' + $setupLog + '"'
        $installRun = Invoke-CheckedProcess $setup $arguments $runRoot 600
        $installCheck = if ($PriorSetup) { 'setup-upgrade' } else { 'setup-install' }
        Assert-Success $installRun $installCheck
        $installed = $true
        $installedExe = Join-Path $installRoot 'runtime\BiliX-GUI.exe'
        Assert-True (Test-Path -LiteralPath $installedExe -PathType Leaf) 'Installed GUI executable is missing'
        foreach ($name in @('LICENSE', 'THIRD_PARTY_NOTICES.md', 'LICENSES', 'SOURCES')) {
            Assert-True (Test-Path -LiteralPath (Join-Path $installRoot $name)) "Missing installed material: $name"
        }
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $installRoot 'SOURCES\tests\vm\.vagrant'))) 'Installed sources include Vagrant state'
        $checks.Add('installer-files-and-licenses') | Out-Null
        $installedSmoke = Invoke-CheckedProcess $installedExe '--smoke-test' $installRoot 180 $environment
        Assert-Success $installedSmoke 'installed-gui-smoke'
        Assert-True ((Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash -ceq $configHash) 'Installation or upgrade changed shared configuration'
        Assert-True ((Get-Content -LiteralPath $profileSentinel -Raw).Trim() -ceq 'BiliX validation profile') 'Installation or upgrade changed profile data'
        Assert-True ((Get-Content -LiteralPath $downloadSentinel -Raw).Trim() -ceq 'BiliX validation download') 'Installation or upgrade changed download data'
        $checks.Add('install-or-upgrade-preserves-config-and-downloads') | Out-Null
    }
}
catch {
    $failure = $_.Exception.Message
}
finally {
    if ($installed) {
        try {
            $uninstallers = @(Get-ChildItem -LiteralPath $installRoot -Filter 'unins*.exe' -File)
            Assert-True ($uninstallers.Count -eq 1) 'Expected one Inno Setup uninstaller'
            $uninstallLog = Join-Path $runRoot 'uninstall.log'
            $uninstallArgs = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="' + $uninstallLog + '"'
            Wait-ExecutableUnlocked (Join-Path $installRoot 'runtime\BiliX-GUI.exe')
            $checks.Add('installed-gui-exited-and-unlocked') | Out-Null
            $uninstallRun = Invoke-CheckedProcess $uninstallers[0].FullName $uninstallArgs $runRoot 600
            Assert-Success $uninstallRun 'setup-uninstall'
            Wait-PathRemoved (Join-Path $installRoot 'runtime\BiliX-GUI.exe')
            Assert-True (Test-Path -LiteralPath (Join-Path $profileRoot 'keep-after-uninstall.txt')) 'Uninstall removed user data'
            Assert-True ((Get-FileHash -LiteralPath $configFile -Algorithm SHA256).Hash -ceq $configHash) 'Uninstall changed shared configuration'
            Assert-True ((Get-Content -LiteralPath $downloadSentinel -Raw).Trim() -ceq 'BiliX validation download') 'Uninstall changed download data'
            $checks.Add('uninstall-preserves-profile') | Out-Null
        }
        catch {
            if ($failure) { $failure += '; cleanup: ' + $_.Exception.Message }
            else { $failure = 'cleanup: ' + $_.Exception.Message }
        }
    }
    $record['checks'] = @($checks.ToArray())
    $record['status'] = if ($failure) { 'failed' } else { 'passed' }
    $record['error'] = $failure
    $record['finished_utc'] = [DateTime]::UtcNow.ToString('o')
    $report = Join-Path $runRoot 'result.json'
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $report -Encoding UTF8
    Write-Output "Validation report: $report"
    Write-Output "Status: $($record['status'])"
    foreach ($check in $checks) { Write-Output "PASS $check" }
    if ($failure) { Write-Error $failure; exit 1 }
}

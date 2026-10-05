# Run in PowerShell on a Windows host with Vagrant and VirtualBox installed.
# Each acceptance target starts from a new VM. A failing VM is left available
# for diagnosis. The Linux build and evidence live under ignored dist/gui/.
param(
    [switch]$SkipBuild,
    [switch]$PrepareOnly,
    [switch]$ReusePrepared,
    [string]$Maintainer = '',
    [string]$ArtifactDir = '',
    [string]$PriorDeb = '',
    [ValidateSet('ubuntu2204', 'ubuntu2404', 'debian12', 'debian13')]
    [string[]]$Targets = @('ubuntu2204', 'ubuntu2404', 'debian12', 'debian13')
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$outRoot = if ($ArtifactDir) { [IO.Path]::GetFullPath($ArtifactDir) } else { Join-Path $repoRoot 'dist\gui' }
if ($ArtifactDir -and -not $SkipBuild) {
    throw '-ArtifactDir requires -SkipBuild; native builds output to dist/gui.'
}
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null
if ($Maintainer -and $Maintainer -notmatch '^[A-Za-z0-9 ._-]+ <[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+>$') {
    throw 'Maintainer must be Name <email@example.org> with plain ASCII characters.'
}

function Invoke-Vagrant([string[]]$Arguments) {
    & vagrant @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "vagrant $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Remove-TestVM([string]$Target) {
    $idFile = Join-Path $PSScriptRoot ".vagrant\machines\$Target\virtualbox\id"
    if (-not (Test-Path -LiteralPath $idFile -PathType Leaf)) {
        return
    }
    $id = (Get-Content -LiteralPath $idFile -Raw).Trim()
    if ($id -notmatch '^[0-9a-fA-F-]{36}$') {
        throw "Unexpected VirtualBox VM ID in $idFile"
    }
    $vbCommand = Get-Command VBoxManage.exe -ErrorAction SilentlyContinue
    $vbPath = if ($vbCommand) { $vbCommand.Source } else { $null }
    if (-not $vbPath) {
        $known = 'C:\Software\VirtualBox\VBoxManage.exe'
        if (Test-Path -LiteralPath $known -PathType Leaf) {
            $vbPath = $known
        }
    }
    if (-not $vbPath) {
        throw 'VBoxManage.exe is required to verify an existing test VM before destruction.'
    }
    $info = & $vbPath showvminfo $id --machinereadable
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify VirtualBox VM $id"
    }
    $expectedName = "bilix-validation-$Target"
    if ($info -notcontains "name=`"$expectedName`"") {
        throw "VM $id is not the expected dedicated $expectedName VM"
    }
    $cfgLine = $info | Where-Object { $_ -like 'CfgFile=*' } | Select-Object -First 1
    if (-not $cfgLine -or $cfgLine -notmatch '^CfgFile="(.+)"$') {
        throw "Cannot resolve the VM configuration path for $expectedName"
    }
    $cfg = (Resolve-Path -LiteralPath $Matches[1]).Path
    $machineDirectory = (Resolve-Path -LiteralPath (Split-Path -Parent $cfg)).Path
    $systemProperties = & $vbPath list systemproperties
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not read the VirtualBox default machine folder.'
    }
    $folderLine = $systemProperties | Where-Object { $_ -like 'Default Machine Folder:*' } | Select-Object -First 1
    if (-not $folderLine) {
        throw 'Could not identify the VirtualBox default machine folder.'
    }
    $defaultFolder = (Resolve-Path -LiteralPath (($folderLine -split ':\s+', 2)[1])).Path
    if ((Split-Path -Leaf $machineDirectory) -ne $expectedName -or
        (Split-Path -Parent $machineDirectory) -ne $defaultFolder) {
        throw "VM configuration is outside its expected named directory: $cfg"
    }
    Invoke-Vagrant @('destroy', '-f', $Target)
}

Push-Location $PSScriptRoot
try {
    Invoke-Vagrant @('validate')
    if ($PrepareOnly -and -not $SkipBuild) {
        throw '-PrepareOnly requires -SkipBuild.'
    }
    if ($PrepareOnly) {
        foreach ($target in $Targets) {
            $machine = if ($target -eq 'ubuntu2204') { 'ubuntu2204clean' } else { $target }
            Remove-TestVM $machine
            Invoke-Vagrant @('up', $machine, '--provider=virtualbox')
            Invoke-Vagrant @('halt', $machine)
        }
        return
    }
    if (-not $SkipBuild) {
        & python (Join-Path $PSScriptRoot 'write-source-manifest.py')
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not create the Git source manifest for the Linux VM.'
        }
        Remove-TestVM 'ubuntu2204'
        Invoke-Vagrant @('up', 'ubuntu2204', '--provider=virtualbox')
        $buildCommand = 'bash /bilix-host/tests/vm/build-ubuntu2204.sh'
        if ($Maintainer) {
            $buildCommand = "BILIX_DEB_MAINTAINER='$Maintainer' $buildCommand"
        }
        Invoke-Vagrant @('ssh', 'ubuntu2204', '-c', $buildCommand)
        Invoke-Vagrant @('halt', 'ubuntu2204')
    }

    $resolvedArtifacts = (Resolve-Path -LiteralPath $outRoot).Path
    $distRoot = Join-Path $repoRoot 'dist'
    if (-not $resolvedArtifacts.StartsWith($distRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'ArtifactDir must be inside this repository dist directory for the VM shared folder.'
    }
    $manifestPath = Join-Path $resolvedArtifacts 'release-manifest-linux.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        $manifestPath = Join-Path $resolvedArtifacts 'release-manifest.json'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $packages = @($manifest.artifacts | Where-Object { $_.name -cmatch '^djhx-bilix-gui_[0-9][A-Za-z0-9.+~-]*_amd64\.deb$' })
    if ($packages.Count -ne 1) {
        throw 'The selected manifest must list exactly one amd64 GUI deb.'
    }
    $package = Join-Path $resolvedArtifacts $packages[0].name
    if ((Get-Item -LiteralPath $package).Length -ne [long]$packages[0].bytes -or
        (Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash.ToLowerInvariant() -cne $packages[0].sha256) {
        throw 'Selected deb differs from its manifest.'
    }
    $guestPackage = '/bilix-host/' + $package.Substring($repoRoot.Length + 1).Replace('\', '/')
    # Quote the shared-folder path for the guest shell, including spaces/apostrophes.
    $quotedPackage = "'" + $guestPackage.Replace("'", "'`"'`"'") + "'"
    $quotedPrior = ''
    if ($PriorDeb) {
        $priorInput = if ([IO.Path]::IsPathRooted($PriorDeb)) { $PriorDeb } else { Join-Path $repoRoot $PriorDeb }
        $priorPath = (Resolve-Path -LiteralPath $priorInput).Path
        if (-not $priorPath.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'PriorDeb must be inside this repository shared folder.'
        }
        $priorGuest = '/bilix-host/' + $priorPath.Substring($repoRoot.Length + 1).Replace('\', '/')
        $quotedPrior = "'" + $priorGuest.Replace("'", "'`"'`"'") + "'"
    }
    foreach ($target in $Targets) {
        $machine = if ($target -eq 'ubuntu2204') { 'ubuntu2204clean' } else { $target }
        if ($ReusePrepared) {
            Invoke-Vagrant @('up', $machine, '--provider=virtualbox', '--no-provision')
        } else {
            Remove-TestVM $machine
            Invoke-Vagrant @('up', $machine, '--provider=virtualbox')
        }
        Invoke-Vagrant @('ssh', $machine, '-c', "bash /bilix-host/tests/vm/accept-deb.sh $target $quotedPackage $quotedPrior")
        Invoke-Vagrant @('halt', $machine)
    }
}
finally {
    Pop-Location
}

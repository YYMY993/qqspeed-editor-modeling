[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$InstallDir,
    [switch]$CheckOnly,
    [switch]$NoRegister
)
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'install_bridge.py'
$installOptions = @()
if ($InstallDir) { $installOptions += @('--install-dir', $InstallDir) }
if ($CheckOnly) { $installOptions += '--check-only' }
if ($NoRegister) { $installOptions += '--no-register' }
& $Python -X utf8 $installer @installOptions
if ($LASTEXITCODE -ne 0) { throw 'Bridge installer did not complete.' }

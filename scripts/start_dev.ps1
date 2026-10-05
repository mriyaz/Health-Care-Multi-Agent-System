# HealthOS local dev startup (Windows)
# Creates/uses .venv, installs deps if needed, then runs scripts/start_dev.py.
#
# Usage (from repo root):
#   .\scripts\start_dev.ps1
#   .\scripts\start_dev.ps1 -SkipDocker
#   .\scripts\start_dev.ps1 -NoApi

param(
    [switch]$SkipDocker,
    [switch]$SkipMigrate,
    [switch]$SkipSeed,
    [switch]$NoApi,
    [string]$FhirBaseUrl = "",
    [double]$HapiTimeout = 180
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$venvPip = Join-Path $RepoRoot ".venv\Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
}

$requirements = Join-Path $RepoRoot "requirements.txt"
$marker = Join-Path $RepoRoot ".venv\.healthos-deps-installed"
if (-not (Test-Path $marker) -or (Get-Item $requirements).LastWriteTimeUtc -gt (Get-Item $marker).LastWriteTimeUtc) {
    Write-Host "Installing Python dependencies..."
    & $venvPip install -r $requirements
    New-Item -ItemType File -Path $marker -Force | Out-Null
}

$pyArgs = @("scripts/start_dev.py")
if ($SkipDocker) { $pyArgs += "--skip-docker" }
if ($SkipMigrate) { $pyArgs += "--skip-migrate" }
if ($SkipSeed) { $pyArgs += "--skip-seed" }
if ($NoApi) { $pyArgs += "--no-api" }
if ($FhirBaseUrl) { $pyArgs += @("--fhir-base-url", $FhirBaseUrl) }
$pyArgs += @("--hapi-timeout", $HapiTimeout)

& $venvPython @pyArgs

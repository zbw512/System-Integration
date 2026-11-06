[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$SecretsPath = (Join-Path $PSScriptRoot "autodl.secrets.psd1")
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$config = Import-AutoDLConfig -Path $ConfigPath
$secrets = Import-AutoDLSecrets -Path $SecretsPath
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
Assert-LocalPathFile -Path $python -Description "后端 Python"

$env:BACKEND_VLM_ADAPTER = "minicpm_remote"
$env:BACKEND_VLM_REMOTE_URL = "http://127.0.0.1:$($config.LocalPort)"
$env:BACKEND_VLM_REMOTE_TOKEN = [string]$secrets.BackendRemoteToken
$env:BACKEND_VLM_REMOTE_TIMEOUT_S = "300"
$env:BACKEND_VLM_REMOTE_RETRIES = "2"
$env:BACKEND_VLM_MAX_FRAMES = "8"
$env:BACKEND_VLM_WINDOW_SECONDS = "3"
$env:BACKEND_VLM_WINDOW_STRIDE_SECONDS = "3"

Write-Host "使用 AutoDL 适配器启动 Flask（Ctrl+C 停止）..."
Push-Location (Join-Path $projectRoot "backend")
try {
    & $python "app.py"
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

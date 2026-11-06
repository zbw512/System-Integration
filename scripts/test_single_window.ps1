[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$SecretsPath = (Join-Path $PSScriptRoot "autodl.secrets.psd1"),
    [string]$Video = "",
    [double]$StartS = 0.0,
    [double]$EndS = 3.0,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$previousConsoleOutputEncoding = [Console]::OutputEncoding
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousPythonUtf8 = $env:PYTHONUTF8
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    $config = Import-AutoDLConfig -Path $ConfigPath
    $secrets = Import-AutoDLSecrets -Path $SecretsPath
    if (-not $Video) { $Video = [string]$config.SmokeVideoPath }
    Assert-LocalPathFile -Path $Video -Description "单窗口测试视频"

    $projectRoot = Split-Path -Parent $PSScriptRoot
    if (-not $Python) {
        $Python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
    }
    Assert-LocalPathFile -Path $Python -Description "后端 Python"

    $clientScript = Join-Path $PSScriptRoot "test_window_client.py"
    $url = "http://127.0.0.1:$($config.LocalPort)/predict_window"
    $oldToken = $env:VLM_SERVICE_TOKEN
    try {
        $env:VLM_SERVICE_TOKEN = [string]$secrets.ServiceToken
        & $Python $clientScript `
            --video $Video `
            --start-s $StartS `
            --end-s $EndS `
            --url $url
        if ($LASTEXITCODE -ne 0) {
            throw "单窗口真实推理测试失败，退出码 $LASTEXITCODE"
        }
    } finally {
        if ($null -eq $oldToken) {
            Remove-Item Env:VLM_SERVICE_TOKEN -ErrorAction SilentlyContinue
        } else {
            $env:VLM_SERVICE_TOKEN = $oldToken
        }
    }
} finally {
    [Console]::OutputEncoding = $previousConsoleOutputEncoding
    if ($null -eq $previousPythonIoEncoding) {
        Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONIOENCODING = $previousPythonIoEncoding
    }
    if ($null -eq $previousPythonUtf8) {
        Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONUTF8 = $previousPythonUtf8
    }
}

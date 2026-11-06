[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$Video = ""
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
    if (-not $Video) { $Video = [string]$config.SmokeVideoPath }
    Assert-LocalPathFile -Path $Video -Description "端到端测试视频"

    $projectRoot = Split-Path -Parent $PSScriptRoot
    $python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
    Assert-LocalPathFile -Path $python -Description "后端 Python"

    & $python (Join-Path $PSScriptRoot "test_full_video_e2e.py") `
        --video $Video `
        --api-base $config.BackendBaseUrl
    if ($LASTEXITCODE -ne 0) {
        throw "完整视频端到端测试失败"
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

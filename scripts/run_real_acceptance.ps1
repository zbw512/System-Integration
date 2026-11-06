[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$SecretsPath = (Join-Path $PSScriptRoot "autodl.secrets.psd1"),
    [switch]$SkipSingleWindow,
    [switch]$SkipEndToEnd
)

$ErrorActionPreference = "Stop"

Write-Host "== AutoDL 连接与模型健康 =="
& (Join-Path $PSScriptRoot "check_autodl_connection.ps1") `
    -ConfigPath $ConfigPath `
    -SecretsPath $SecretsPath

if (-not $SkipSingleWindow) {
    Write-Host "== 真实单窗口 8 帧推理 =="
    & (Join-Path $PSScriptRoot "test_single_window.ps1") `
        -ConfigPath $ConfigPath `
        -SecretsPath $SecretsPath
}

if (-not $SkipEndToEnd) {
    Write-Host "== Flask 上传 → AutoDL → Segment 端到端 =="
    & (Join-Path $PSScriptRoot "test_full_video_e2e.ps1") `
        -ConfigPath $ConfigPath
}

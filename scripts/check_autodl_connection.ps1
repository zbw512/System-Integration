[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$SecretsPath = (Join-Path $PSScriptRoot "autodl.secrets.psd1"),
    [switch]$SkipRemote,
    [switch]$SkipTunnel
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$config = Import-AutoDLConfig -Path $ConfigPath
$secrets = Import-AutoDLSecrets -Path $SecretsPath

if (-not $SkipRemote) {
    Write-Host "[1/3] 检查 SSH 和 AutoDL GPU..."
    $gpu = Invoke-AutoDLSsh -Config $config -CaptureOutput -RemoteCommand @(
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader"
    )
    Write-Host "远端 GPU：$gpu"

    $serviceState = Invoke-AutoDLSsh -Config $config -CaptureOutput -RemoteCommand @(
        "bash",
        "$($config.RemoteProjectRoot)/deploy/autodl/healthcheck.sh"
    )
    Write-Host "云端服务：$serviceState"
}

if (-not $SkipTunnel) {
    Write-Host "[2/3] 检查本地 SSH 隧道..."
    $healthUrl = "http://127.0.0.1:$($config.LocalPort)/health"
    try {
        $health = Invoke-RestMethod `
            -Uri $healthUrl `
            -Headers @{ Authorization = "Bearer $($secrets.ServiceToken)" } `
            -TimeoutSec 15
    } catch {
        throw "无法通过隧道访问 AutoDL 服务：$healthUrl。请先运行 start_autodl_tunnel.ps1，并检查云端服务。"
    }
    if (-not $health.loaded) {
        throw "AutoDL 服务可达，但模型未加载：$($health.load_error)"
    }
    Write-Host "隧道健康：loaded=$($health.loaded)，GPU=$($health.gpu_name)，模型=$($health.model.version)/$($health.model.checkpoint)"
}

Write-Host "[3/3] AutoDL 连接检查通过。"

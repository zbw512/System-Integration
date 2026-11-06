[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$SecretsPath = (Join-Path $PSScriptRoot "autodl.secrets.psd1"),
    [string]$TorchIndexUrl = "",
    [switch]$SkipModelUpload,
    [switch]$SkipServiceUpload,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$config = Import-AutoDLConfig -Path $ConfigPath
$secrets = Import-AutoDLSecrets -Path $SecretsPath
$remoteRoot = [string]$config.RemoteProjectRoot
if ($remoteRoot -notmatch "^/[A-Za-z0-9._/-]+$") {
    throw "RemoteProjectRoot 只能包含安全 ASCII 路径字符"
}

if (-not $SkipServiceUpload) {
    Write-Host "== 1. 上传服务代码 =="
    & (Join-Path $PSScriptRoot "upload_service_to_autodl.ps1") -ConfigPath $ConfigPath
}

Write-Host "== 2. 写入远端环境文件 =="
$envContent = @(
    "VLM_SERVICE_TOKEN=$($secrets.ServiceToken)",
    "VLM_BASE_MODEL_PATH=$($config.BaseModelRemotePath)",
    "VLM_ADAPTER_PATH=$($config.AdapterRemotePath)",
    "VLM_HOST=127.0.0.1",
    "VLM_PORT=$($config.RemoteServicePort)",
    "VLM_MAX_FRAMES=8",
    "VLM_MAX_REQUEST_BYTES=67108864",
    "VLM_MAX_FRAME_BYTES=16777216",
    "VLM_MAX_IMAGE_PIXELS=16000000",
    "VLM_LOAD_ON_STARTUP=true",
    "VLM_LOG_LEVEL=INFO"
) -join "`n"
$sshArgs = Get-AutoDLSshArguments -Config $config
$writeEnvCommand = "umask 077 && mkdir -p '$remoteRoot/deploy/autodl' && tr -d '\r' > '$remoteRoot/deploy/autodl/.env' && chmod 600 '$remoteRoot/deploy/autodl/.env'"
$sshCommandArguments = @($sshArgs) + $writeEnvCommand
$envContent | & ssh @sshCommandArguments
if ($LASTEXITCODE -ne 0) {
    throw "远端环境文件写入失败"
}

if (-not $SkipModelUpload) {
    Write-Host "== 3. 上传并校验模型 =="
    & (Join-Path $PSScriptRoot "upload_model_to_autodl.ps1") -ConfigPath $ConfigPath
}

Write-Host "== 4. 安装云端环境 =="
Invoke-AutoDLSsh -Config $config -RemoteCommand @(
    "bash", "'$remoteRoot/deploy/autodl/stop_service.sh'"
)
$torchPrefix = if ($TorchIndexUrl) {
    "TORCH_INDEX_URL='$TorchIndexUrl' TORCH_VERSION='2.14.1' "
} else {
    ""
}
$installCommand = "${torchPrefix}bash '$remoteRoot/deploy/autodl/install.sh'"
Invoke-AutoDLSsh -Config $config -RemoteCommand @($installCommand)

Write-Host "== 5. 检查云端 GPU、依赖和模型 =="
Invoke-AutoDLSsh -Config $config -RemoteCommand @(
    "bash", "'$remoteRoot/deploy/autodl/check_environment.sh'"
)

Write-Host "== 6. 启动模型服务 =="
Invoke-AutoDLSsh -Config $config -RemoteCommand @(
    "bash", "'$remoteRoot/deploy/autodl/start_service.sh'"
)

Write-Host "== 7. 启动本地 SSH 隧道 =="
& (Join-Path $PSScriptRoot "start_autodl_tunnel.ps1") -ConfigPath $ConfigPath

Write-Host "== 8. 检查 SSH、隧道和模型健康 =="
& (Join-Path $PSScriptRoot "check_autodl_connection.ps1") `
    -ConfigPath $ConfigPath `
    -SecretsPath $SecretsPath

if (-not $SkipSmokeTest) {
    Write-Host "== 9. 真实单窗口推理测试 =="
    & (Join-Path $PSScriptRoot "test_single_window.ps1") `
        -ConfigPath $ConfigPath `
        -SecretsPath $SecretsPath
}

Write-Host "AutoDL 部署与真实单窗口验收完成。"
Write-Host "启动本地 Flask：.\scripts\start_backend_remote.ps1"

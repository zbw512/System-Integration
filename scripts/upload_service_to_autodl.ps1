[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1")
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$config = Import-AutoDLConfig -Path $ConfigPath
if (-not $WhatIfPreference -and $config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
    Assert-LocalPathFile -Path $config.IdentityFile -Description "SSH 私钥"
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$serviceDir = Join-Path $projectRoot "cloud_vlm_service"
$deployDir = Join-Path $projectRoot "deploy\autodl"
$remoteRoot = [string]$config.RemoteProjectRoot
$target = "$($config.SshUser)@$($config.SshHostName)"

if ($remoteRoot -notmatch "^/[A-Za-z0-9._/-]+$") {
    throw "RemoteProjectRoot 只能包含安全 ASCII 路径字符"
}
Assert-LocalPathFile -Path (Join-Path $serviceDir "app.py") -Description "云端服务 app.py"
Assert-LocalPathFile -Path (Join-Path $deployDir "install.sh") -Description "云端安装脚本"

if ($PSCmdlet.ShouldProcess("${target}:$remoteRoot", "上传云端服务代码")) {
    Invoke-AutoDLSsh -Config $config -RemoteCommand @(
        "mkdir", "-p",
        "'$remoteRoot/cloud_vlm_service'",
        "'$remoteRoot/deploy/autodl'",
        "'$remoteRoot/scripts'"
    )

    $serviceFiles = @(
        "__init__.py",
        "app.py",
        "config.py",
        "contract.py",
        "errors.py",
        "load_model.py",
        "mock_server.py",
        "prompt_scene4.txt",
        "requirements-gpu.txt",
        "requirements-service.txt",
        "requirements-test.txt",
        "runtime.py",
        "schemas.py",
        "verify_assets.py"
    ) | ForEach-Object { Join-Path $serviceDir $_ }

    $scpArguments = @("-P", [string]$config.SshPort)
    if ($config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
        $scpArguments += @("-i", [string]$config.IdentityFile)
    }
    $scpArguments += $serviceFiles
    $scpArguments += "${target}:$remoteRoot/cloud_vlm_service/"
    & scp @scpArguments
    if ($LASTEXITCODE -ne 0) {
        throw "云端服务代码上传失败"
    }

    $deployFiles = @(
        Get-ChildItem -LiteralPath $deployDir -File |
            Where-Object { $_.Name -ne ".env" } |
            ForEach-Object { $_.FullName }
    )
    $scpArguments = @("-P", [string]$config.SshPort)
    if ($config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
        $scpArguments += @("-i", [string]$config.IdentityFile)
    }
    $scpArguments += $deployFiles
    $scpArguments += "${target}:$remoteRoot/deploy/autodl/"
    & scp @scpArguments
    if ($LASTEXITCODE -ne 0) {
        throw "部署脚本上传失败"
    }
    Invoke-AutoDLSsh -Config $config -RemoteCommand @(
        "chmod", "755", "'$remoteRoot/deploy/autodl/'*.sh"
    )

    $scpArguments = @("-P", [string]$config.SshPort)
    if ($config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
        $scpArguments += @("-i", [string]$config.IdentityFile)
    }
    $scpArguments += @(
        (Join-Path $projectRoot "scripts\test_window_client.py"),
        "${target}:$remoteRoot/scripts/"
    )
    & scp @scpArguments
    if ($LASTEXITCODE -ne 0) {
        throw "测试客户端上传失败"
    }
}

$message = if ($WhatIfPreference) {
    "服务代码上传模拟完成：$remoteRoot"
} else {
    "服务代码已上传到：$remoteRoot"
}
Write-Host $message

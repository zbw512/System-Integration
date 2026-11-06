[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1")
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$config = Import-AutoDLConfig -Path $ConfigPath
$runDir = Get-AutoDLRunDirectory -ScriptsDirectory $PSScriptRoot
$pidFile = Join-Path $runDir "autodl-tunnel.pid"
$stdoutLog = Join-Path $runDir "autodl-tunnel.out.log"
$stderrLog = Join-Path $runDir "autodl-tunnel.err.log"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "找不到 ssh。请安装 Windows OpenSSH Client。"
}

if (Test-Path -LiteralPath $pidFile) {
    $existingPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($existing -and $existing.ProcessName -eq "ssh") {
        Write-Host "SSH 隧道已经在运行，PID=$existingPid"
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force
}

$sshArgs = @(
    "-N",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-L", "$($config.LocalPort):127.0.0.1:$($config.RemoteServicePort)"
)
if ($config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
    Assert-LocalPathFile -Path $config.IdentityFile -Description "SSH 私钥"
    $sshArgs += @("-i", [string]$config.IdentityFile)
}
$sshArgs += @("-p", [string]$config.SshPort)
$sshArgs += "$($config.SshUser)@$($config.SshHostName)"

$quotedArguments = ($sshArgs | ForEach-Object { Quote-NativeArgument $_ }) -join " "
$process = Start-Process `
    -FilePath "ssh" `
    -ArgumentList $quotedArguments `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

$process.Id | Set-Content -LiteralPath $pidFile -Encoding ascii
Start-Sleep -Seconds 2
$process.Refresh()
if ($process.HasExited) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $detail = if (Test-Path -LiteralPath $stderrLog) {
        Get-Content -LiteralPath $stderrLog -Raw
    } else {
        "没有 stderr 日志"
    }
    throw "SSH 隧道启动失败。请检查连接配置或私钥。$detail"
}

Write-Host "SSH 隧道已启动：127.0.0.1:$($config.LocalPort) -> $($config.SshHostName):$($config.RemoteServicePort)，PID=$($process.Id)"

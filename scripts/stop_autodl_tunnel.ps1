[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$runDir = Get-AutoDLRunDirectory -ScriptsDirectory $PSScriptRoot
$pidFile = Join-Path $runDir "autodl-tunnel.pid"
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "没有隧道 PID 文件，隧道未运行。"
    exit 0
}

$tunnelPid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-Process -Id $tunnelPid -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Host "PID $tunnelPid 已不存在，已清理 PID 文件。"
    exit 0
}
if ($process.ProcessName -ne "ssh") {
    throw "PID $tunnelPid 不是 ssh 进程，拒绝停止。请人工检查。"
}

Stop-Process -Id $tunnelPid
$process.WaitForExit(10000) | Out-Null
Remove-Item -LiteralPath $pidFile -Force
Write-Host "SSH 隧道已停止，PID=$tunnelPid"

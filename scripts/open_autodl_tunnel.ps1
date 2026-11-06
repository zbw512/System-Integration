param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1")
)

Write-Warning "open_autodl_tunnel.ps1 已改名为 start_autodl_tunnel.ps1，本入口保留兼容。"
& (Join-Path $PSScriptRoot "start_autodl_tunnel.ps1") -ConfigPath $ConfigPath

Set-StrictMode -Version Latest

function Import-AutoDLConfig {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "AutoDL 配置文件不存在：$Path。请从 scripts\autodl.connection.example.psd1 复制并填写。"
    }
    $config = Import-PowerShellDataFile -LiteralPath $Path
    foreach ($name in @(
        "SshHostName",
        "SshPort",
        "SshUser",
        "RemoteProjectRoot",
        "BaseModelRemotePath",
        "AdapterRemotePath",
        "LocalPort",
        "RemoteServicePort"
    )) {
        if (-not $config.ContainsKey($name) -or "$($config[$name])" -eq "") {
            throw "AutoDL 配置缺少字段：$name"
        }
    }
    if ([int]$config.SshPort -lt 1 -or [int]$config.SshPort -gt 65535) {
        throw "SshPort 必须在 1-65535 之间"
    }
    if ([int]$config.LocalPort -lt 1 -or [int]$config.LocalPort -gt 65535) {
        throw "LocalPort 必须在 1-65535 之间"
    }
    if ([int]$config.RemoteServicePort -lt 1 -or [int]$config.RemoteServicePort -gt 65535) {
        throw "RemoteServicePort 必须在 1-65535 之间"
    }
    return $config
}

function Import-AutoDLSecrets {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "AutoDL 密钥配置不存在：$Path。请从 scripts\autodl.secrets.example.psd1 复制并填写。"
    }
    $secrets = Import-PowerShellDataFile -LiteralPath $Path
    $serviceToken = "$($secrets.ServiceToken)"
    $backendToken = "$($secrets.BackendRemoteToken)"
    if ($serviceToken.Length -lt 32) {
        throw "ServiceToken 至少需要 32 个字符"
    }
    if ($serviceToken -match "[\r\n]") {
        throw "ServiceToken 不能包含换行"
    }
    if ($backendToken -ne $serviceToken) {
        throw "ServiceToken 与 BackendRemoteToken 必须完全一致"
    }
    return $secrets
}

function Get-AutoDLSshArguments {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config
    )

    $arguments = @()
    if ($Config.ContainsKey("IdentityFile") -and "$($Config.IdentityFile)") {
        $arguments += @("-i", [string]$Config.IdentityFile)
    }
    $arguments += @("-p", [string]$Config.SshPort)
    $arguments += "$($Config.SshUser)@$($Config.SshHostName)"
    return $arguments
}

function Invoke-AutoDLSsh {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Config,
        [string[]]$RemoteCommand = @(),
        [switch]$CaptureOutput
    )

    $arguments = Get-AutoDLSshArguments -Config $Config
    if ($RemoteCommand.Count -gt 0) {
        $arguments += ($RemoteCommand -join " ")
    }
    if ($CaptureOutput) {
        $output = & ssh @arguments 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "SSH 命令失败：$($output -join [Environment]::NewLine)"
        }
        return ($output -join "`n")
    }

    & ssh @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "SSH 命令失败，退出码 $LASTEXITCODE"
    }
}

function Get-AutoDLRunDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptsDirectory
    )
    $projectRoot = Split-Path -Parent $ScriptsDirectory
    $runDir = Join-Path $projectRoot ".run"
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    return $runDir
}

function Assert-LocalPathFile {
    param([string]$Path, [string]$Description)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description 不存在：$Path"
    }
}

function Quote-NativeArgument {
    param([string]$Value)
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

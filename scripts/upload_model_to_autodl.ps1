[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "autodl.connection.psd1"),
    [string]$BaseModelPath = "",
    [string]$AdapterPath = "",
    [string]$RemoteModelRoot = "",
    [int]$ChunkSizeMB = 256,
    [switch]$ForceReupload
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")

$config = Import-AutoDLConfig -Path $ConfigPath
if (-not $WhatIfPreference -and $config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
    Assert-LocalPathFile -Path $config.IdentityFile -Description "SSH 私钥"
}
if (-not $BaseModelPath) { $BaseModelPath = $config.LocalBaseModelPath }
if (-not $AdapterPath) { $AdapterPath = $config.LocalAdapterPath }
if (-not $BaseModelPath) {
    throw "独立部署必须在 connection 配置中填写 LocalBaseModelPath，或通过 -BaseModelPath 指定"
}
if (-not $AdapterPath) {
    throw "独立部署必须在 connection 配置中填写 LocalAdapterPath，或通过 -AdapterPath 指定"
}
$remoteBase = if ($RemoteModelRoot) {
    "$($RemoteModelRoot.TrimEnd('/'))/$(Split-Path -Leaf $BaseModelPath)"
} else {
    [string]$config.BaseModelRemotePath
}
$remoteAdapter = if ($RemoteModelRoot) {
    "$($RemoteModelRoot.TrimEnd('/'))/$(Split-Path -Leaf $AdapterPath)"
} else {
    [string]$config.AdapterRemotePath
}

if ($remoteBase -notmatch "^/[A-Za-z0-9._/-]+$" -or $remoteAdapter -notmatch "^/[A-Za-z0-9._/-]+$") {
    throw "远端模型路径只能包含安全 ASCII 路径字符"
}

Assert-LocalPathFile -Path (Join-Path $BaseModelPath "config.json") -Description "基座 config.json"
$indexPath = Join-Path $BaseModelPath "model.safetensors.index.json"
Assert-LocalPathFile -Path $indexPath -Description "基座权重索引"
$index = Get-Content -LiteralPath $indexPath -Raw | ConvertFrom-Json
$shards = @($index.weight_map.PSObject.Properties | ForEach-Object { $_.Value } | Sort-Object -Unique)
if ($shards.Count -eq 0) {
    throw "基座权重索引没有分片"
}
foreach ($shard in $shards) {
    Assert-LocalPathFile -Path (Join-Path $BaseModelPath $shard) -Description "基座分片 $shard"
}

$requiredBaseFiles = @(
    "configuration_minicpm.py",
    "image_processing_minicpmv.py",
    "modeling_minicpmv.py",
    "modeling_navit_siglip.py",
    "preprocessor_config.json",
    "processing_minicpmv.py",
    "resampler.py",
    "tokenizer.json",
    "tokenizer_config.json"
)
foreach ($name in $requiredBaseFiles) {
    Assert-LocalPathFile -Path (Join-Path $BaseModelPath $name) -Description "基座文件 $name"
}

$adapterConfig = Join-Path $AdapterPath "adapter_config.json"
$adapterWeights = Join-Path $AdapterPath "adapter_model.safetensors"
Assert-LocalPathFile -Path $adapterConfig -Description "LoRA adapter_config.json"
Assert-LocalPathFile -Path $adapterWeights -Description "LoRA 权重"

if (-not $WhatIfPreference) {
    Invoke-AutoDLSsh -Config $config -RemoteCommand @(
        "mkdir", "-p", "'$remoteBase'", "'$remoteAdapter'"
    )
}

function Get-RemoteFileSize {
    param([string]$RemotePath)
    $command = "if [ -f '$RemotePath' ]; then stat -c %s '$RemotePath'; else echo -1; fi"
    $value = Invoke-AutoDLSsh -Config $config -CaptureOutput -RemoteCommand @($command)
    return [int64]($value.Trim())
}

$rsyncCommand = Get-Command rsync -ErrorAction SilentlyContinue
$rsyncExe = if ($rsyncCommand) { $rsyncCommand.Source } else { $null }
if (-not $rsyncCommand) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $candidate = Join-Path (Split-Path -Parent (Split-Path -Parent $git.Source)) "usr\bin\rsync.exe"
        if (Test-Path -LiteralPath $candidate) {
            $rsyncExe = $candidate
        }
    }
}

$remoteHasRsync = $false
if (-not $WhatIfPreference) {
    try {
        $probe = Invoke-AutoDLSsh -Config $config -CaptureOutput -RemoteCommand @(
            "command", "-v", "rsync", ">/dev/null", "&&", "echo", "yes", "||", "echo", "no"
        )
        $remoteHasRsync = $probe.Trim() -eq "yes"
    } catch {
        $remoteHasRsync = $false
    }
}

$useRsync = ($null -ne $rsyncExe -and $remoteHasRsync)
if ($useRsync) {
    Write-Host "上传方式：rsync --partial --append-verify（支持断点续传）"
} else {
    Write-Host "上传方式：无 rsync；小文件 scp，大文件使用 $ChunkSizeMB MiB 分块续传。"
}

$sshRshParts = @("ssh", "-p", [string]$config.SshPort)
if ($config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
    $sshRshParts += @("-i", [string]$config.IdentityFile)
}
$sshRsh = $sshRshParts -join " "
$target = "$($config.SshUser)@$($config.SshHostName)"

function Send-ScpFile {
    param([string]$LocalPath, [string]$RemotePath)
    $scpArguments = @("-P", [string]$config.SshPort)
    if ($config.ContainsKey("IdentityFile") -and "$($config.IdentityFile)") {
        $scpArguments += @("-i", [string]$config.IdentityFile)
    }
    $scpArguments += @($LocalPath, "${target}:$RemotePath")
    & scp @scpArguments
    return $LASTEXITCODE
}

function Send-ChunkedModelFile {
    param(
        [string]$LocalPath,
        [string]$RemotePath,
        [string]$RemoteDirectory
    )

    $name = Split-Path -Leaf $LocalPath
    $localSize = (Get-Item -LiteralPath $LocalPath).Length
    $chunkSize = [int64]$ChunkSizeMB * 1MB
    if ($chunkSize -le 0) {
        throw "ChunkSizeMB 必须为正整数"
    }
    $chunkCount = [int][Math]::Ceiling($localSize / [double]$chunkSize)
    $projectRoot = Split-Path -Parent $PSScriptRoot
    $localTempDirectory = Join-Path $projectRoot "work\upload-chunks"
    New-Item -ItemType Directory -Path $localTempDirectory -Force | Out-Null
    $remoteChunkDirectory = "$RemoteDirectory/.codex-upload-$name"
    Invoke-AutoDLSsh -Config $config -RemoteCommand @(
        "mkdir", "-p", "'$remoteChunkDirectory'"
    )

    $source = [System.IO.File]::OpenRead($LocalPath)
    try {
        for ($index = 0; $index -lt $chunkCount; $index++) {
            $offset = [int64]$index * $chunkSize
            $length = [Math]::Min($chunkSize, $localSize - $offset)
            $chunkName = "{0:D6}.part" -f $index
            $localChunk = Join-Path $localTempDirectory "$name.$chunkName"
            $remoteChunk = "$remoteChunkDirectory/$chunkName"

            $remoteChunkSize = Get-RemoteFileSize -RemotePath $remoteChunk
            if (-not $ForceReupload -and $remoteChunkSize -eq $length) {
                Write-Host "  分块 $($index + 1)/$chunkCount 已完成，跳过"
                continue
            }

            if (Test-Path -LiteralPath $localChunk) {
                Remove-Item -LiteralPath $localChunk -Force
            }
            $source.Position = $offset
            $targetStream = [System.IO.File]::Create($localChunk)
            try {
                $remaining = $length
                $buffer = New-Object byte[] (1MB)
                while ($remaining -gt 0) {
                    $readSize = [int][Math]::Min($buffer.Length, $remaining)
                    $read = $source.Read($buffer, 0, $readSize)
                    if ($read -le 0) {
                        throw "本地文件提前结束：$LocalPath"
                    }
                    $targetStream.Write($buffer, 0, $read)
                    $remaining -= $read
                }
            } finally {
                $targetStream.Dispose()
            }

            Write-Host "  上传分块 $($index + 1)/$chunkCount：$name"
            $exitCode = Send-ScpFile -LocalPath $localChunk -RemotePath $remoteChunk
            if ($exitCode -ne 0) {
                throw "分块上传失败：$name 第 $($index + 1) 块。已完成分块会在重试时跳过。"
            }
            Remove-Item -LiteralPath $localChunk -Force
        }
    } finally {
        $source.Dispose()
    }

    $assembleCommand = (
        "set -e; cat '$remoteChunkDirectory/'*.part > '$RemotePath.part'; " +
        "mv -f '$RemotePath.part' '$RemotePath'; " +
        "test `"`$(stat -c %s '$RemotePath')`" -eq $localSize; " +
        "find '$remoteChunkDirectory' -type f -delete; rmdir '$remoteChunkDirectory'"
    )
    Invoke-AutoDLSsh -Config $config -RemoteCommand @($assembleCommand)
    Remove-Item -LiteralPath $localTempDirectory -Force -ErrorAction SilentlyContinue
}

function Send-ModelFile {
    param(
        [string]$LocalPath,
        [string]$RemoteDirectory
    )

    $name = Split-Path -Leaf $LocalPath
    $remotePath = "$RemoteDirectory/$name"
    $localSize = (Get-Item -LiteralPath $LocalPath).Length
    $remoteSize = Get-RemoteFileSize -RemotePath $remotePath
    if (-not $ForceReupload -and $remoteSize -eq $localSize) {
        Write-Host "跳过已完成：$remotePath ($localSize bytes)"
        return
    }

    Write-Host "上传 $LocalPath -> ${target}:$remotePath ($localSize bytes)"
    if ($useRsync) {
        & $rsyncExe -az --partial --append-verify --info=progress2 `
            --rsh $sshRsh `
            $LocalPath "${target}:$remotePath"
    } elseif ($localSize -gt ([int64]$ChunkSizeMB * 1MB)) {
        Write-Host "  无 rsync，使用分块续传。"
        Send-ChunkedModelFile `
            -LocalPath $LocalPath `
            -RemotePath $remotePath `
            -RemoteDirectory $RemoteDirectory
        if ($LASTEXITCODE -ne 0) {
            throw "上传失败：$LocalPath"
        }
        return
    } else {
        $exitCode = Send-ScpFile -LocalPath $LocalPath -RemotePath $remotePath
        if ($exitCode -ne 0) {
            throw "上传失败：$LocalPath。已完成的其它文件会在下次运行时跳过。"
        }
        return
    }
    if ($LASTEXITCODE -ne 0) {
        throw "上传失败：$LocalPath。已完成的其它文件会在下次运行时跳过。"
    }
}

$allModelFiles = @(
    Get-ChildItem -LiteralPath $BaseModelPath -File |
        Sort-Object Name |
        ForEach-Object { $_.FullName }
)
foreach ($file in $allModelFiles) {
    if ($PSCmdlet.ShouldProcess("${target}:$remoteBase", "上传 $(Split-Path -Leaf $file)")) {
        Send-ModelFile -LocalPath $file -RemoteDirectory $remoteBase
    }
}

foreach ($file in @($adapterConfig, $adapterWeights)) {
    if ($PSCmdlet.ShouldProcess("${target}:$remoteAdapter", "上传 $(Split-Path -Leaf $file)")) {
        Send-ModelFile -LocalPath $file -RemoteDirectory $remoteAdapter
    }
}

if (-not $WhatIfPreference) {
    foreach ($file in $allModelFiles) {
        $name = Split-Path -Leaf $file
        $localSize = (Get-Item -LiteralPath $file).Length
        $remoteSize = Get-RemoteFileSize -RemotePath "$remoteBase/$name"
        if ($remoteSize -ne $localSize) {
            throw "远端校验失败：$name 期望 $localSize，实际 $remoteSize"
        }
    }
    foreach ($file in @($adapterConfig, $adapterWeights)) {
        $name = Split-Path -Leaf $file
        $localSize = (Get-Item -LiteralPath $file).Length
        $remoteSize = Get-RemoteFileSize -RemotePath "$remoteAdapter/$name"
        if ($remoteSize -ne $localSize) {
            throw "远端 LoRA 校验失败：$name 期望 $localSize，实际 $remoteSize"
        }
    }
}

$completionMessage = if ($WhatIfPreference) {
    "模型上传模拟完成（没有连接或上传）："
} else {
    "模型上传和远端大小校验完成："
}
Write-Host $completionMessage
Write-Host "  基座：$remoteBase"
Write-Host "  LoRA：$remoteAdapter"

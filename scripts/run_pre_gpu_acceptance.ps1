[CmdletBinding()]
param(
    [string]$ValueCsv = "E:\dachuang\SAV\exports\val_scene4_v1.csv",
    [string]$ValidationVideoDir = "E:\dachuang\SAV\dataset"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "AutoDL.Common.ps1")
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPython = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$cloudTestVenv = Join-Path $projectRoot "work\cloud-vlm-test-venv"
$cloudTestPython = Join-Path $cloudTestVenv "Scripts\python.exe"
$previousConsoleOutputEncoding = [Console]::OutputEncoding
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousPythonUtf8 = $env:PYTHONUTF8

try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    Assert-LocalPathFile -Path $backendPython -Description "后端虚拟环境"

Write-Host "== 1. 云端服务无 GPU 测试环境 =="
if (-not (Test-Path -LiteralPath $cloudTestPython)) {
    & python -m venv $cloudTestVenv
    if ($LASTEXITCODE -ne 0) { throw "创建云端测试虚拟环境失败" }
}
& $cloudTestPython -m pip install --disable-pip-version-check `
    -r (Join-Path $projectRoot "cloud_vlm_service\requirements-test.txt")
if ($LASTEXITCODE -ne 0) { throw "安装云端测试依赖失败" }

Write-Host "== 2. 云端 HTTP 服务测试 =="
Push-Location $projectRoot
try {
    & $cloudTestPython -m pytest cloud_vlm_service\tests -q
    if ($LASTEXITCODE -ne 0) { throw "云端 HTTP 服务测试失败" }
} finally {
    Pop-Location
}

Write-Host "== 3. Flask 全量回归、远程适配器和 Mock AutoDL 测试 =="
Push-Location (Join-Path $projectRoot "backend")
try {
    & $backendPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "后端测试失败" }
} finally {
    Pop-Location
}

Write-Host "== 4. 前端 API 契约测试 =="
Push-Location (Join-Path $projectRoot "frontend")
try {
    & npm test
    if ($LASTEXITCODE -ne 0) { throw "前端测试失败" }

    Write-Host "== 5. 前端类型检查和构建 =="
    & npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "前端类型检查失败" }
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
} finally {
    Pop-Location
}

Write-Host "== 6. 确定性重建 850 条验证 JSONL =="
$validationJsonl = Join-Path $projectRoot "work\minicpmv45_scene4_val_v1.jsonl"
& $backendPython (Join-Path $PSScriptRoot "build_scene4_val_jsonl.py") `
    --csv $ValueCsv `
    --video-dir $ValidationVideoDir `
    --output $validationJsonl `
    --expected-count 850
if ($LASTEXITCODE -ne 0) {
    throw "验证集 JSONL 重建失败"
}

Write-Host "== 7. PowerShell 和 Shell 脚本语法 =="
$parseFailures = @()
Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*.ps1" | ForEach-Object {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    if ($errors.Count -gt 0) {
        $parseFailures += $errors
    }
}
if ($parseFailures.Count -gt 0) {
    throw "PowerShell 脚本语法错误：$($parseFailures -join '; ')"
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $gitBash = Join-Path (Split-Path -Parent (Split-Path -Parent $git.Source)) "bin\bash.exe"
    if (Test-Path -LiteralPath $gitBash) {
        Get-ChildItem -LiteralPath (Join-Path $projectRoot "deploy\autodl") -Filter "*.sh" |
            ForEach-Object {
                & $gitBash -n ($_.FullName -replace "\\", "/")
                if ($LASTEXITCODE -ne 0) {
                    throw "Shell 脚本语法错误：$($_.FullName)"
                }
            }
    }
}

    Write-Host "无 GPU 全部验收通过。"
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

# 每日签到（给 Windows 计划任务用）：自动挑选可用 Python，静默跑 CLI，输出写 logs\checkin_console.log
$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$LogDir = Join-Path $Root 'logs'
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir 'checkin_console.log'

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value "`r`n=== $stamp 开始 -> $Root ==="

$runners = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $runners += @{ Exe = 'py'; Prefix = @('-3') } }
if (Get-Command python -ErrorAction SilentlyContinue) { $runners += @{ Exe = 'python'; Prefix = @() } }
if (Get-Command pythonw -ErrorAction SilentlyContinue) { $runners += @{ Exe = 'pythonw'; Prefix = @() } }

if (-not $runners) {
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value '没有找到 Python，无法执行签到'
    exit 1
}

$runner = $runners[0]
$args = @() + $runner.Prefix + @('run.py', 'run')
$out = & $runner.Exe @args 2>&1 | Out-String
Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value $out

$code = $LASTEXITCODE
Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value "=== 退出码 $code ==="
exit $code

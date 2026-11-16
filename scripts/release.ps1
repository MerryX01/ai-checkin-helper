# 一键构建 + 打标签（推送前会要求你确认）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\release.ps1 -Version 2.2.1
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "版本号必须是 x.y.z，例如 2.2.1"
}

# 同步 VERSION 与 pyproject.toml
& python -c @"
from pathlib import Path
import re
v = "$Version"
p = Path('signin/__init__.py')
t = p.read_text(encoding='utf-8')
p.write_text(re.sub(r'VERSION = "[^"]*"', f'VERSION = "{v}"', t, count=1), encoding='utf-8')
p = Path('pyproject.toml')
t = p.read_text(encoding='utf-8')
p.write_text(re.sub(r'version = "[^"]*"', f'version = "{v}"', t, count=1), encoding='utf-8')
"@

& python -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw "测试失败，停止发布" }
& python -m compileall -q signin run.py gui_app.py app_main.py
if ($LASTEXITCODE -ne 0) { throw "编译失败，停止发布" }

Get-Process -Name "签到助手" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
& python -m PyInstaller --noconfirm --clean --onefile --windowed --name "签到助手" app_main.py
if ($LASTEXITCODE -ne 0) { throw "exe 构建失败" }

git add -A
git commit -m "release v$Version"
git tag "v$Version"

Write-Host ""
Write-Host "已构建 dist\签到助手.exe，并创建提交和标签 v$Version"
if ($Push) {
    git push origin HEAD
    git push origin "v$Version"
    Write-Host "已推送；GitHub Actions 会自动构建并创建 Release。"
} else {
    Write-Host "未推送。确认无误后执行：git push origin HEAD; git push origin v$Version"
}

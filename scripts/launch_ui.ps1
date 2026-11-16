# 打开图形界面：自动挑选带 tkinter 的 Python，失败时弹窗提示（不再"双击没反应"）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\launch_ui.ps1
$ErrorActionPreference = 'Continue'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$LogDir = Join-Path $Root 'logs'
if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir 'ui_launch.log'

function Write-LaunchLog([string]$Text) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value "$stamp $Text"
}

function Test-Interpreter([string]$Exe, [string[]]$Prefix) {
    # 用临时脚本文件探测：Start-Process -ArgumentList 不自动加引号，把 "-c 代码" 拆成两个参数会误判"没有 tkinter"
    $probe = Join-Path $env:TEMP ('signin_probe_' + [guid]::NewGuid().ToString('N') + '.py')
    $code = "import tkinter`r`ntkinter.Tcl()`r`n"
    [IO.File]::WriteAllText($probe, $code, (New-Object Text.UTF8Encoding($false)))
    try {
        # 用 Start-Process -Wait 而不是 &：pythonw 是 GUI 子系统，& 不会等它跑完，退出码读不准
        # 临时文件路径不含空格，所以 -ArgumentList 拼参数不会被拆坏
        $proc = Start-Process -FilePath $Exe -ArgumentList (@() + $Prefix + @($probe)) `
            -WindowStyle Hidden -PassThru -Wait
        $exit = $proc.ExitCode
    } catch {
        $exit = -1
    } finally {
        if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Force }
    }
    return ($exit -eq 0)
}

Write-LaunchLog "准备启动界面（工程目录：$Root）"

$candidates = @()
if (Get-Command pyw -ErrorAction SilentlyContinue) {
    $candidates += @{ Launch = 'pyw'; Prefix = @('-3') }
}
$python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\pythonw.exe'
if (Test-Path -LiteralPath $python312) {
    $candidates += @{ Launch = $python312; Prefix = @() }
}
if (Get-Command pythonw -ErrorAction SilentlyContinue) {
    $candidates += @{ Launch = 'pythonw'; Prefix = @() }
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidates += @{ Launch = 'py'; Prefix = @('-3') }
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    $candidates += @{ Launch = 'python'; Prefix = @() }
}

$launched = $false
foreach ($item in $candidates) {
    $exe = $item.Launch
    $prefix = $item.Prefix
    if (Test-Interpreter -Exe $exe -Prefix $prefix) {
        try {
            $args = @() + $prefix + @('gui_app.py')
            $proc = Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $Root -PassThru
            Write-LaunchLog "已启动：$exe $($args -join ' ')（PID $($proc.Id)）"
            $launched = $true
            break
        } catch {
            Write-LaunchLog "启动失败：$exe -> $($_.Exception.Message)"
        }
    } else {
        Write-LaunchLog "跳过：$exe 没有可用的 tkinter"
    }
}

if (-not $launched) {
    Write-LaunchLog '没有找到带 tkinter 的 Python，界面无法启动'
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $msg = "没有找到带 tkinter 的 Python，界面无法启动。`r`n`r`n" +
               "请安装 Python 3（勾选 tcl/tk），或用下面命令在终端里看具体报错：`r`n" +
               "  py -3 gui_app.py`r`n`r`n详细信息：" + $LogFile + "`r`n" +
               "命令行仍然可用：python run.py run"
        [System.Windows.Forms.MessageBox]::Show($msg, '每日自动签到 · 启动失败', 0, 'Error') | Out-Null
    } catch {
        Write-Host "界面启动失败，详情见 $LogFile"
    }
    exit 1
}

exit 0

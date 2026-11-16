# 注册 / 删除 Windows 每日签到定时任务
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time 09:05
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Remove
param(
    [string]$Time = '10:10',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = 'SignInDailyCheckin'
$Root = Split-Path -Parent $PSScriptRoot
$Vbs = Join-Path $PSScriptRoot 'run_hidden.vbs'

if ($Remove) {
    & schtasks.exe /Delete /TN $TaskName /F 2>&1 | Out-String | Write-Output
    Write-Output "已尝试删除任务：$TaskName"
    exit $LASTEXITCODE
}

if ($Time -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    Write-Output "时间格式不对：$Time（应为 HH:MM，如 09:05）"
    exit 2
}

if (-not (Test-Path -LiteralPath $Vbs)) {
    Write-Output "缺少启动脚本：$Vbs"
    exit 2
}

# /F 保证重复执行是幂等的（同名任务直接覆盖）
$Action = 'wscript.exe "' + $Vbs + '"'
Write-Output "注册任务：$TaskName  每天 $Time  动作：$Action"

& schtasks.exe /Create /TN $TaskName /TR $Action /SC DAILY /ST $Time /F
$code = $LASTEXITCODE
if ($code -eq 0) {
    Write-Output '注册成功。可执行以下命令确认：'
    Write-Output ('  schtasks /Query /TN ' + $TaskName + ' /V /FO LIST')
} else {
    Write-Output "注册失败，退出码 $code"
}
exit $code

' Silently runs the daily check-in (no console window).
' Logs: logs\checkin_console.log (stdout) + logs\checkin.log (structured).
Option Explicit
Dim fso, shell, scriptDir

Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set shell = CreateObject("WScript.Shell")
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptDir & "\run_daily.ps1""", 0, False

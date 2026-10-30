@echo off
setlocal
chcp 65001 >nul
set "RECORD_ARCHIVE_UNINSTALL_ROOT=%~dp0"
set "RECORD_ARCHIVE_UNINSTALL_SCRIPT=%~dp0_internal\distribution\uninstall_entry.ps1"
if not exist "%RECORD_ARCHIVE_UNINSTALL_SCRIPT%" (
    echo 请先完整解压 ZIP，再运行卸载记录归档.cmd。
    if not defined RECORD_ARCHIVE_NO_PAUSE pause
    exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $env:PSModulePath=Join-Path $PSHOME 'Modules'; try { & ([ScriptBlock]::Create([IO.File]::ReadAllText($env:RECORD_ARCHIVE_UNINSTALL_SCRIPT))) -AppRoot $env:RECORD_ARCHIVE_UNINSTALL_ROOT } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
set "recordArchiveExit=%errorlevel%"
if not defined RECORD_ARCHIVE_NO_PAUSE pause
exit /b %recordArchiveExit%

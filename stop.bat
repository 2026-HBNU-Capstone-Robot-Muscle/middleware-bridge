@echo off
setlocal DisableDelayedExpansion
set "SCRIPT=%~dp0scripts\windows\stop_gui_dryrun.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RC=%ERRORLEVEL%"
echo(
pause
exit /b %RC%

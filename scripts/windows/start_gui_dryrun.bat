@echo off
setlocal DisableDelayedExpansion
set "SCRIPT=%~dp0start_gui_dryrun.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo(
  echo GUI dry-run startup failed. Check the error above and logs\gui-dryrun.
  echo Exit code: %RC%
  echo(
  pause
  exit /b %RC%
)
echo(
pause
exit /b 0

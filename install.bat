@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\install_environment.ps1"
set "INSTALL_EXIT=%ERRORLEVEL%"

if not "%INSTALL_EXIT%"=="0" echo Setup failed. Review the PowerShell output and docs\ros2_install_guideline.md.
if "%INSTALL_EXIT%"=="0" echo Setup completed. Run start.bat to launch the GUI.

echo.
pause
exit /b %INSTALL_EXIT%
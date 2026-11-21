@echo off
setlocal
cd /d "%~dp0"
for /f "tokens=2 delims=:" %%a in ('chcp') do set "ORIGINAL_CODEPAGE=%%a"
chcp 65001 >nul

echo Estimated additional disk space: approximately 15-25 GB.
echo Estimated downloads: approximately 5-10 GB; existing installed tools may reduce this.
echo Actual size depends on Windows components, Pixi packages, and cached downloads.
echo.
choice /C YN /M "Install the required environment now"
if errorlevel 2 goto declined

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install_environment.ps1"
set "INSTALL_EXIT=%ERRORLEVEL%"

if not "%INSTALL_EXIT%"=="0" echo Setup failed. Review the PowerShell output and docs\ros2_install_guideline.md.
if "%INSTALL_EXIT%"=="0" echo Setup completed. Run start.bat to launch the GUI.

echo.
pause
if defined ORIGINAL_CODEPAGE chcp %ORIGINAL_CODEPAGE% >nul
exit /b %INSTALL_EXIT%

:declined
echo Installation cancelled. No setup commands were run.
if defined ORIGINAL_CODEPAGE chcp %ORIGINAL_CODEPAGE% >nul
exit /b 0

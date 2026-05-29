@echo off
REM Double-click to install Lamp on Windows (runs install.ps1).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
  echo.
  echo Install failed. See messages above.
  pause
  exit /b 1
)
pause

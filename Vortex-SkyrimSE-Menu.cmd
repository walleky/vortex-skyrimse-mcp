@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0vortex_skyrimse_menu.ps1" %*
if errorlevel 1 (
  echo.
  echo Vortex Skyrim SE Helper Menu failed. Read the message above.
)
echo.
pause

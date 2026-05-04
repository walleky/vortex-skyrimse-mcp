@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mcp_doctor.ps1" -OpenConfigFolder %*
echo.
pause

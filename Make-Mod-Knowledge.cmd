@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_mod_knowledge.ps1" %*
if errorlevel 1 (
  echo.
  echo Mod knowledge report failed. Read the message above.
)
echo.
pause

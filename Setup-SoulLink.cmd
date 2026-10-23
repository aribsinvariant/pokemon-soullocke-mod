@echo off
setlocal
title Emerald Soul Link Setup
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0soullink\setup\windows.ps1" %*
set "setup_result=%errorlevel%"
if not "%setup_result%"=="0" echo Setup failed. See the error and setup log shown above, then run this file again.
pause
exit /b %setup_result%

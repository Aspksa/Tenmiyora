@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title Tenmiyora
set "TENMIYORA_ROOT=%~dp0"
set "TENMIYORA_MODE=%~1"
set "TENMIYORA_OPTION=%~2"
set "TENMIYORA_EXTRA=%~3"
set "TENMIYORA_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%TENMIYORA_PS%" goto no_powershell
if not exist "%TENMIYORA_ROOT%bootstrap\host.ps1" goto missing_launcher
if "%TENMIYORA_ATTACHED%"=="1" goto attached
start "Tenmiyora" "%TENMIYORA_PS%" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%TENMIYORA_ROOT%bootstrap\host.ps1"
exit /b %ERRORLEVEL%
:attached
"%TENMIYORA_PS%" -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%TENMIYORA_ROOT%bootstrap\host.ps1"
exit /b %ERRORLEVEL%
:no_powershell
echo [ERROR] Windows PowerShell 5.1 is required.
pause
exit /b 1
:missing_launcher
echo [ERROR] bootstrap\host.ps1 is missing. Extract the entire project first.
pause
exit /b 1

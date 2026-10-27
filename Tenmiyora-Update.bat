@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title Tenmiyora Update
set "TENMIYORA_ROOT=%~dp0"
set "TENMIYORA_PACKAGE=%~1"
if not defined TENMIYORA_PACKAGE (
  echo Enter full path to the verified staged update directory:
  set /p "TENMIYORA_PACKAGE=> "
)
if not defined TENMIYORA_PACKAGE (
  echo [ERROR] No update directory provided.
  pause
  exit /b 1
)
if not exist "%TENMIYORA_PACKAGE%\manifest.json" (
  echo [ERROR] Missing manifest.json in the selected directory.
  pause
  exit /b 1
)
echo This process will stop and restart Tenmiyora.
echo Only bootstrap, web and Tenmiyora.bat are allowed to change.
choice /C YN /M "Approve installing this staged update?"
if errorlevel 2 exit /b 1
set "TENMIYORA_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%TENMIYORA_PS%" (
  echo [ERROR] Windows PowerShell 5.1 unavailable.
  pause
  exit /b 1
)
"%TENMIYORA_PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%TENMIYORA_ROOT%bootstrap\update-project.ps1" -Package "%TENMIYORA_PACKAGE%" -Approve
set "TENMIYORA_EXIT=%ERRORLEVEL%"
if not "%TENMIYORA_EXIT%"=="0" pause
exit /b %TENMIYORA_EXIT%

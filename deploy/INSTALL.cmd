@echo off
rem SOC Handover Platform - offline installer launcher.
rem Double-click this file. It asks for administrator permission, then runs setup\setup.ps1.
rem Options (optional): INSTALL.cmd -InstallDir D:\SOC-Handover -AppPort 8090   /   INSTALL.cmd -Manual
setlocal
cd /d "%~dp0"
title SOC Handover - Setup

rem -Manual (no services) can run without administrator permission
echo %* | find /i "-Manual" >nul
if not errorlevel 1 goto run

fltmc >nul 2>&1
if errorlevel 1 (
  echo Requesting administrator permission...
  if "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  )
  exit /b
)

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\setup.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%

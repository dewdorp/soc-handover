@echo off
rem SOC Handover Platform - patch launcher (app only).
rem Double-click this file. It asks for administrator permission, then runs setup\update.ps1.
rem Options (optional): UPDATE.cmd -InstallDir D:\SOC-Handover
setlocal
cd /d "%~dp0"
title SOC Handover - Patch

rem Administrator permission is requested by update.ps1 only when the install runs as a service.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\update.ps1" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%

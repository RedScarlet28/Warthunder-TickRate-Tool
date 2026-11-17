@echo off
rem Double-click on EITHER PC when the session is over.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0stop_shooting.ps1"

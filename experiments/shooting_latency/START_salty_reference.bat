@echo off
rem Double-click on SALTY'S PC. Starts the reference clock + all recorders.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_shooting.ps1" -Role reference

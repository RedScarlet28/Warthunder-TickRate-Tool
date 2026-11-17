@echo off
rem Double-click on YOUR PC. Pairs to Salty's PC (192.168.1.225) + starts all recorders.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_shooting.ps1" -Role client

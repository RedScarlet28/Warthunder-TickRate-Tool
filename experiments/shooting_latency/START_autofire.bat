@echo off
rem Auto-fire for PRIVATE custom battles only. Bind your machine gun to K in War Thunder first.
rem Start the recorders (START_..._.bat) before this.
rem Ctrl+Shift+F8 = start/pause firing, Ctrl+Shift+F9 = quit.
cd /d "%~dp0"
python "%~dp0auto_fire.py" --key k
pause

@echo off
rem Keep one bot running forever: restarts it 60s after any exit or crash.
rem Usage: run_forever.bat EURUSD
cd /d "%~dp0"
title fxbot %1
:loop
echo [%date% %time%] starting run_live.py --pair %1
"%~dp0venv\Scripts\python.exe" run_live.py --pair %1
if %errorlevel%==2 (
    echo Another bot is already running for %1 - not starting a duplicate.
    pause
    exit /b 2
)
echo [%date% %time%] bot exited with code %errorlevel% - restarting in 60s (close this window to stop)
timeout /t 60 /nobreak >nul
goto loop

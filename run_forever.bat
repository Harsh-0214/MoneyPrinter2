@echo off
rem Keep one bot running forever: restarts it 60s after any exit or crash.
rem Usage: run_forever.bat EURUSD            (main strategy)
rem        run_forever.bat EURUSD pullback   (extra strategy "sleeve")
cd /d "%~dp0"
set SLEEVEARG=
if not "%2"=="" set SLEEVEARG=--sleeve %2
title fxbot %1 %2
:loop
echo [%date% %time%] starting run_live.py --pair %1 %SLEEVEARG%
"%~dp0venv\Scripts\python.exe" run_live.py --pair %1 %SLEEVEARG%
if %errorlevel%==2 (
    echo Another bot is already running for %1 %2 - not starting a duplicate.
    pause
    exit /b 2
)
echo [%date% %time%] bot exited with code %errorlevel% - restarting in 60s (close this window to stop)
timeout /t 60 /nobreak >nul
goto loop

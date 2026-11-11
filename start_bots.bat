@echo off
rem Start MetaTrader 5 (if needed) and both bots, each in its own window.
rem Runs automatically at Windows login (Task Scheduler task "MoneyPrinter2 bots").
cd /d "%~dp0"

tasklist /fi "imagename eq terminal64.exe" | find /i "terminal64.exe" >nul
if errorlevel 1 (
    echo Starting MetaTrader 5...
    start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
    rem give MT5 time to log in
    timeout /t 45 /nobreak >nul
)

start "fxbot EURUSD" cmd /k ""%~dp0run_forever.bat" EURUSD"
timeout /t 3 /nobreak >nul
start "fxbot GBPUSD" cmd /k ""%~dp0run_forever.bat" GBPUSD"

@echo off
rem Start MetaTrader 5 (if needed) and one bot per market, each in its own window.
rem Each market bot runs ALL of that market's strategies and trades whichever
rem one has a setup:
rem   EURUSD / GBPUSD : London Sweep + Breakout (5 min) and daily swing pullback (1 h)
rem   XAUUSD          : gold trend 55-day and 20-day (1 h)
rem   USDJPY          : volatility breakout (15 min)
rem Can run automatically at Windows login (Task Scheduler task "MoneyPrinter2 bots").
cd /d "%~dp0"

tasklist /fi "imagename eq terminal64.exe" | find /i "terminal64.exe" >nul
if errorlevel 1 (
    echo Starting MetaTrader 5...
    start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
    rem give MT5 time to log in
    timeout /t 45 /nobreak >nul
)

for %%B in (EURUSD GBPUSD XAUUSD USDJPY) do (
    start "fxbot %%B" cmd /k ""%~dp0run_forever.bat" %%B"
    timeout /t 3 /nobreak >nul
)

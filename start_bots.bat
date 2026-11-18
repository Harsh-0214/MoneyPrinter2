@echo off
rem Start MetaTrader 5 (if needed) and one bot per market, each in its own window.
rem Each market bot runs ALL of that market's strategies and trades whichever
rem one has a setup:
rem   EURUSD / GBPUSD : London Sweep + Breakout (5 min) and daily swing pullback (1 h)
rem   XAUUSD          : gold trend 55-day and 20-day (1 h)
rem   USDJPY          : volatility breakout (15 min)
rem   SPX500          : S&P 500 IBS mean reversion (1 h), demo from Nov 18 2026
rem Can run automatically at Windows login (Task Scheduler task "MoneyPrinter2 bots").
cd /d "%~dp0"

rem Windows' own find/timeout by full path: from Git Bash its Unix find/timeout come first on PATH.
tasklist /fi "imagename eq terminal64.exe" | "%SystemRoot%\System32\find.exe" /i "terminal64.exe" >nul
if errorlevel 1 (
    echo Starting MetaTrader 5...
    start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
    rem give MT5 time to log in
    "%SystemRoot%\System32\timeout.exe" /t 45 /nobreak >nul
)

rem Phone control (Telegram /status /startbots /stopbots /restart); exits at once if already
rem running or if Telegram isn't set up. It keeps running when the bots are stopped.
start "fxbot phone control" /min "%~dp0venv\Scripts\python.exe" "%~dp0telegram_control.py"

for %%B in (EURUSD GBPUSD XAUUSD USDJPY SPX500) do (
    start "fxbot %%B" cmd /k ""%~dp0run_forever.bat" %%B"
    "%SystemRoot%\System32\timeout.exe" /t 3 /nobreak >nul
)

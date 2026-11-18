@echo off
rem Weekly live-vs-backtest check, sent to Telegram (Task Scheduler: "MoneyPrinter2 fidelity", Sat 08:00).
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" run_fidelity.py --days 8 --telegram >> logs\fidelity.log 2>&1

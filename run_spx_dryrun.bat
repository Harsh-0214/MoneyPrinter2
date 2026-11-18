@echo off
rem S&P 500 IBS bot in DRY-RUN mode: logs "would BUY / would close", sends no orders (Nov 18 2026).
rem Not part of start_bots.bat until it is approved for the demo account.
cd /d "%~dp0"
start "fxbot SPX500 (dry run)" cmd /k ""%~dp0venv\Scripts\python.exe" "%~dp0run_live.py" --pair SPX500 --dry-run"

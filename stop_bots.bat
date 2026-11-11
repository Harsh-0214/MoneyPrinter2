@echo off
rem Stop both bots (leaves MetaTrader 5 and any open positions alone).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -ne 'powershell.exe' -and $_.CommandLine -match 'run_forever.bat|run_live.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Bots stopped.

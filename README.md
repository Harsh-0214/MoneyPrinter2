# MoneyPrinter2 — EUR/USD London Breakout Bot

Simulation + live trading bot for EUR/USD via MetaTrader 5 (FOREX.com demo, Canada).
Strategy: Asian range breakout at the London open, 5-minute bars.

---

## Setup from a fresh clone (laptop or Windows VPS)

### 1. Clone the repo
```
git clone https://github.com/Harsh-0214/MoneyPrinter2.git
cd MoneyPrinter2
```

### 2. Install Python 3.10+
Download from python.org — tick **"Add Python to PATH"** during install.

### 3. Create a virtual environment and install dependencies
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Add your MT5 credentials
```
copy .env.example .env
```
Open `.env` and fill in your FOREX.com demo account number, password, server name,
and the path to your MT5 `terminal64.exe`. Never commit `.env` — it is gitignored.

### 5. Verify everything works
```
python -m pytest -q
python run_backtest.py --synthetic
```
The synthetic run uses random-walk data. It should lose a little (roughly the spread).
If it ever profits on random data, there is a bug.

---

## Get real historical data

**Option A — from MetaTrader 5 (recommended):**
Open your FOREX.com demo in the MT5 terminal, leave it running, then:
```
python fetch_mt5_data.py --start 2021-01-01 --end 2025-12-31
```
MT5 timestamps are in broker server time. Set `data.source_tz` in `config.yaml`
(ask your broker or check a candle against a UTC chart — often `Europe/Helsinki`).

**Option B — Dukascopy:**
Download EUR/USD 1-minute bid candles as CSV, save as `data/EURUSD_M1.csv`,
and set `source_tz: UTC` in `config.yaml`.

---

## Run a backtest
```
python run_backtest.py
```
Results go to `results/`: `trades.csv`, `equity.csv`, `equity.png`.

Honest testing — split your data and never tune on the test period:
```
python run_backtest.py --start 2021-01-01 --end 2023-12-31   # in-sample: tune here
python run_backtest.py --start 2024-01-01 --end 2025-12-31   # out-of-sample: look once
```

---

## Run live (demo only — Part 2)
```
python run_live.py
```
The live runner connects to MT5 using credentials from `.env`.
It refuses to run on a live account unless `--allow-live` is explicitly passed
AND a matching flag is set in `config.yaml`.

---

## Project layout
```
config.yaml                   all parameters
.env.example                  template for MT5 credentials (copy to .env)
run_backtest.py               run a backtest
run_live.py                   live/demo runner (Part 2)
fetch_mt5_data.py             download history from MT5
fxbot/data.py                 loading, timezones, resampling
fxbot/brokers/base.py         broker interface (strategy only talks to this)
fxbot/brokers/sim_broker.py   simulator: spread, slippage, gaps, stops
fxbot/brokers/mt5_broker.py   live MT5 broker (Part 2)
fxbot/risk.py                 sizing, daily loss kill switch, news blackout
fxbot/strategies/london_breakout.py
fxbot/backtest.py             runner + metrics
tests/                        unit tests
```

---

## Simulator assumptions (deliberately pessimistic)
- Signals on a bar's close fill at the next bar's open.
- Buys pay the ask (bid + spread); spread widens to 3 pips around NY rollover.
- Stops fill with slippage, or at the open if price gaps through.
- If stop and target are both hit in one bar, the stop counts.

---

## Warning signs to watch for in backtest results
- Profit factor collapses out-of-sample.
- Results flip when a parameter moves slightly (try `min_range` 12 vs 15 vs 18).
- Profit disappears when `spread_pips` goes from 1.0 to 1.5.

# MoneyPrinter2 — EUR/USD London Session Trading Bot

Automated trading bot for EUR/USD via MetaTrader 5 (FOREX.com demo, Canada).
Runs two complementary strategies on the London open using 5-minute bars.

**5-year backtest results (2021–2025, EURUSD):**
| Metric | Value |
|---|---|
| Total return | +8.70% |
| Max drawdown | -5.64% |
| Win rate | 48.8% |
| Profit factor | 1.28 |
| Trades | 203 (~40/year) |

---

## How the bot decides what to trade

Every morning the bot runs two strategies in parallel. Each one evaluates the
current market conditions and scores its own setup quality. The highest-scoring
proposal wins the morning trade slot. Only one trade is taken per session.

### Morning strategies (08:00–11:00 London time)

#### 1. London Sweep — ICT stop hunt reversal (score 100–130)

Looks for price to fake out the Asian range, then immediately reverse.

```
00:00–08:00   Builds Asian range (overnight high and low)
08:00–10:30   Watches for price to spike just past the range boundary
              e.g. Asian high = 1.0520, price taps 1.0525  ← "sweep"
              Then waits for a swing structure to break back through (BOS)
              e.g. price closes below the last swing low before the spike
              → Entry fires immediately on that bar
```

The idea: market makers briefly push price above/below the range to trigger
retail stop losses, then reverse. The bot enters when the reversal is confirmed
by a Break of Structure (BOS).

**Stop loss:** placed just above the sweep extreme (the fake spike high/low).
If price exceeds the sweep extreme, the setup is invalid.

**Take profit:** opposite side of the Asian range. A stop hunt reversal
typically runs all the way back to where it came from.

```
Example short trade:
  Asian high    = 1.0520
  Sweep extreme = 1.0525  (price tapped here, running stops)
  BOS entry     = 1.0510  (price broke back below a swing low)

  Stop loss     = 1.0526  (above sweep extreme + 1 pip buffer)
  Take profit   = 1.0490  (opposite side of range)
  Risk          = 16 pips
  Reward        = 20 pips  → R/R = 1.25 ❌ (below minimum 1.5, skipped)
```

**Scoring bonuses:**
- +20 if SMT divergence confirmed (EUR swept but GBP did NOT — genuine stop hunt)
- +10 if Asian range is tight (< 15 pips — precise levels)
- +5  if Asian range is moderate (15–25 pips)

**Day filter:** skips Monday and Tuesday — historically both are losing days
for this strategy on EURUSD.

---

#### 2. London Breakout — range breakout fallback (score 60–80)

Looks for price to break cleanly through the Asian range and keep going.
Only fires if the Sweep did not form by 10:30.

```
00:00–08:00   Builds same Asian range
08:00–10:30   Silently watches — if price closes beyond range + 0.5 pips,
              notes the direction but does NOT fire yet
10:30         Checks: is price STILL beyond the range?
              Yes → proposes entry now (confirmed breakout)
              No  → skipped (false breakout — price reversed back inside)
10:30–11:00   Entry window
```

The 10:30 delay serves two purposes: it gives the Sweep a full 2.5-hour
window to form first, and it filters false breakouts that reversed.

**Stop loss:** opposite side of the Asian range. A real breakout should
not re-enter the range.

**Take profit:** entry price + (2.0 × risk distance). Fixed 2:1 R/R.

```
Example long trade:
  Asian low     = 1.0490
  Asian high    = 1.0520
  Break at 08:05, price reaches 1.0528
  Still above range at 10:30 → entry confirmed

  Entry         = 1.0528
  Stop loss     = 1.0490  (opposite range wall)
  Risk          = 38 pips
  Take profit   = 1.0528 + (2.0 × 0.0038) = 1.0604
```

**Scoring bonuses:**
- +12 if range < 20 pips (very tight consolidation)
- +7  if range 20–25 pips
- +3  if range 25–30 pips
- +up to 5 based on breakout distance (momentum confirmation)

---

### Why Sweep always beats Breakout

The Sweep's minimum score (100) is always higher than the Breakout's
maximum (~77). Additionally, the Breakout's `propose()` returns nothing
before 10:30, so they cannot compete for the same bar in most cases.

If both somehow propose on the same bar (at exactly 10:30): the Sweep's
score wins. The Breakout only ever fires as a true fallback.

```
Day A: Sweep detects BOS at 09:30 → fires (score 105), Breakout silenced
Day B: No sweep formed by 10:30  → Breakout fires if still valid (score 68)
Day C: Breakout formed at 08:05 but reversed by 10:30 → neither fires
```

---

### Position sizing

Every trade risks exactly 0.5% of account equity, regardless of stop distance:

```
Units = (equity × 0.005) / (stop_distance_in_price × pip_value)
```

A wider stop = smaller position size. The dollar risk per trade is always
the same. A 2% daily loss limit kills all trading for the rest of that day.

---

### What max drawdown means

Max drawdown (max DD) is the largest peak-to-trough drop in account equity
during the backtest. If the account grew to $53,000 then fell to $50,000
before recovering, that is a -5.66% drawdown.

Our -5.64% means the account never dipped more than ~$2,820 below its
recent high at any point across 5 years. For context, most professional
strategies run -10% to -20% max DD.

---

## Setup from a fresh clone

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
Open `.env` and fill in your FOREX.com demo account number, password, server
name, and the path to your MT5 `terminal64.exe`. Never commit `.env` — it is
gitignored.

### 5. Verify everything works
```
python -m pytest -q
python run_backtest.py --synthetic
```
The synthetic run uses random-walk data. It should lose a little (roughly
the spread). If it ever profits on random data, there is a bug.

---

## Get real historical data

**Option A — histdata.com (used for backtesting):**
Download EUR/USD M1 bars, place CSVs in `data/histdata_eurusd/`, then:
```
python combine_histdata.py --symbol EURUSD
python combine_histdata.py --symbol GBPUSD   # needed for SMT filter
```

**Option B — from MetaTrader 5:**
```
python fetch_mt5_data.py --start 2021-01-01 --end 2025-12-31
```

---

## Run a backtest
```
python run_backtest.py
```
Results go to `results/`: `trades.csv`, `equity.csv`, `equity.png`.

Honest testing — never tune on the test period:
```
python run_backtest.py --start 2021-01-01 --end 2023-12-31   # in-sample
python run_backtest.py --start 2024-01-01 --end 2025-12-31   # out-of-sample
```

---

## Run live (demo only)
```
python run_live.py
```
Refuses to run on a live account unless `--allow-live` is explicitly passed
AND `live.allow_live: true` is set in `config.yaml`.

---

## Project layout
```
config.yaml                            all parameters
.env.example                           MT5 credentials template (copy to .env)
run_backtest.py                        backtest runner
run_live.py                            live/demo runner
combine_histdata.py                    merge histdata.com CSV files
fxbot/
  data.py                              loading, timezones, resampling
  backtest.py                          scored-proposal engine + metrics
  risk.py                              position sizing, daily kill switch
  brokers/
    base.py                            broker interface
    sim_broker.py                      simulator (spread, slippage, gaps)
    mt5_broker.py                      live MT5 broker
  strategies/
    proposal.py                        TradeProposal dataclass (score + order)
    london_sweep.py                    ICT stop hunt reversal
    london_breakout.py                 Asian range breakout fallback
    ny_breakout.py                     NY open breakout (tested, not used)
tests/                                 unit tests (27 total)
data/                                  CSV price data (gitignored)
results/                               backtest output (gitignored)
```

---

## Simulator assumptions (deliberately pessimistic)
- Signals on a bar's close fill at the next bar's open.
- Buys pay the ask (bid + spread); spread widens to 3 pips around NY rollover.
- Stops fill with slippage, or at the open if price gaps through.
- If stop and target are both hit in one bar, the stop counts.

---

## Warning signs in backtest results
- Profit factor collapses out-of-sample.
- Results flip when a parameter moves slightly (try `min_range` 20 vs 25 vs 30).
- Profit disappears when `spread_pips` goes from 1.0 to 1.5.

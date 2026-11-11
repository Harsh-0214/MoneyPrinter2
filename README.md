# MoneyPrinter2 — FX + Gold Trading Bot for MetaTrader 5

Automated trading bot for MetaTrader 5 (FOREX.com demo, Canada, CAD account).
Three bots run side by side, one per market:

| Bot | Strategy | Bars | Trades/yr | When it trades |
|---|---|---|---|---|
| **EURUSD** | London Sweep + Breakout, daily trend filter | 5 min | ~27 | 08:00–11:00 London, exits 16:00 |
| **GBPUSD** | same (EURUSD and GBPUSD are each other's SMT check) | 5 min | ~38 | same |
| **XAUUSD** | Daily trend following (55-day breakout, buy-only) | 1 h | ~5 | decides daily, holds for weeks |

**Portfolio backtest, 2021–2025, 1% risk per trade, real spreads:**
**+45.2% (7.8%/yr), max drawdown −11.1%, PF 1.42**.
By year: +11.8 · +11.0 · −0.1 · −1.5 · +19.0. This is a backtest, not a promise;
see the caveats under "Strategy arsenal". A step-by-step guide is in
**`docs/MoneyPrinter2_Guide.pdf`**.

## Honest results (2021–2025): EUR + GBP stack

Validated with `python run_validate.py`. Parameters were chosen on the full
2021–2025 data, so the in-sample/out-of-sample split below is a sanity check,
not a clean blind test.

Current config (Nov 2026): skips **Mondays only**, uses the **daily trend filter**
(trade only in the direction of the 50-day average), and charges each pair its
**real live spread** (EURUSD 1.4 pips, GBPUSD 2.0 pips).

| Period | Pairs | Trades | Return | CAGR | Max DD | PF | Win % |
|---|---|---|---|---|---|---|---|
| 2021–2023 | EUR + GBP | 205 | +11.61% | 3.8%/yr | -4.18% | 1.37 | 50.7 |
| 2024–2025 | EUR + GBP | 124 | +1.99% | 1.0%/yr | -6.31% | 1.11 | 46.8 |
| 2021–2025 | EUR + GBP | 327 | +14.78% | 2.8%/yr | -7.24% | 1.31 | 49.2 |
| 2021–2025 | EURUSD only | 135 | +4.63% | 0.9%/yr | -5.65% | 1.26 | 47.4 |
| 2021–2025 | GBPUSD only | 192 | +10.15% | 2.0%/yr | -4.34% | 1.33 | 50.5 |

**By year (combined):** 2021 +5.8% · 2022 +5.5% · 2023 0.0% · 2024 −2.5% · 2025 +5.5%

Breakout minimum Asian range = **22 pips** (was 25). With the trend filter on,
16 / 18 / 20 / 22 / 24 / 25 / 27 / 30 pips gave +11.2 / +9.0 / +13.0 / **+14.8** /
+14.6 / +14.1 / +10.2 / +7.6% over 5 years. 22 adds ~20% more trades (65/yr,
EURUSD 27/yr). Other ideas for more trades all cost profit: trading Mondays
(+7.1%), a longer breakout window (+12.4–12.7%), a NY-open Sweep (+5–8%), and a
lower Sweep R/R (+9.5%).

### Daily trend filter (higher timeframe)
Same realistic spreads, both pairs, 2021–2025:

| Setup | Return | Max DD | PF |
|---|---|---|---|
| No trend filter | +12.1% | −10.0% | 1.17 |
| Trend filter, 10 / 20-day average | +4.7% / +7.5% | −7.8% / −8.3% | 1.11 / 1.19 |
| **Trend filter, 30–200-day average** | **+10.7% to +14.1%** | **−6.7% to −8.9%** | **1.27–1.36** |
| 1-minute candles instead of 5 | −5.7% to +7.8% | −13% to −17% | 0.95–1.08 |
| 15-minute candles instead of 5 | +9.2% | −5.3% | 1.17 |

The 50-day setting sits in a wide plateau (30–200 all work), so it isn't a
lucky pick. The filter cuts trades by ~40% (EURUSD ≈ 21/yr) but roughly doubles
the profit per trade. Only buys happen above the average and only sells below it.

Without the trend filter, at the old 1-pip spread, the same setup showed +16.2%;
see the day-filter table below.

### Day filter: why only Monday is skipped
Total R by weekday, all trades, both pairs, no days skipped:

| | 2021 | 2022 | 2023 | 2024 | 2025 | Total |
|---|---|---|---|---|---|---|
| Mon | −2.5 | −5.7 | −1.7 | +2.5 | −1.2 | **−8.6** (lost 4 of 5 years) |
| Tue | −0.7 | +0.5 | +8.9 | −1.1 | +0.8 | +8.4 |
| Wed | +5.4 | −0.4 | −4.1 | −0.5 | +5.9 | +6.3 |
| Thu | +5.7 | −0.6 | −2.4 | −5.4 | −0.7 | −3.4 |
| Fri | +8.4 | +3.5 | −1.7 | −2.6 | +13.5 | +21.1 |

Skip Mon+Tue (old): +11.7%, −10.6% DD · **Skip Mon only: +16.2%, −10.2% DD** · Every day: +11.7%, −10.5% DD.
Each weekday-year is only ~25 trades, so treat this as weak evidence. Monday at
least has a plausible cause: its Asian range is built from the thin Sunday open.

The robustness table below was run with the old Mon+Tue filter.

What this means:
- The edge is real but small: about **+0.07 R per trade**, roughly 3%/yr at 0.5% risk.
- Results are lumpy. Two strong years carry three flat or losing ones.
- About 90% of trades are London Breakout trades. The Sweep fires only ~6 times a year.
- **Scaling risk does not reach 10%/yr safely.** At 1% risk: ~4.3%/yr, −20% max DD.
  At 2% risk: ~7.3%/yr, −33% max DD (Monte Carlo 95th percentile: −31%).

### Robustness (one parameter changed at a time)
| Check | In-sample | Out-of-sample | Verdict |
|---|---|---|---|
| Spread 1.0 → 1.5 → 2.0 pips | +6.7 → +5.8 → +3.4% | +4.8 → +3.5 → +3.1% | survives costs |
| Slippage 0.2 → 0.5 pips | +6.7 → +6.0% | +4.8 → +3.9% | ok |
| Sweep `swing_k` 1 / 2 / 3 | +3.3 / +6.7 / +8.5% | +4.8 / +4.8 / +5.0% | stable |
| Sweep `min_rr` 1.25 / 1.5 / 2.0 | +5.5 / +6.7 / +6.3% | +2.5 / +4.8 / +5.4% | ok |
| Breakout `reward_risk` 1.5 / 2 / 2.5 | +7.0 / +6.7 / +6.6% | +4.6 / +4.8 / +4.6% | stable (target rarely hit) |
| **Breakout `min_range_pips` 20 / 25 / 30** | **+12.3 / +6.7 / 0.0%** | **+1.5 / +4.8 / +1.2%** | ⚠️ fragile |
| Breakout `max_defer_extension_pips` 10 / 15 / off | +8.2 / +6.7 / +7.1% | +2.8 / +4.8 / +5.9% | the cap doesn't help out-of-sample |

### Third pair test: AUDUSD (same parameters, no retuning)
| | 2021–2023 | 2024–2025 | 2021–2025 | Max DD | PF |
|---|---|---|---|---|---|
| AUDUSD alone | +0.0% | +5.1% | +5.2% (1.0%/yr) | −6.0% | 1.16 |
| AUDUSD alone, 1.5-pip spread | | | +1.1% | −6.3% | 1.03 |
| EUR + GBP + AUD | +6.7% | +10.0% | +16.9% (3.2%/yr) | −13.4% | 1.19 |

Verdict: **not enabled.** AUDUSD earned nothing in 2021–2023 and roughly breaks
even at a realistic 1.5-pip spread. It also made the losing years worse
(2023 −4.2%, 2024 −5.2% combined). It sits commented out in `config.yaml`
under `pairs:`.

### Strategy arsenal (Nov 2026, `python run_arsenal.py`)
23 strategy variants × 4 markets (EURUSD, GBPUSD, AUDUSD, gold), 2021–2025, 1% risk,
each strategy run alone. Costs are your account's spreads (EUR 1.4, GBP 2.0,
AUD 1.5 pips, gold $0.80) plus gold financing at −6.5%/yr (long) and −1.5%/yr
(short). Pip settings are scaled per market by its typical daily range.

| Strategy | Works on | Trades/yr | 5-yr | Max DD | PF | When it earns |
|---|---|---|---|---|---|---|
| **London Sweep + Breakout (live)** | **EURUSD, GBPUSD** | 27–32 per pair | +9% / +18% | −11% / −10% | 1.25 / 1.35 | London→NY session moves |
| **Gold daily trend (Donchian 55/20, 2×ATR)** | **XAUUSD** | ~6 | +14.4% | −4.8% | 2.83 | strong multi-week trends (2024–25) |
| Gold daily trend, long only (55/20, 3×ATR) | XAUUSD | ~3 | +10.5% | −2.9% | 4.76 | gold bull markets only |
| London Sweep alone | EUR, GBP | 1–2 | +3.5–3.9% | −2% | 2.3–3.0 | rare, high quality |
| Opening-range breakout (London / NY, 15–60 min) | none | 100–240 | −27% to −91% | | 0.6–0.9 | loses even at cheap-account spreads |
| Pullback-in-trend (RSI-2; 5m / 15m / 1h) | none | 190–780 | −21% to −99% | | 0.2–0.9 | loses even at cheap-account spreads |
| Daily trend following on FX | none | 3–10 | −1% to −10% | | 0.3–1.3 | no edge on EUR/GBP/AUD |
| Sweep/Breakout on gold or AUDUSD | none | | | | 0.8–1.0 | not at these costs |

Every gold trend setting tested (Donchian 20–100 day entries, 2–4×ATR stops) was
profitable (PF 1.23–2.86). Most of the profit came in 2024–2025, gold's big
rally; 2021–2023 were roughly flat.

**Combined portfolio** (EUR+GBP stack + gold trend 55/20 2×ATR, 1% risk each):
**+44.7% over 5 years (7.7%/yr), max DD −11.5%**. That compares with +30.3%
(5.5%/yr) and −13.4% for the FX stack alone. By year: +11.1 · +11.4 · −0.3 · −1.5 · +19.0.
Gold trend made money in 2024, when the FX stack lost.

At cheap raw-spread costs (EUR 0.6, GBP 0.9, gold $0.30) the ranking is the same.
The breakout and pullback strategies still lose, so for them costs aren't the
only problem.

### Extra strategies tested and rejected (Nov 2026, `run_consistency.py`)
Each one was run alone on EURUSD and GBPUSD for every year 2021–2025 (10
pair-years). Target: profitable in every pair-year.

| Strategy | Variations tested | Best pair-years profitable | Typical R/trade | Verdict |
|---|---|---|---|---|
| Tiny-range fade (fade breaks of < 10–20 pip Asian ranges) | 48 | 5 / 10 | −0.05 to +0.16, ~23 trades/yr | inconsistent: rejected |
| London-close reversal (fade a 30–80 pip London move at 15:00–16:30) | 96 | 4 / 10 | −0.15 to −0.25 | loses in every variation |
| London-close continuation (trade *with* that move) | 192 | 7 / 10 (and net negative) | ≈ −0.05 | rejected |

| Daily trend following, EURUSD (Donchian 20–100 day breakout, ATR stops; trailing and turtle-style exits; EMA 20/50 × 100/200 crossover) | 84 | EURUSD: 4 of 5 years at best, still net ≈ 0 R | −0.3 to +0.08 | no edge, even with zero swap: rejected |

Trend following was judged on EURUSD (GBPUSD shown only as a cross-check).
It paid ~0.1–0.4 R per trade in overnight swap at −8/−2 USD per lot per night.
With swap set to zero it was still ≈ breakeven, and it also lost in 2023–2024,
so it doesn't hedge the stack's bad years. Multi-day holds and swap are now
supported by the simulator (`costs.swap_long_per_lot` / `swap_short_per_lot`,
triple on Wednesday) for future tests.

Fading and following the afternoon move both lose. The London afternoon
behaves like a random walk where costs decide the result. The code is kept
(`tiny_range_fade.py`, `london_close_reversal.py`) for future experiments
but isn't in the live stack.

⚠️ Most of the Breakout's profit comes from Asian ranges of **25–30 pips**
(+0.12 R in-sample, +0.15 R out-of-sample, positive on both pairs). The 20–25
and 30–35 pip buckets are about breakeven, and ranges under 15 pips lose in
both periods. A sweet spot that narrow could be noise, so watch it in demo.

---

## How the bot decides what to trade

Every bar, both morning strategies evaluate the market and score their own
setup. The highest-scoring proposal takes the one trade slot per pair per day
(`fxbot.backtest.route_morning`, which both the backtest and the live runner use).

### 1. London Sweep: stop-hunt reversal (score 100–130)

```
00:00–08:00   Build the Asian range (London time)
08:00–10:30   Price spikes 1–15 pips past a range edge ("sweep")
              then closes back through the last swing point (Break of Structure)
              → entry on the next bar
```
- **Stop:** beyond the sweep extreme + 1 pip (max 25 pips)
- **Target:** opposite side of the Asian range; skipped if R/R < 1.5
- **SMT filter (hard):** EUR swept but GBP did not, or vice versa
- **Breakeven:** stop moves to entry once the trade is +1R
- **Days:** skips Monday
- **Score:** 100 + 20 (SMT) + 10/5 (tight/moderate range)

### 2. London Breakout: deferred fallback (score 60–77)
```
08:00–10:30   Note a close beyond range ± 0.5 pip, but don't trade yet
10:30–11:00   If price is STILL beyond the range (and < 15 pips extended) → enter
```
- **Range filter:** Asian range 22–80 pips
- **Stop:** opposite side of the Asian range (avg ~45 pips)
- **Target:** 2R. In practice only ~5% of trades reach it; most close at the session exit.
- **Breakeven:** stop moves to entry at +1R
- **Days:** skips Monday

All positions close at **16:00 London** if still open.

### 3. Gold daily trend following (XAUUSD only)
- **Entry:** at the start of each London day, if yesterday's close was above the
  highest high of the previous 55 days, buy. It's buy-only, because shorts lost money in every test.
- **Stop:** 2× the 20-day average daily range below entry. It then trails 2× ATR
  behind the best price reached, and never loosens.
- **Exit:** the trailing stop, or a daily close below the 20-day low.
- **Holding:** days to weeks, so overnight financing applies (modelled at −6.5%/yr on longs).
- **Restarts:** the bot replays ~120 days of hourly bars at startup to rebuild the
  channel. A signal stays valid all day, so a restart doesn't miss it.

### Position sizing
Each trade risks 1% of equity (`risk.risk_per_trade_pct`), measured on
`live.equity_cap` (50,000) and converted to the account currency (CAD) with
MT5's own rate: `units = equity × 1% / (stop distance × USD→CAD)`.
For gold, units are ounces (1 lot = 1 oz on FOREX.com).
A 2% daily loss stops new entries for the rest of the day.

---

## Setup from a fresh clone
```
git clone https://github.com/Harsh-0214/MoneyPrinter2.git
cd MoneyPrinter2
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # fill in MT5 login, password, server, terminal path
python -m pytest -q             # 51 tests
python run_backtest.py --synthetic   # random data: should lose ~the spread
```

## Data
- **histdata.com** (used for backtests): put the M1 CSVs in `data/histdata/`, then run
  `python combine_histdata.py --symbol EURUSD`, `--symbol GBPUSD` and `--symbol XAUUSD`.
- **Dukascopy** (any USD-quoted pair):
  `python download_dukascopy.py --instrument AUDUSD` → `data/AUDUSD_M1_duka.csv`
- **MetaTrader 5:** `python fetch_mt5_data.py --start 2021-01-01 --end 2025-12-31`

Markets must be USD-quoted (EURUSD, GBPUSD, AUDUSD, XAUUSD). The simulator books
P&L in USD; the live bot converts to the account currency. Non-FX instruments set
`instrument: {pip, min_units}` on their `pairs:` entry (gold: pip 0.1, 1 oz).

## Backtest & validation
```
python run_validate.py            # walk-forward + per-year + robustness grid (~10 min)
python run_validate.py --only walk
python run_consistency.py tiny_range_fade   # per-year grid for one strategy (also london_close_reversal, london_close_follow, trend_donchian, trend_turtle, trend_ema; --no-swap, --spread)
python run_arsenal.py             # every strategy x every market, per year (~20 min)
python run_backtest.py            # single-pair run, writes results/trades.csv, equity.png
```
`run_validate.py` caches resampled bars in `data/cache/`, so reruns are fast.

## Run live (demo)
```
start_bots.bat                                 # MT5 + all three bots, auto-restart on crash
stop_bots.bat                                  # stop the bots (positions are left alone)
python run_live.py --pair XAUUSD --dry-run     # one bot, log only
python run_report.py                           # demo results vs backtest expectations
```
- Each bot runs its market's strategies exactly like the backtest (`route_morning`).
  EURUSD and GBPUSD use each other as the SMT feed.
- Only closed bars are used. Missed bars are caught up. On startup and after every
  reconnect the bot replays today's bars (or `warmup_days` of history for gold).
- Each pair has its own magic number (`live.magic` + its index in `pairs`:
  EURUSD 12345, GBPUSD 12346, XAUUSD 12347).
- A second copy for the same pair refuses to start, so trades can't be doubled.
- **Chart overlay:** attach the `FxbotOverlay` indicator (in `mt5/`, installed and
  compiled into MT5) to a chart. It draws the lines each bot is watching, plus a status panel.
- **Logs:** `logs/live_<PAIR>_<date>.log`, with `STATUS` lines (what the bot sees),
  `ORDER` / `Order filled`, `Stop moved`, and `CLOSED` lines with P/L.
- **24/7:** `start_bots.bat` at Windows login (Task Scheduler), the PC set never
  to sleep on AC power, and MT5 set to remember its password.
- A real-money account needs both `--allow-live` and `live.allow_live: true`.

## Project layout
```
config.yaml              every parameter
run_backtest.py          single-pair backtest
run_validate.py          multi-pair walk-forward + robustness
run_consistency.py       year-by-year grid for a single strategy
run_arsenal.py           every strategy x every market (research)
run_live.py              live/demo runner (one process per pair)
run_report.py            demo results vs backtest expectations
start_bots.bat / run_forever.bat / stop_bots.bat   24/7 launchers
mt5/FxbotOverlay.mq5     MT5 chart indicator (draws what the bot sees)
docs/MoneyPrinter2_Guide.pdf   how everything works
download_dukascopy.py    M1 data for any USD-quoted pair
combine_histdata.py      merge histdata.com CSVs
fxbot/
  backtest.py            engine, route_morning(), metrics, multi-pair
  data.py  risk.py
  brokers/  sim_broker.py  mt5_broker.py  base.py
  overlay.py             writes the chart-overlay file for MT5
  strategies/  london_sweep.py  london_breakout.py  trend_follow.py (gold)
               (+ opening_range, trend_pullback, key_levels, tiny_range_fade,
                  london_close_reversal, ny_breakout, prev_day, mean_reversion: tested, unused)
tests/                   51 unit tests
```

## Simulator assumptions (deliberately pessimistic)
- Signals fill at the next bar's open. Buys pay the ask. The spread widens to 3 pips at NY rollover.
- Stops fill with slippage, or at the open if price gaps through.
- If the stop and target are both hit in the same bar, the stop counts.
- Overnight swap is charged at the 17:00 New York rollover (triple on Wednesday). The intraday stack never pays it.
- News spikes are not modelled.

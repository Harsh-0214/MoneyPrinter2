# MoneyPrinter2 — London Session FX Bot (EURUSD + GBPUSD)

Automated intraday trading bot for MetaTrader 5 (FOREX.com demo, Canada).
It runs two strategies on the London open using 5-minute bars, on EURUSD and
GBPUSD. Each pair uses the other one as its SMT confirmation feed.

## Honest results (2021–2025, 0.5% risk per trade)

Validated with `python run_validate.py`. Parameters were chosen on the full
2021–2025 data, so the in-sample/out-of-sample split below is a sanity check,
not a clean blind test.

| Period | Pairs | Trades | Return | CAGR | Max DD | PF | Win % |
|---|---|---|---|---|---|---|---|
| 2021–2023 (in-sample) | EUR + GBP | 222 | +6.73% | 2.2%/yr | -6.93% | 1.18 | 47.7 |
| 2024–2025 (out-of-sample) | EUR + GBP | 126 | +4.83% | 2.4%/yr | -5.98% | 1.27 | 46.8 |
| 2021–2025 | EUR + GBP | 348 | +11.70% | 2.2%/yr | -10.58% | 1.21 | 47.4 |
| 2021–2025 | EURUSD only | 134 | +6.68% | 1.3%/yr | -4.43% | 1.35 | 52.2 |
| 2021–2025 | GBPUSD only | 214 | +5.02% | 1.0%/yr | -8.04% | 1.13 | 44.4 |

**By year (combined):** 2021 +9.6% · 2022 +1.1% · 2023 −3.6% · 2024 −3.9% · 2025 +8.9%

What this means:
- The edge is real but small: about **+0.07 R per trade**, roughly 2%/yr at 0.5% risk.
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

### Extra strategies tested and rejected (Nov 2026, `run_consistency.py`)
Each one was run alone on EURUSD and GBPUSD for every year 2021–2025 (10
pair-years). Target: profitable in every pair-year.

| Strategy | Variations tested | Best pair-years profitable | Typical R/trade | Verdict |
|---|---|---|---|---|
| Tiny-range fade (fade breaks of < 10–20 pip Asian ranges) | 48 | 5 / 10 | −0.05 to +0.16, ~23 trades/yr | inconsistent: rejected |
| London-close reversal (fade a 30–80 pip London move at 15:00–16:30) | 96 | 4 / 10 | −0.15 to −0.25 | loses in every variation |
| London-close continuation (trade *with* that move) | 192 | 7 / 10 (and net negative) | ≈ −0.05 | rejected |

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
- **Days:** skips Monday and Tuesday
- **Score:** 100 + 20 (SMT) + 10/5 (tight/moderate range)

### 2. London Breakout: deferred fallback (score 60–77)
```
08:00–10:30   Note a close beyond range ± 0.5 pip, but don't trade yet
10:30–11:00   If price is STILL beyond the range (and < 15 pips extended) → enter
```
- **Range filter:** Asian range 25–80 pips
- **Stop:** opposite side of the Asian range (avg ~45 pips)
- **Target:** 2R. In practice only ~5% of trades reach it; most close at the session exit.
- **Breakeven:** stop moves to entry at +1R
- **Days:** skips Monday and Tuesday

All positions close at **16:00 London** if still open.

### Position sizing
Each trade risks 0.5% of equity: `units = equity × 0.005 / stop distance`.
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
python -m pytest -q             # 35 tests
python run_backtest.py --synthetic   # random data: should lose ~the spread
```

## Data
- **histdata.com** (used for backtests): put the M1 CSVs in `data/histdata/`, then run
  `python combine_histdata.py --symbol EURUSD` and `--symbol GBPUSD`.
- **Dukascopy** (any USD-quoted pair):
  `python download_dukascopy.py --instrument AUDUSD` → `data/AUDUSD_M1_duka.csv`
- **MetaTrader 5:** `python fetch_mt5_data.py --start 2021-01-01 --end 2025-12-31`

Pairs must be USD-quoted (XXX/USD). The simulator books PnL in the quote currency.

## Backtest & validation
```
python run_validate.py            # walk-forward + per-year + robustness grid (~10 min)
python run_validate.py --only walk
python run_consistency.py tiny_range_fade   # per-year grid for one strategy (also london_close_reversal / london_close_follow)
python run_backtest.py            # single-pair run, writes results/trades.csv, equity.png
```
`run_validate.py` caches resampled bars in `data/cache/`, so reruns are fast.

## Run live (demo)
```
python run_live.py --pair EURUSD --dry-run     # log only
python run_live.py --pair EURUSD               # demo orders
python run_live.py --pair GBPUSD               # second process for the second pair
```
- Runs the same strategy stack and routing as the backtest, with the partner pair as the SMT feed.
- Only closed 5-minute bars are used. Missed bars are caught up, and today's bars
  are replayed on startup and after every reconnect.
- Each pair gets its own magic number (`live.magic` + index in `pairs`).
- A real-money account needs both `--allow-live` and `live.allow_live: true`.

## Project layout
```
config.yaml              every parameter
run_backtest.py          single-pair backtest
run_validate.py          multi-pair walk-forward + robustness
run_consistency.py       year-by-year grid for a single strategy
run_live.py              live/demo runner (one process per pair)
download_dukascopy.py    M1 data for any USD-quoted pair
combine_histdata.py      merge histdata.com CSVs
fxbot/
  backtest.py            engine, route_morning(), metrics, multi-pair
  data.py  risk.py
  brokers/  sim_broker.py  mt5_broker.py  base.py
  strategies/  london_sweep.py  london_breakout.py  (+ tiny_range_fade, london_close_reversal, ny_breakout, prev_day, mean_reversion: tested, unused)
tests/                   35 unit tests
```

## Simulator assumptions (deliberately pessimistic)
- Signals fill at the next bar's open. Buys pay the ask. The spread widens to 3 pips at NY rollover.
- Stops fill with slippage, or at the open if price gaps through.
- If the stop and target are both hit in the same bar, the stop counts.
- Not modelled: overnight swap (none needed, everything closes the same day) and news spikes.

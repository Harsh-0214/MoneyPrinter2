# MoneyPrinter2 — FX + Gold Trading Bot for MetaTrader 5

Automated trading bot for MetaTrader 5 (FOREX.com demo, Canada, CAD account).
**One bot per market** (EURUSD, GBPUSD, XAUUSD). Each bot runs all of that
market's strategies and trades whichever one has a setup. Every strategy keeps
its own trade label (magic number), so strategies on the same market can hold
positions at the same time, and the report tracks each one separately:

| Market bot | Strategy | Bars | Trades/yr | Magic | When it trades |
|---|---|---|---|---|---|
| **EURUSD** | London Sweep + Breakout, daily trend filter | 15 min | ~20 | 12345 | 08:00–11:00 London; Sweep exits 16:00, Breakout 20:00 |
| | Daily swing pullback (RSI-2, 100-day trend) | 1 h | ~10 | 12445 | decides daily, holds 1–10 days |
| **GBPUSD** | London Sweep + Breakout (SMT partner: EURUSD) | 5 min | ~38 | 12346 | 08:00–11:00 London; Sweep exits 16:00, Breakout 20:00 |
| | Daily swing pullback (RSI-2, 200-day trend) | 1 h | ~11 | 12446 | decides daily, holds 1–10 days |
| **XAUUSD** | Gold trend following, 55-day breakout, buy-only | 1 h | ~5 | 12347 | decides daily, holds weeks |
| | Gold trend following, 20-day breakout, buy-only | 1 h | ~6 | 12447 | same |

In `config.yaml`, a market's main stack is its `pairs:` entry and each extra
strategy is a `sleeves:` item under it. Adding a strategy to a market means adding a sleeve.

**Portfolio backtest, 2021–2025, 1% risk per trade, real spreads:**
**+69.4% (11.2%/yr), max drawdown −9.7%, PF 1.54, no losing year.**
By year: +12.6 · +13.1 · +0.2 · +4.3 · +27.3 (with the ±30-min news filter, now on:
+69.1%, same drawdown; see "High-impact news filter"). The three newest strategies were
picked from 54 candidates, so expect live results to be somewhat lower. This is a
backtest, not a promise; see the caveats under "Strategy arsenal". All bots
together never risk more than `live.max_open_risk_pct` (5%) at once.
A step-by-step guide is in **`docs/MoneyPrinter2_Guide.pdf`**.

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

Sweep trades close at **16:00 London** and Breakout trades at **20:00 London** if still open.
Nov 2026 test (2021-25, EUR+GBP): Breakout exit 20:00 +45% / PF 1.39 vs 16:00 +30% / PF 1.30;
no time exit at all was worse (+20%, PF 1.14, DD -19%). `session_exit: null` disables it.

**Timeframe (Nov 2026, with the 20:00 exit):** EURUSD runs on 15-min candles (2021-25 PF 1.48 vs
1.30 on 5-min, DD -8.5% vs -13.5%; 2026 out-of-sample +4.1% vs +2.8%). GBPUSD stays on 5-min
(+32% vs +22% on 15-min over 2021-25). 1-min and 30-min were worse on both pairs.

### 3. Gold daily trend following (XAUUSD only)
- **Entry:** at the start of each London day, if yesterday's close was above the
  highest high of the previous 55 days, buy. It's buy-only, because shorts lost money in every test.
- **Stop:** 2× the 20-day average daily range below entry. It then trails 2× ATR
  behind the best price reached, and never loosens.
- **Exit:** the trailing stop, or a daily close below the 20-day low.
- **Holding:** days to weeks, so overnight financing applies (modelled at −6.5%/yr on longs).
- **Restarts:** the bot replays ~120 days of hourly bars at startup to rebuild the
  channel. A signal stays valid all day, so a restart doesn't miss it.

### 4. Daily swing pullback (EURUSD:pullback, GBPUSD:pullback)
- **Trend:** the daily close versus its 100-day average (EURUSD) or 200-day average (GBPUSD).
- **Entry:** in an uptrend, buy when the 2-day RSI of daily closes drops below 10
  (a sharp 1–3 day dip). In a downtrend, sell when it rises above 90.
- **Exit:** a daily close back above (or below) the 5-day average, or after 10 days.
  There's a protective stop at 3× the daily ATR.
- **Why it's here:** about 70% of trades win. Its monthly returns are uncorrelated
  with the London stack (+0.03 / −0.04), so it smooths the portfolio, adding
  +0.5–0.7%/yr per pair at a −1.3 to −2.9% drawdown.

### 5. Fast gold trend (XAUUSD:fast)
The same rules as the 55-day gold trend, but with a 20-day breakout entry and a
10-day low exit. It catches shorter gold trends the slow system misses.
2021–2025 alone: +18.1%, PF 2.94, max drawdown −3.6%. Correlation with the rest
of the portfolio is +0.35, because both are gold trend systems.

### Strategy research round 2 (same markets, new styles)
Tested on EURUSD, GBPUSD and gold (`run_arsenal.py`, `results/arsenal_round2.csv`):
the daily swing pullback, volatility breakout (open ± k×yesterday's range),
NR7 / NR4 / inside-day breakouts, the previous-day high/low breakout, and the
20-day gold trend. **Adopted:** the daily pullback on EUR and GBP, and the 20-day
gold trend. **Rejected:** volatility breakout and previous-day breakout lost on
all three markets; NR7/NR4 were ~breakeven. The gold inside-day breakout made
money (+12%, PF 1.56) but raised the portfolio drawdown to −14%, and its close
cousins didn't work, so it was left out.

| Portfolio (1% risk each) | Trades/yr | 5-yr | Per year | Max DD |
|---|---|---|---|---|
| EUR+GBP stack + gold 55-day | 70 | +45% | 7.8% | −11.1% |
| + gold 20-day + EUR/GBP daily pullbacks (**live**) | 98 | +69% | 11.2% | −9.7% |
| + gold inside-day breakout too | 116 | +82% | 12.7% | −14.2% |

### Position sizing
Each trade risks 1% of equity (`risk.risk_per_trade_pct`), measured on
`live.equity_cap` (50,000) and converted to the account currency (CAD) with
MT5's own rate: `units = equity × 1% / (stop distance × USD→CAD)`.
For gold, units are ounces (1 lot = 1 oz on FOREX.com).
A 2% daily loss stops new entries for the rest of the day.
**Portfolio risk cap:** before any order, the bot adds up what every open bot
position would lose at its stop (across all markets and magic numbers). If that
plus the new trade's 1% exceeds `live.max_open_risk_pct` (5% = 2,500 CAD), the
trade is skipped and logged as `RISK CAP`. Positions whose stop is already at or
past entry count as zero.

---

## Setup from a fresh clone
```
git clone https://github.com/Harsh-0214/MoneyPrinter2.git
cd MoneyPrinter2
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # fill in MT5 login, password, server, terminal path
python -m pytest -q             # 72 tests
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
start_bots.bat                                 # MT5 + one bot per market (3), auto-restart on crash
stop_bots.bat                                  # stop the bots (positions are left alone)
python run_live.py --pair XAUUSD --dry-run     # one bot, log only
python run_live.py --pair EURUSD --sleeve pullback   # just one of a market's strategies (testing)
python run_report.py                           # demo results vs backtest expectations
```
- Each market bot runs all of its strategies in one loop, exactly like the backtest
  (`route_morning`). Each strategy uses its own bar timeframe (5 min or 1 h).
  EURUSD and GBPUSD's London stacks use each other as the SMT feed.
- Only closed bars are used. Missed bars are caught up. On startup and after every
  reconnect each strategy replays today's bars, or `warmup_days` of history for the daily strategies.
- Each strategy has its own magic number, so its trades are labelled separately in MT5.
  Main stacks are `live.magic` + the pair's index (EURUSD 12345, GBPUSD 12346, XAUUSD 12347);
  sleeve j adds 100×j (12445, 12446, 12447).
- One log per market bot: `logs/live_<PAIR>_<date>.log`. Each line is tagged with the strategy
  (`[London]`, `[Pullback]`, `[Trend 55d]`, `[Trend 20d]`). One chart file per market: `fxbot_<SYMBOL>.txt`.
- A second copy for the same pair refuses to start, so trades can't be doubled.
- **Terminal = plain English.** Each market window narrates in short `# ...` lines: startup,
  what each strategy is waiting for, "wants to SELL ... because ...", safety checks, trade size,
  fills, stop moves, closes with P/L, skips (news / spread / risk cap) and a daily summary.
  The technical log stays in the log file (`--verbose` also prints it in the terminal).
- **Journal:** `logs/journal_<date>.log` collects the important events of all three markets
  in one file. The FxbotOverlay indicator also prints them into MT5's **Experts** tab
  (from `fxbot_events_<SYMBOL>.txt`). Orders and fills also appear in MT5's own Journal tab.
- **Spread guard:** no new entry while the live spread is above `live.max_spread_mult`
  (2.5×) the pair's normal spread.
- **Drawdown circuit breaker:** no new trades once the account is `live.max_drawdown_pct`
  (15% of the sizing base) below its peak. The peak is in `data/state/peak_equity.json`;
  delete that file to resume after investigating.
- **Stall watchdog:** if the market is open but no new candles arrive for 20 min
  (3 h for hourly strategies), the bot reconnects to MT5.
- **Daily summary** per market at the start of each London day: closed trades, P/L, open trades, equity.
- **Fresh-data check:** `python run_oos_mt5.py` re-runs the live portfolio on 2026 data from
  MT5 that was never used for tuning (Jan 1 - Nov 11 2026: +17.0%, PF 2.60, max DD -4.7%).
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
run_portfolio.py         all live strategies on one account: compounding, risk brake, real margin, Monte Carlo
run_new_markets.py       live strategies on indices / silver / oil / JPY crosses (broker H1 feed)
fetch_mt5_h1.py          broker's own H1 history -> data/mt5/ (for run_new_markets.py)
run_live.py              live/demo runner (one bot per market, runs all its strategies)
run_report.py            demo results vs backtest expectations
start_bots.bat / run_forever.bat / stop_bots.bat   24/7 launchers
mt5/FxbotOverlay.mq5     MT5 chart indicator (draws what the bot sees)
docs/MoneyPrinter2_Guide.pdf   how everything works
download_dukascopy.py    M1 data for any USD-quoted pair
combine_histdata.py      merge histdata.com CSVs
build_news_calendar.py   builds data/news/high_impact_2021_2025.csv
run_news_test.py         news-filter backtest comparison
fxbot/
  backtest.py            engine, route_morning(), metrics, multi-pair
  data.py  risk.py  news.py (news calendar)
  brokers/  sim_broker.py  mt5_broker.py  base.py
  overlay.py             writes the chart-overlay file for MT5
  strategies/  london_sweep.py  london_breakout.py  trend_follow.py (gold)  daily_patterns.py (pullback)
               (+ opening_range, trend_pullback, key_levels, tiny_range_fade,
                  london_close_reversal, ny_breakout, prev_day, mean_reversion: tested, unused)
tests/                   72 unit tests
```

## High-impact news filter (`fxbot/news.py`)
Blocks **new entries** within `risk.news_blackout_minutes` of a high-impact release for
the currencies that move that market (EURUSD: USD+EUR, GBPUSD: USD+GBP, XAUUSD: USD;
`risk.news_currencies: auto`). Open trades are never closed because of news.
Switch: `risk.news_filter` (**on**, ±30 min, no whole-day skips).
- **Backtests** use `data/news/high_impact_2021_2025.csv`, built by
  `python build_news_calendar.py` from official release dates (BLS for NFP/CPI, the Fed,
  ECB, BoE, ONS, Eurostat flash HICP), with local release times converted to UTC using
  real DST rules. Only 7 event types (NFP, US CPI, FOMC + press conference, ECB +
  press conference, BoE, UK CPI, Eurozone flash CPI); PMIs, GDP, retail sales, speeches
  etc. are missing. UK CPI dates are the least certain.
- **Live** bots read the public Forex Factory weekly JSON (every "High" event, so more
  than the backtest covers), refreshed at most every `news_refresh_hours` (4) and cached in
  `data/news/live_calendar.csv`. A failed download logs a warning and uses the cache, or
  no filter. Skips are logged as `NEWS: skipping entry, USD CPI m/m at 13:30 UTC ...`, and
  the chart overlay shows the next event.
- `python run_news_test.py` reruns the comparison below.

Portfolio backtest 2021–2025 (all 6 strategies, 1% risk), only the news settings changed:

| News setting | 2021 | 2022 | 2023 | 2024 | 2025 | Total | Max DD | PF | Trades |
|---|---|---|---|---|---|---|---|---|---|
| No filter (old) | +12.6 | +13.1 | +0.2 | +4.3 | +27.3 | +69.4% | −9.7% | 1.54 | 489 |
| ±15 min | +12.6 | +13.1 | +0.2 | +4.3 | +27.3 | +69.4% | −9.7% | 1.54 | 489 |
| **±30 min (live)** | +12.4 | +13.1 | +0.2 | +4.4 | +27.3 | **+69.1%** | **−9.7%** | 1.54 | 488 |
| ±60 min | +11.5 | +14.1 | −1.0 | +4.4 | +27.0 | +67.0% | −9.8% | 1.53 | 481 |
| ±120 min | +12.6 | +14.1 | −3.3 | +4.5 | +25.1 | +62.2% | −11.9% | 1.50 | 475 |
| ±30 min + skip NFP/FOMC days | +10.5 | +10.8 | +2.3 | +3.9 | +25.2 | +62.8% | −7.0% | 1.57 | 443 |
| ±30 min + skip all event days | +11.0 | +10.1 | +0.7 | +4.9 | +21.4 | +56.8% | −8.0% | 1.60 | 394 |

Why it barely matters: the London entries happen 08:00–11:00 London, and most big
releases fall outside that window (US data 13:30, BoE 12:00, ECB 13:15, FOMC 19:00).
The daily strategies decide at midnight. Only Eurozone flash CPI (10:00 London) and UK
CPI (07:00) are close. ±30 min is kept because it's nearly free, and it guards against the
spread blowouts and spikes the simulator doesn't model. Skipping NFP/FOMC days cut
drawdown to −7.0% but cost 6.6 points of return. It was also 1 of 7 variants tried, so
it wasn't adopted. Turn it on with `news_day_block: [payrolls, fomc]` if you prefer smaller drawdowns.

## Simulator assumptions (deliberately pessimistic)
- Signals fill at the next bar's open. Buys pay the ask. The spread widens to 3 pips at NY rollover.
- Stops fill with slippage, or at the open if price gaps through.
- If the stop and target are both hit in the same bar, the stop counts.
- Overnight swap is charged at the 17:00 New York rollover (triple on Wednesday). The intraday stack never pays it.
- News spikes are not modelled (the news filter only changes which entries are allowed).

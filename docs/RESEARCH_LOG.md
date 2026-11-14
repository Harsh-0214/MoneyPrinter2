# Research log

What was tested, how, and what was kept. Raw result files are in `results/` (not in git).
Method for every test: real spreads + slippage, histdata M1 2021-2025, and 2026 MT5 data
that no setting was ever tuned on. Strategy ideas are judged on 2021-23, then once on
2024-25 / 2026; a fix that only works on the data it was found on is rejected.

## Live portfolio (Nov 2026)

| Bot | Strategy | Candles | Notes |
|---|---|---|---|
| EURUSD | London Sweep + Breakout | 15 min | Breakout exits 20:00 London |
| GBPUSD | London Sweep + Breakout, daily RSI-2 pullback | 5 min / 1 h | Pullback stop 1.5x ATR |
| XAUUSD | Donchian trend 55d + 20d, each with a +0.5R add-on | 1 h | Trailing stops, no target |
| USDJPY | Volatility breakout (Larry Williams), k 0.9 | 15 min | Entries 05:00-12:00 London, breakeven at +1R, a second try after a same-day stop-out (Nov 13 2026) |

Risk: 3% per trade on real equity (compounding), risk brake 3% -> 2% / 1% / 0.5% at
-8% / -15% / -20% from the peak, no new trades at -28%, margin use capped at 70%.
Portfolio sim (margin + brake): 2021-25 avg ~4.9%/month, max DD ~-21%; 2026 ~7.5%/month.

## Kept (improved results on both periods)

- London Breakout exit 16:00 -> 20:00 (2021-25 +30% -> +45%, PF 1.30 -> 1.39).
- EURUSD London stack on 15-min candles (PF 1.30 -> 1.48; 2026 +2.8% -> +4.1%).
- USDJPY added (volatility breakout; all 96 grid settings profitable; -0.08 monthly
  correlation with the rest); entry window 05:00-12:00 (PF 1.58 -> 2.35).
- Gold add-on positions at +0.5R (avg month 3.9% -> 4.9%, same drawdown).
- Risk brake (no reshuffled 2021-25 path past -30%; flat 3% had 40% chance).
- Compounding on real equity.
- USDJPY breakout: a second try after a same-day stop-out (2021-25 PF 2.35 -> 2.52, +7.5R;
  2026 unchanged). 13 Nov 2026.

## Tested and rejected

| Idea | Result |
|---|---|
| Bigger targets (3R, 4R), trailing stops, no time exit (London) | All lower than 2R + 20:00 exit |
| "Let it run" target extension near the target | 2021-25 lower in all 10 variants (only 1 trade in 5 yrs ran past 2.2R) |
| Fixed targets on USDJPY breakout | Halved profit |
| 1-min / 30-min candles | Worse on every pair |
| Second trade per day (London) | Never fires before the cutoff; later cutoffs worse |
| Risk weighting per bot | Within noise; worse drawdowns |
| Min stop distance vs spread | Tight-stop trades ~0R, but portfolio unchanged: built, off |
| Proven strategies on the other 3 markets | None passed; 3 near-misses cut 2021-25 returns |
| Raschke (Turtle Soup, 80-20, Holy Grail), Crabel ID/NR4 | 80-20 lost everywhere; others too rare or negative in 2026 |
| DeMark TD9, Bollinger squeeze, Connors Double 7s, PTJ 200-day | None passed (2-3 of 5 years at best) |
| Original idea: USDJPY Tokyo-session continuation | PF 1.56 on 2021-23, PF 0.81 on 2024-25 -> noise |
| Protect open trades before major news (close / breakeven) | All 4 variants lower (+155-162% vs +172%), no drawdown gain |
| Regime filters / breakeven applied to ~190 failed strategy-market combos | Made the median worse; only variants of the live USDJPY breakout passed |
| Weekend gap fade (new idea, 5 markets x 8 settings) | 27 of 40 lose; the one winner is 1 setting on GBPUSD |
| Adding to USDJPY breakout winners (+0.5R / +1R add-on unit) | Strong 2021-25, lost every 2026 trade |
| Gold: 10-day trend sleeve, 1R / 1.5R add-ons, intraday entries | Alone fine; in the portfolio gold's margin crowds other trades out (10/5 sleeve: an option) |
| 28 more markets (metals, energy, softs, 7 indices, 17 FX crosses) x live strategies | 2 thin passes (China A50, UK oil trend); CHFJPY pullback failed on 2011-18 |
| London stack on AUD, CAD, CHF, NZD, EURGBP (broker 15-min, 4 years) | PF 0.24-1.28, none |

## Fresh review (12 Nov 2026)

- **Margin was modelled too kindly.** Measured with `mt5.order_calc_margin`: FX 5% of
  notional (20:1), **gold 22% (~4.5:1)**, US indices 10%. Older portfolio sims assumed 20:1
  for gold too. With real margin (`run_portfolio.py`), 3% risk: 2021-25 avg 4.65%/month
  (was 4.9), max DD -18.7%; 2026 6.5%/month (was 8.2), DD -10.5%. The live bot already uses
  real margin (MarginGuard), so it was the projections that were high, not the bot.
- **Risk level:** with the brake, more than 3% adds almost nothing (Monte Carlo median
  5.1 -> 5.3%/month at 3 -> 6%) because the brake and margin cap cut trades back. Without the
  brake, 6% risk: 2021-25 7.2%/month, DD -37%, 1-in-100 reshuffle -51%; median still ~6.4%
  because margin binds. **8%/month is not reachable with this portfolio at survivable risk.**
- **12 new markets** (`run_new_markets.py`, broker's own H1 feed 2019-2026, live settings
  unchanged): SPX500, NAS100, US30, GER40, UK100, JPN225, XAGUSD, US Oil, EUR/GBP/CAD/AUD-JPY.
  None passed (PF >= 1.15 on 2019-25, >= 5/7 years up, 2026 PF >= 1). Closest: US Oil trend
  20/10 PF 1.18 (too thin), NAS100 vol breakout PF 2.05 but 2026 negative, SPX500 pullback
  PF 1.20 at 4/7 years. Reference rows confirm the live edges on this independent feed
  (incl. 2019-20, never used before): gold trend 55/20 PF 3.26, 20/10 PF 2.58, USDJPY vol
  breakout PF 2.13.
- **Leave-one-out** (3% risk, real margin): every live unit adds return in at least 2 of
  2021-23 / 2024-25 / 2026. Nothing to cut.
- **Risk weighting retested with real margin:** gold + USDJPY at 4%, the rest 3%: avg month
  3.73 -> 4.22 (2021-23), 6.05 -> 6.11 (2024-25), 6.50 -> 7.03 (2026), DD -16.0/-18.7/-10.5
  -> -16.6/-20.5/-8.6. Higher return in all 3 periods but small and with deeper drawdowns
  in 2 of them (best of 4 variants tried): not applied, an option.
- Live bug fixed: MT5 sometimes returns no tick for a moment; `current_spread_pips`,
  `submit` and `close_position` now handle it instead of raising (3 crashes on 11 Nov).

## Calendar / flow effects (12 Nov 2026, `run_calendar_effects.py`) - none passed

| Idea | Result |
|---|---|
| Turn-of-month on 6 indices (last day to 3rd day), 2001-2026 | No better than any other 4-day hold, on every index |
| Overnight index drift (US close -> 09:00 NY), 2018-26 | Negative after costs on all 6 indices and gold |
| Pre-FOMC drift (24 h before the decision), 2019-26 | NAS100 +33 bp/event but from 2020 + 2022; 2025-26 ~0; best 5 removed: +13 bp. Decayed |
| Gold "Asian session" rise | Positive every year, but it's the 22-23 UTC reopen bars: BID recovers as the reopen spread narrows, a buyer pays the wide ASK. From 00 UTC: +0.3 bp/h < spread. Artifact |
| Month-end USD rebalancing into the London 4pm fix (US vs foreign equities), 2010-26 | Coin flip on EUR/GBP/JPY/AUD (51-54% hit, sign flips by period) |

## 13 Nov 2026

- **US index opening-range breakout** (`run_index_orb.py`, NAS100 / SPX500 / US30, 15 and 30 min
  range after the 09:30 NY open, 2R or no target, with / without trend filter, 15-min bars
  Apr 2024-Nov 2026 and 5-min bars Jun 2025-Nov 2026, real spreads): PF 0.70-1.08 in all 24
  runs. ~12 trades a month at break-even or worse. Rejected.
- **Breakout minimum Asian range 21 vs 22 pips** (full portfolio, real margin): avg month
  2021-23 3.91 vs 3.92, 2024-25 6.11 vs 6.34, 2026 5.93 vs 7.04. 20-24 pips all similar
  (plateau), 22 stays.
- **CFTC positioning (COT)** (`fetch_cot.py`, `run_cot.py`, weekly reports 2000-2026, EUR/GBP/
  JPY/AUD/CAD/CHF/gold, daily MT5 prices, entries the Monday after release, rules fixed first):
  fade speculator extremes 2007-20 -0.17R/trade (5/14 years up); follow commercials -0.21R
  (3/14); follow 4-week spec flow -0.03R (3/14). Filter on the bot's own trades: trades with
  the crowd already on their side averaged the same R in 2021-23 (0.23 vs 0.23), lower in
  2024-26 (0.20 vs 0.62) but still profitable, so skipping them removes profit. Rejected.
- News calendar: one bot downloads at a time (lock file), per-process temp files, retried
  replace on Windows. Fixes the "file in use" / HTTP 429 warnings when 4 bots refresh at once.

## Live risk (12 Nov 2026)

Gold (all 4 units) and USDJPY: 4% risk per trade; EURUSD, GBPUSD, GBP pullback: 3%.
`run_portfolio.py` (real margin, brake as in run_live): avg month 3.92 / 6.34 / 7.03% for
2021-23 / 2024-25 / 2026, max DD -17.2 / -19.7 / -8.6%.
Nov 13 2026, with the USDJPY second try: 4.05 / 6.54 / 7.03%, max DD unchanged.

## Why strategies fail here (diagnosis of every strategy tried, 2021-23)

- 57% have no edge even before costs (coin flips): no filter or exit can fix them.
- 12% have a small gross edge (+0.07-0.2R) eaten by 0.1-0.3R of spread per trade
  (mostly opening-range breakouts trading 100-200 times a year).
- 11% work - the live bots are drawn from this group.
- Ways left to add profit: lower trading costs (raw-spread account), time (compounding),
  and genuinely new strategy ideas. Tried and failed on 12 Nov 2026: more markets for the
  proven strategies (JPY crosses, indices, silver, oil) and calendar / flow effects.

## Nov 13 2026 - Big US company stocks (CFDs on the same account): rejected for the bot

`fetch_mt5_stocks.py`, `run_stocks.py`. Broker H1 history 2013-2026, split-adjusted (one data hole
in GE Jan-Sep 2025). Two lists: today's 12 biggest companies, and 2013's 14 biggest (the honest
list - today's leaders are leaders because they went up). Costs: recorded spread + 0.08%/side
(1.8c/share commission, $10 min) + CFD financing 7%/yr buys, 1.5%/yr shorts. Live settings, untuned.

| strategy (pooled R, 1% risk)  | today's top 12: PF, years up, 2026 | 2013's top 14: PF, years up, 2026 |
|-------------------------------|------------------------------------|-----------------------------------|
| Trend 55/20 buy-only (gold)   | 1.22, 10/13, -15.9R                | 0.89, 5/13, -3.4R                 |
| Trend 20/10 buy-only          | 1.20, 8/13, -11.1R                 | 0.89, 4/13, -3.6R                 |
| Trend 55/20 buy+short         | 0.93, 4/13                         | 0.75, 2/13                        |
| Trend 20/10 buy+short         | 0.87, 3/13                         | 0.75, 2/13                        |
| Breakout US session (USDJPY)  | 0.75, 0/13                         | 0.52, 0/13                        |

Trend buy-only only "works" on today's winners (hindsight) and loses on the 2013 list. Shorting
stocks loses on both lists. Intraday breakout loses heavily.

Momentum rotation (monthly, hold the 3 best 12-1 month performers of the 2013 list):
as CFDs +13.5%/yr vs holding all 14 +4.7%/yr (7%/yr financing eats most of it); as real shares
(no financing) +21.6%/yr, DD -18%, vs S&P 500 +13.4%/yr (2014-2025). But the edge is almost all
2020-2025 (first half: +10.3% vs +7.6% hold-all; second half +34% vs +17%) and top 4-7 holdings
give 16-17%/yr. Modest, period-dependent, a long-term investing idea (real shares, e.g. a TFSA),
not a fit for the CFD bot. Not added.

## Nov 13 2026 - Stock-specific strategies (dip buying, weak close, gap drift, pairs): rejected

`run_stock_edges.py`. Rules written before the run (see the script header). Decisions at 15:00 NY,
fills at the 16:00 close; 0.08%/side per stock + CFD financing. Account % = 25% of the account per
trade, at most 4 at once (no leverage), average per year 2013-2025.

| strategy                    | today's top 12: PF, yrs up, acct %/yr, 2026 | 2013's top 14: PF, yrs up, acct %/yr, 2026 |
|-----------------------------|----------------------------------------------|--------------------------------------------|
| S1 dip (RSI-2 < 10 above 200d) | 1.28, 12/13, +3.4, +13.4  PASS            | 1.19, 9/13, +1.3, +4.2 (fails 70% years)   |
| S2 weak close (IBS < 0.2)   | 1.31, 8/13, +9.9, -13.3                      | 1.12, 7/13, +6.6, -12.7                    |
| S3 gap >4% follow, buy      | 1.52, 10/13, +4.5, -1.0                      | 1.20, 7/12, +0.4, +2.5                     |
| S3 gap >4% follow, short    | 0.49, 2/12                                   | 0.95, 6/11                                 |
| S4 pairs (7 pairs, z > 2)   | 0.59, 1/13, -6.1 (every pair loses after costs)                          |

Holding the lists for comparison: today's top 12 +45%/yr as shares (hindsight), 2013's top 14
+15.6%/yr as shares, ~+8.6% as CFDs. The dip-buy edge is real but small (+0.15% per trade on the
2013 list) and is worth ~1-3%/yr to the account - far less than just holding the stocks. Large-cap
pairs keep drifting apart instead of snapping back. Nothing added.

## Nov 13 2026 - Carry trade and news-reaction trading: both rejected

**Carry** (`run_carry.py`; OECD 3-month interbank rates into `data/rates/oecd.csv` from
sdmx.oecd.org, FRED timed out; broker daily prices). Monthly: buy the 3 highest-rate of USD EUR
GBP JPY AUD NZD CAD CHF, short the 3 lowest. The broker's MT5 swap fields read 0 on the demo, so
its interest cut is unknown: judged at 1.5%/yr per position, shown at 0 and 3%.

| version (no leverage)       | cut 0%: per yr, Sharpe, worst drop | cut 1.5%   | cut 3%   |
|-----------------------------|------------------------------------|------------|----------|
| V1 plain carry              | -0.2%, 0.02, -34%                  | -2.6%/yr   | -5.0%/yr |
| V2 + 3-month crash filter   | -0.1%, 0.00, -29%                  | -1.4%/yr   | -2.4%/yr |

Mostly long NZD/AUD, short CHF/JPY/EUR. 2008 -25%, then flat to down most years since. Even with
the broker taking nothing it earned nothing over 2007-2025. (Data holes in the broker's daily
files - EUR 2021, NZD 2020, CAD 2015, JPY/AUD/CHF most of 2025 - are handled by leaving that
currency out of the ranking that month.)

**News reaction** (`run_news_reaction.py`). First event of the day per market, 2021-2025
calendar + 2026 US releases (BLS archive dates, FOMC). 15-minute reaction >= 0.2 x daily range:
follow it (stop at the pre-release price) or fade it (stop at the 15-minute extreme); breakeven at
1R, out after 4 h; double spread + slippage. Timing checked: EURUSD moves 14.1 pips in the 15
minutes after NFP vs 6.0 the week before and 4.1 later that day.

| threshold | follow: PF, yrs up, 2026 | fade: PF, yrs up, 2026 |
|-----------|--------------------------|------------------------|
| 0.1       | 0.50, 1/5, -21R          | 0.18, 0/5, -156R       |
| 0.2       | 0.57, 1/5, -2.6R         | 0.25, 0/5, -100R       |
| 0.3       | 0.77, 1/5, +0.2R         | 0.27, 1/5, -77R        |

Following the move loses on every market; fading it loses badly (the 15-minute extreme is a
tight stop that wide post-news spreads keep hitting). The first 15 minutes already price the news.

## Nov 13 2026 (evening) - More trades from the edges that work; new ideas

Goal: more trades and more profit without loosening the rules. Scripts: `run_more_trades.py`
(variants of the live units, histdata 2021-25 + the broker's own feed for 2019-20 and 2026),
`run_portfolio_add.py` (what a candidate adds to the live portfolio: real margin, risk brake,
gold/USDJPY at 4%), `run_new_markets.py --round2` (28 more markets, `fetch_mt5_more.py`),
`run_london_more.py`, `run_london_crosses.py`, `run_chfjpy_pullback.py`. Rules fixed before each
run: PF >= 1.15 and >= 4/5 years up on 2021-25, 2026 PF >= 1; a portfolio change must raise
the average month in all of 2021-23 / 2024-25 / 2026 without a deeper drawdown (> 2 points).
Baseline (live units, live risk): avg month 3.92 / 6.34 / 7.04%, max DD -17.2 / -19.7 / -8.5%.

### USDJPY volatility breakout: a second try and adding to winners

| variant (1% risk)                 | trades/yr | PF 21-25 | yrs up | R 2021-23 | R 2024-25 | 2026 (broker M15) |
|-----------------------------------|-----------|----------|--------|-----------|-----------|-------------------|
| live (one trade a day)            | 14.6      | 2.35     | 3/5    | +29.5     | +6.8      | +6.2R, PF 2.97    |
| **re-entry: up to 2 tries a day** | 15.8      | 2.52     | 4/5    | +31.0     | +12.8     | +6.2R, PF 2.97 (no second try happened) |
| **add-on unit at +0.5R, stop at the level** | 8.0 | 2.86  | 4/5    | +17.3     | +10.7     | **-4.5R** (6 trades) |
| add-on unit at +1.0R              | 5.4       | 6.03     | 4/5    | +15.3     | +6.6      | **-3.5R** (4 trades) |
| Mondays too                       | 18.8      | 1.84     | 4/5    | +29.3     | +3.5      | +3.3R, PF 1.42    |
| no trend filter                   | 26.8      | 1.69     | 4/5    | +36.9     | +5.2      | **+24.8R**, PF 4.04 |
| no trend + re-entry               | 30.0      | 1.68     | 4/5    | +37.4     | +9.7      | +22.8R, PF 3.27   |

Re-entry: after a stop-out, a second close beyond the level the same day is taken (the
second attempt won 2021-25 in both periods: +1.5R and +6.0R more). Add-on: a separate unit
that buys a second position once price is 0.5R beyond the breakout level, stop at the level
(mirrors the gold add-ons). Mondays and no-trend add trades but lower the profit per trade
and 2024-25. On the broker's H1 feed 2019-26 (coarse bars, a cross-check only): live PF 2.42,
re-entry 2.48; the add-on PF 2.92 on 2021-25 but -4.1R in 2026 on hourly bars.

In the live portfolio (USDJPY at 4% unless noted):

| candidate                              | avg month 21-23 | 24-25        | 2026         | max DD 21-23 / 24-25 / 2026 | verdict |
|----------------------------------------|-----------------|--------------|--------------|-----------------------------|---------|
| **re-entry replaces live**             | 3.92 -> 4.05    | 6.34 -> 6.54 | 7.04 -> 7.04 | unchanged                   | **applied** |
| + add-on @0.5R sleeve                  | 4.52            | 6.37         | 7.02         | -16.9 / -19.7 / -8.5        | rejected: loses alone in 2026 |
| no trend replaces live                 | 4.48            | 5.94         | 12.63        | -18.4 / -21.1 / -10.9       | option |
| no trend + re-entry replaces live      | 4.61            | 6.16         | 12.45        | -18.4 / -21.1 / -11.0       | option |
| no trend + re-entry, at 3% risk        | 4.48            | 6.00         | 11.61        | -18.1 / -20.2 / -10.5       | option |

Applied: the second try (`slot_max_trades: 2`, `max_trades_per_day: 2`). It only changes
days where the first breakout was stopped and price broke out again; 2021-25 that was 6
extra trades worth +7.5R, none in 2026 so far.
Not applied: dropping the 50-day trend filter. It nearly doubles USDJPY's trades and its
2021-25 total (+42R vs +36R), and 2026 alone is +25R vs +6R, but the profit per trade
halves (0.31R vs 0.50R), 2024-25 is lower and the drawdowns deepen 1-2.4 points. One
period down and 2026 carrying the case is not enough under the rules; it is written up in
`config.yaml` (`trend_sma: null`) to revisit when 2026 is a full year. By year the no-trend
version beat the live one in 2021 (+7.8R vs 0), 2022, 2024 and 2026 and lost a little in 2023
and 2025.

### Gold trend: more pyramiding, a faster system, intraday entries

| variant (1% risk)             | trades/yr | PF 21-25 | yrs up | R 2021-23 | R 2024-25 | 2026 H1 | 2019-20 H1 |
|-------------------------------|-----------|----------|--------|-----------|-----------|---------|------------|
| 55/20 (live)                  | 4.8       | 3.51     | 4/5    | +0.3      | +14.7     | +4.5    | +7.1       |
| 20/10 (live)                  | 6.4       | 2.93     | 4/5    | +1.2      | +17.0     | +4.7    | +7.2       |
| add55 @0.5R (live)            | 4.0       | 3.21     | 2/5    | -2.4      | +16.6     | +6.9    | +7.2       |
| add20 @0.5R (live)            | 4.2       | 8.28     | 4/5    | +5.9      | +22.1     | +9.0    | +9.2       |
| 10/5 long (faster)            | 8.8       | 3.03     | 4/5    | +3.4      | +18.6     | +5.2    | +4.7       |
| 55/20 intraday entry          | 5.4       | 3.25     | 4/5    | +0.5      | +16.3     | +4.5    | +3.8       |
| 20/10 intraday entry          | 7.6       | 2.47     | 2/5    | -0.5      | +18.5     | +5.1    | +5.9       |
| 55/20 trailing stop only      | identical to live: the 20-day exit never fires before the stop |
| add55 @1.0R / @1.5R           | 3.0 / 2.8 | 3.50 / 1.36 | 4 / 2 | +0.6 / -0.4 | +6.9 / +1.6 | +3.5 / +2.0 | +0.1 / +0.2 |
| add20 @1.0R / @1.5R           | 4.0 / 3.4 | 2.68 / 1.11 | 4 / 2 | -0.7 / -1.5 | +8.1 / +2.2 | +3.6 / +1.8 | +2.6 / +3.2 |

In the live portfolio (gold already at 4% risk and 22% margin, so more gold crowds out
other trades):

| candidate                      | avg month 21-23 | 24-25       | 2026        | max DD 21-23 / 24-25 / 2026 |
|--------------------------------|-----------------|-------------|-------------|-----------------------------|
| + 10/5 sleeve                  | 3.92 -> 4.36    | 6.34 -> 6.87 | 7.04 -> 6.89 | -15.9 / -20.6 / -8.6        |
| 10/5 replaces 20/10            | 3.83            | 6.38        | 7.08        | -16.4 / -19.4 / -8.5        |
| + add55 @1.0R                  | 4.24            | 6.43        | 7.03        | -16.6 / -19.7 / -8.6        |
| + add20 @1.0R                  | 3.97            | 6.34        | 7.04        | unchanged                   |
| + both @1.0R                   | 4.26            | 6.44        | 7.03        | -16.8 / -19.7 / -8.6        |
| 55/20 intraday replaces 55/20  | 3.95            | 6.08        | 6.94        | -17.3 / -19.7 / -8.5        |

The 10/5 sleeve is the best near-miss: +0.4-0.5 points a month on 2021-25 but 2026 slightly
lower and a 0.9-point deeper 2024-25 drawdown. Not applied (rule: all three periods up); it
sits in `config.yaml` as a commented-out sleeve. The 1.0R add-ons add little; 1.5R nothing.

### Weekend gap fade (new idea): rejected

`fxbot/strategies/weekend_gap.py`. Sunday open vs Friday close; fade the gap towards Friday's
close if it is still >= 0.15 / 0.3 x daily ATR 15 or 60 min after the reopen; target the full
gap or half of it; stop 1:1; out Monday 20:00. 40 settings x 5 markets (EUR, GBP, JPY, AUD,
gold), 2021-25, 5-min bars: 27 lose, median PF 0.49-0.98 on four markets. GBPUSD median PF 1.6
with one setting at PF 6.75 (5 trades a year, neighbours PF 1.06-1.33): selection, not an edge.
Gaps do fill, but the Sunday spread and the big news gaps that don't fill eat it.

### 28 more markets, every live strategy untouched (round 2): nothing to add

Copper, US natural gas, heating oil (no history), UK oil, sugar, coffee (spread 5%: unusable),
US2000, HK50 (history from Sept 2025 only), AUS200, China A50, FRA40, ESP35, SWISS20, and
USD/CAD, USD/CHF, NZD/USD, AUD/USD, EUR/GBP, EUR/AUD, GBP/AUD, EUR/CAD, GBP/CAD, AUD/NZD,
EUR/CHF, GBP/CHF, AUD/CAD, NZD/JPY, CHF/JPY (EUR/NZD, GBP/NZD not downloaded in time).
8 strategies x 28 markets on the broker's H1 feed 2019-26, same pass rule as round 1.
Passed: China A50 trend 55/20 (PF 1.50, 6/7 years, but 3.7 trades a year and 1 trade in 2026)
and UK oil trend 55/20 (PF 1.23, 0.07R a trade): both too thin, like US oil in round 1.
USD/CAD vol breakout: PF 2.13, 6/7 years, then -3.0R on 6 trades in 2026. ESP35 breakout
PF 6.4 at a 3% win rate is a data artefact (gaps in the index history).
CHF/JPY daily pullback passed on 2019-26 (PF 2.27, 5/7, 2026 PF 1.15) and has complete history
from 2011: over 2011-26 it is PF 1.04, 9/16 years (`run_chfjpy_pullback.py`). A lucky window.
Pullback on USD/JPY and AUD/USD (histdata, GBP settings): PF 0.83 and 1.14, both negative 2024-26.

### London stack

- Breakout "ran > 15 pips past the range by 10:30" cap, current config: 15 (live) +27.5% /
  +14.2% (2021-23 / 2024-25), 20: +27.8 / +12.0, 25: +24.2 / +10.7, 35: +22.3 / +11.8,
  off: +24.7 / +12.3. The cap stays (the old robustness table said otherwise, on the old config).
- The London stack on pairs it never traded (`run_london_crosses.py`, broker 15-min feed
  Nov 2022 - Nov 2026, live settings, no SMT partner; EURUSD / GBPUSD on the same feed PF 1.47 /
  1.41): AUDUSD PF 1.28 but 0.07R a trade and 2 losing years of 5, USDCHF 1.14, NZDUSD 1.09,
  USDCAD 0.97, EURGBP 0.24. None.
- Breakout on AUDUSD with the USDJPY rules (histdata 2021-25 + 2026): PF 0.52. No.

## Nov 13 2026 (night) - Leeway on the London thresholds: rejected

`run_leeway.py`. Every London threshold loosened by the same share at once (Sweep min
reward/risk and max stop, Breakout min/max range and the 15-pip "already ran" cap). EUR + GBP,
1% risk, histdata. Extra trades = trades the live rules would not take.

| leeway | trades | extra trades | extra R | 2021-23 ret / PF | 2024-25 ret / PF |
|--------|--------|--------------|---------|------------------|------------------|
| 0 (live) | 291  | -            | -       | +27.5% / 1.43    | +14.2% / 1.40    |
| 0.5%   | 298    | 8            | +0.3    | +25.5% / 1.38    | +15.6% / 1.44    |
| 2%     | 312    | 25           | -3.5    | +24.4% / 1.35    | +13.0% / 1.34    |
| 5%     | 334    | 52           | -1.5    | +26.9% / 1.35    | +13.2% / 1.32    |
| 10%    | 368    | 91           | -2.4    | +34.7% / 1.42    | +5.7% / 1.11     |
| 20%    | 421    | 153          | +2.2    | +41.2% / 1.41    | +3.1% / 1.05     |

The near-misses are break-even trades as a group: more trades, no more profit, and 2024-25
falls apart from 10% on. 0.5% is noise (one period up, one down). The live thresholds stay.

## Nov 14 2026 - Optimising the London limits, walk-forward: live limits kept

`run_london_optimize.py`. 155 settings: Breakout min range 16-28 pips x max range 60/80/100/none
x "already ran" cap 10-25/none, and Sweep min reward/risk 1.0-2.0 x max stop 20-40 pips.
Score = total R at 1% risk, EURUSD + GBPUSD. Each test year uses the limits that scored best
(as a plateau: the setting plus its grid neighbours) on the years BEFORE it only; 2026 uses the
broker's own M5/M15 feed.

| test year | limits picked on | picked Breakout (min / max range, cap) | picked R | live R |
|-----------|------------------|----------------------------------------|----------|--------|
| 2023      | 2021-22          | 16 / 100 / none (124 trades vs 53)     | +3.2     | +3.4   |
| 2024      | 2021-23          | 16 / 100 / 20                          | -3.4     | +0.6   |
| 2025      | 2021-24          | 16 / none / 15                         | +11.8    | +16.3  |
| 2026      | 2021-25          | 16 / 100 / 15 (53 trades vs 37)        | +8.9     | +10.3  |

The optimiser always wants a lower minimum range (16 pips) to get more trades. It wins on the
years it was picked on (best 2021-25: +53.2R vs live +44.6R) and loses to the live limits in
every one of the four unseen years. All of the top 10 settings on 2021-25 made less than the live
limits in 2026 (+4.9 to +9.7R vs +10.3R). Sweep: min reward/risk 1.25 or 1.5 with any max stop
gives the same within 1.3R over 5 years (2 trades); 1.0 loses 6-9R. Nothing changed.

## Nov 14 2026 - "Stop after 3 losses in a row": rejected

`run_loss_streak.py`, every live trade 2021-2026, full portfolio replay (real margin, brake).
Next trade after a streak: after a win +0.16 / +0.53R (2021-23 / 2024-26), after 2 losses +0.39 /
+0.47R, after 3+ losses +0.17 / +0.38R. Trades after a streak are still winners on average.

| rule | trades skipped | R of the skipped trades | avg month 21-23 / 24-25 / 2026 (live 4.06 / 6.54 / 7.04) |
|------|----------------|-------------------------|-----------------------------------------------------------|
| per strategy, 3 losses, wait until a skipped trade would have won | 66 | +16.9 | 3.20 / 6.82 / 6.21 |
| per strategy, 3 losses, skip next 2 | 58 | +15.3 | 3.97 / 6.40 / 6.13 |
| per strategy, 4 losses, skip next 2 | 29 | +0.8 | 3.98 / 6.82 / 6.62 |
| account, 3 losses, pause 1 day | 20 | +13.3 | 2.98 / 6.22 / 6.53 (2026 DD -11.1 vs -8.5) |
| account, 3 losses, pause 7 days | 79 | +31.0 | 1.77 / 6.57 / 6.51 |

Every version throws away profitable trades and none is better in all three periods. The risk
brake (smaller trades while the account is below its peak) already handles bad stretches.

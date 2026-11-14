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
| USDJPY | Volatility breakout (Larry Williams), k 0.9 | 15 min | Entries 05:00-12:00 London, breakeven at +1R |

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

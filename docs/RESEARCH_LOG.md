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

## Why strategies fail here (diagnosis of every strategy tried, 2021-23)

- 57% have no edge even before costs (coin flips): no filter or exit can fix them.
- 12% have a small gross edge (+0.07-0.2R) eaten by 0.1-0.3R of spread per trade
  (mostly opening-range breakouts trading 100-200 times a year).
- 11% work - the live bots are drawn from this group.
- Ways left to add profit: lower trading costs (raw-spread account), time (compounding),
  and genuinely new strategy ideas. More markets for the proven strategies was tried on
  12 Nov 2026 (JPY crosses, indices, silver, oil): none passed.

# Research history (2021-2025 development tests)

Moved out of the README in Nov 2026 to keep it readable. Newer tests are in RESEARCH_LOG.md.

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

### News filter comparison
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

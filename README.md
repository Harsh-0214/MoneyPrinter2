# MoneyPrinter2: an automatic trading bot

MoneyPrinter2 is a program that trades for you, by itself, on a **FOREX.com demo account**
(practice money, in Canadian dollars) through the **MetaTrader 5** app. It watches prices
around the clock, opens a trade when one of its rules says "now", protects every trade with an
automatic exit, and closes it later. You don't have to press anything.

> **Status (Nov 2026):** running on the demo account. No real money yet. The plan is to watch it
> for 2–3 months and check that its real trades match what the tests predicted.

---

## The basics in 2 minutes

**What is being traded?** Prices that move every day:

| Market | What it is | Bot buys when it expects... |
|---|---|---|
| **EURUSD** | the euro measured in US dollars | the euro to rise against the dollar |
| **GBPUSD** | the British pound in US dollars | the pound to rise against the dollar |
| **XAUUSD** | gold, in US dollars per ounce | gold to rise |
| **USDJPY** | the US dollar measured in Japanese yen | the dollar to rise against the yen |

The bot can also **sell first** (called "going short"), which makes money when the price *falls*.
It never owns real euros or gold; it holds a contract that pays the price difference (a **CFD**).

**How does it make money?** Each market has its own simple rules, found by testing on years of
past prices. In everyday words:

- **EURUSD and GBPUSD: the London morning move.** Overnight, while London sleeps, prices stay in
  a quiet range. When London opens (8 am UK time), they often break out of that range and keep
  going for a while. The bot joins that move, and gets out by the evening at the latest.
  It also catches the opposite case: a quick fake-out past the range that snaps back.
- **GBPUSD: buy the dip.** When the pound is in a long uptrend and suddenly drops sharply for
  1–3 days, it often bounces back. The bot buys the dip and sells the bounce (up to 10 days).
- **Gold: ride the trend.** When gold reaches its highest price in 20 or 55 days, it often keeps
  rising for weeks. The bot buys and holds until the trend fades. When a trend trade is already
  in profit, it adds a second, smaller-risk trade to the winner. Gold is buy-only: selling gold
  lost money in every test.
- **USDJPY: the big-move breakout.** If the dollar/yen moves unusually far from where the day
  started (in the direction of its longer trend), it often keeps going until evening. The bot
  joins it and closes everything at 9 pm UK time. If that first attempt is stopped out and the
  price breaks out again the same day, it takes one second try.

**How often does it trade?** About 100 trades a year across all four markets, roughly 8–9 a month.
Several quiet days in a row are normal. Gold trades only a few times a year but holds for weeks.

---

## What to expect (be realistic)

Tests on past prices (2021–2026, including all trading costs) gave:

| Period | Average month | Worst drop from a high point |
|---|---|---|
| 2021–2023 | +3.9% | −17% |
| 2024–2025 | +6.3% | −20% |
| 2026 (prices never used to design the rules) | +7.0% | −9% |

What that means for a $50,000 account:

- **An average month** in the tests was roughly +$2,000 to +$3,500, but months vary a lot:
  some make much more, and some lose money.
- **Losing streaks happen.** Expect stretches where the account falls 20–30% below its best
  point before it recovers. That is normal for this kind of system, not a sign it is broken.
- **Real results usually come in below the tests.** Real prices, delays and costs are messier
  than the past data. Planning on about half the test numbers is sensible.
- **8% or more every month is not realistic.** That would be about 150% a year, which almost
  nobody sustains. Pushing for it means taking risks that can wipe out most of the account.
- **Roughly half of all trades lose.** The system makes money because the winners are bigger
  than the losers, not because it is usually right.

---

## How it protects the money

- **Every trade has an automatic exit for losses (a "stop loss")**, sent to the broker together
  with the trade. Even if the laptop dies, the broker closes the trade at that price.
- **Each trade can lose at most 3% of the account** (4% for gold and USDJPY) if its stop is hit.
- **It slows down when things go badly.** When the account is 8% below its best point, trades
  get smaller (2%), then 1% at 15% down, then 0.5% at 20% down. Full size returns after it recovers.
- **Emergency stop:** 28% below its best point, it stops opening new trades entirely.
- **Total risk limit:** all open trades together can never risk more than 12% of the account.
- **Skips bad moments:** no new trades 30 minutes around big news (like US jobs or interest-rate
  announcements), or when the broker's prices are unusually expensive.
- **Stops for the day** after a 2% loss in one day.

---

## Using it day to day

| I want to... | Do this |
|---|---|
| **Start the bots** | Double-click `start_bots.bat`. It opens MetaTrader and 4 windows, one per market. |
| **Stop the bots** | Double-click `stop_bots.bat`. Open trades stay open (their stop losses still protect them). |
| **See what each bot is thinking** | Look at its window. It explains itself in plain sentences ("waiting for...", "wants to BUY because..."). |
| **See it on the charts** | In MetaTrader, the **FxbotOverlay** indicator draws the levels the bot is watching, trade entries, stop losses, targets and upcoming news. |
| **See today's important events** | Open `logs/journal_<date>.log`. |
| **Check how it's doing** | Run `python run_report.py`. It compares the real trades with what the tests expected. |

The "boing" sound in MetaTrader means a trade was opened, changed or closed.

**Keeping it running 24/7 on the laptop:**
1. Keep the laptop **plugged in**, set to **never sleep** when plugged in.
2. Set closing the lid to **"Do nothing"** when plugged in (Power Options).
3. **Windows updates restart the computer** and stop the bots (one update cost 7.5 hours in
   Nov 2026). Pause updates, or set active hours.
4. **After a restart the bots don't come back by themselves** unless you have created the
   Windows Task Scheduler task that runs `start_bots.bat` at login. Otherwise, start them by hand.
5. MetaTrader must be set to remember its password.

**Golden rule:** don't change settings after a few losing trades or a quiet week. Changing rules
because of a short bad stretch is the most common way people break a working system.

---

## Before using real money

1. Let the demo run **2–3 months**.
2. Run `python run_report.py` every few weeks and check the real trades match the tests
   (same trades, same timing, similar results).
3. If they match, start with **an amount you could lose 30% of without it hurting**.
4. Keep long-term savings in ordinary index funds (for example in a TFSA). Treat the bot as a
   side bet, not a replacement for them.

A real-money account is blocked unless you deliberately turn it on twice
(`--allow-live` and `live.allow_live: true` in `config.yaml`).

---

## What was tried and didn't work

About 600 tests were run with the same strict rules (all costs included, rules fixed before
testing, checked on years not used to design them). Only the strategies above passed. Things that
**did not** work:

- The same strategies on other markets: stock indexes (S&P 500, NASDAQ, Dow, Germany, UK, Japan),
  silver, oil, other yen pairs.
- Calendar patterns: start/end of month, overnight moves, days before US interest-rate decisions.
- Trading the first minutes after the US stock market opens.
- Following or betting against what big traders hold (the weekly CFTC "COT" report).
- **Carry trade** (buy high-interest currencies, short low-interest ones): earned nothing since
  2007 even before the broker's cut, with a −34% crash in 2008.
- **Trading big news** (jobs, inflation, central banks): following the first 15-minute move
  and betting against it both lost. The market prices the news within minutes.
- **Individual stocks** (Apple, Nvidia, Exxon...): trend, dip-buying, news-gap and "pairs"
  strategies. On big US companies, simply owning the stocks beat every trading strategy tested.
  Holding the strongest 3 each month did better than holding all of them, but that suits real
  shares in an investment account, not this bot (stock CFDs charge about 7% a year to hold).
- **Weekend gaps** (betting that Sunday's opening jump closes back to Friday's price): lost on
  4 of 5 markets. The Sunday spread and the big news gaps that never close eat the edge.
- **28 more markets** (copper, natural gas, UK oil, sugar, coffee, 7 more stock indexes, 17
  currency pairs such as USD/CAD and EUR/GBP) with the strategies that already work: nothing
  solid. A CHF/JPY dip-buying result looked good on 2019-26 and fell apart on 2011-18.
- **Squeezing more out of gold and USDJPY**: a faster gold system, bigger gold "add to winners",
  entering gold during the day instead of at the daily close, and adding to USDJPY winners.
  Some looked good alone, but in the whole account gold already uses most of the margin, and the
  USDJPY add-on lost every trade in 2026. The one thing that did pass, a second USDJPY try after
  a same-day stop-out, is now live. Dropping USDJPY's trend filter (twice the trades, much better
  2026, slightly worse 2024-25 and deeper dips) is written up in `config.yaml` as an option.

Details of every test: `docs/RESEARCH_LOG.md` (and older ones in `docs/RESEARCH_HISTORY.md`).

---

## Words you'll see

| Word | Meaning |
|---|---|
| **Long / buy** | A trade that makes money if the price goes up. |
| **Short / sell** | A trade that makes money if the price goes down. |
| **Stop loss** | The automatic exit that limits a trade's loss. |
| **Target / take profit** | An automatic exit that locks in a profit at a set price. |
| **Breakeven** | Once a trade is far enough in profit, the bot moves its stop loss to the entry price, so the trade can no longer lose. |
| **R** | The amount a trade risks. "+2R" means it made twice what it risked; "−1R" means the stop was hit. |
| **Pip** | A tiny price step in currencies (0.0001 for EURUSD). 20 pips is a typical small move. |
| **Spread** | The small gap between the buy and sell price; it's the broker's fee on each trade. |
| **Lot** | A trade's size. The bot calculates it for you from the 3% rule. |
| **Margin** | Money the broker sets aside while a trade is open (a deposit, not a cost). |
| **Leverage** | Trading a position bigger than your cash, using margin. It makes gains and losses bigger. |
| **CFD** | A contract that pays the price change without owning the real thing. |
| **Drawdown** | How far the account has fallen from its highest point. |
| **Backtest** | Running the rules on past prices to see how they would have done. |
| **Demo account** | A practice account with fake money but real prices. |
| **Profit factor (PF)** | Money won ÷ money lost. Above 1 makes money; 1.5 is good. |
| **Magic number** | A label on each trade saying which strategy opened it (e.g. 12347 = gold trend). |
| **Asian range** | The high and low that a price makes overnight, before London opens. |
| **Trend / moving average** | The average price over the last N days; above it = uptrend, below = downtrend. |

A longer illustrated guide: **`docs/MoneyPrinter2_Guide.pdf`**.

---
---

# Technical reference

Everything below is for working on the code.

## Strategies and settings at a glance

| Market bot | Strategy | Bars | Trades/yr | Risk | Magic | When it trades |
|---|---|---|---|---|---|---|
| **EURUSD** | London Sweep + Breakout, daily trend filter | 15 min | ~20 | 3% | 12345 | 08:00–11:00 London; Sweep exits 16:00, Breakout 20:00 |
| **GBPUSD** | London Sweep + Breakout (SMT partner: EURUSD) | 5 min | ~38 | 3% | 12346 | same |
| | Daily swing pullback (RSI-2, 200-day trend) | 1 h | ~13 | 3% | 12446 | decides daily, holds 1–10 days |
| **XAUUSD** | Gold trend following, 55-day breakout, buy-only | 1 h | ~5 | 4% | 12347 | decides daily, holds weeks |
| | Gold trend following, 20-day breakout, buy-only | 1 h | ~6 | 4% | 12447 | same |
| | Add-on to the 55-day trend once it is +0.5R | 1 h | ~4 | 4% | 12547 | same |
| | Add-on to the 20-day trend once it is +0.5R | 1 h | ~4 | 4% | 12647 | same |
| **USDJPY** | Volatility breakout (day open ± 0.9 × yesterday's range), 50-day trend, second try after a stop-out | 15 min | ~16 | 4% | 12348 | 05:00–12:00 London, exits 21:00 |

In `config.yaml`, a market's main stack is its `pairs:` entry and each extra strategy is a
`sleeves:` item under it. A pair can override the global risk with its own `risk:` block.
Expected results come from `python run_portfolio.py` (every live strategy on one account,
compounding, risk brake, the broker's real margin per market: FX 5%, gold 22%).

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

### 4. Daily swing pullback (GBPUSD:pullback)
- **Trend:** the daily close versus its 200-day average.
- **Entry:** in an uptrend, buy when the 2-day RSI of daily closes drops below 10
  (a sharp 1–3 day dip). In a downtrend, sell when it rises above 90.
- **Exit:** a daily close back above (or below) the 5-day average, or after 10 days.
  There's a protective stop at 1.5× the daily ATR (was 3×: smaller losses, PF 1.61).
- **Why it's here:** most trades win, and its monthly returns are uncorrelated
  with the London stack, so it smooths the portfolio.
- The EURUSD version was removed in Nov 2026 (won small, lost big, negative in 2026).

### 5. Fast gold trend (XAUUSD:fast)
The same rules as the 55-day gold trend, but with a 20-day breakout entry and a
10-day low exit. It catches shorter gold trends the slow system misses.
2021–2025 alone: +18.1%, PF 2.94, max drawdown −3.6%. Correlation with the rest
of the portfolio is +0.35, because both are gold trend systems.

### 6. Gold add-ons (XAUUSD:add55, XAUUSD:add20)
"Adding to winners": on the same signal as each gold trend, buy a second position once the
trend trade is +0.5R in profit, with its stop at the main trade's entry price. It then trails
and exits like the main trade. Portfolio sim with margin and the risk brake (2021–25): average
month 3.9% → 4.9%, max drawdown unchanged.

### 7. USDJPY volatility breakout (USDJPY)
- **Levels:** buy at today's open + 0.9 × yesterday's range, sell at the open − 0.9 × range.
  Only in the direction of the 50-day trend; Mondays skipped.
- **Window:** entries 05:00–12:00 London (every window ending at 12:00 beat later ones;
  12–16 London is the US-data whipsaw). Everything closes at 21:00.
- **Stop:** 0.5 × yesterday's range; moves to entry at +1R. No fixed target (the best
  breakouts run past 2–3R).
- **Second try (Nov 13 2026):** if the first breakout is stopped out and a candle closes beyond
  the level again the same day, it enters once more (`slot_max_trades: 2`, `max_trades_per_day: 2`).
  2021–25: PF 2.35 → 2.52, +7.5R from 6 extra trades, 4/5 years up (was 3/5); 2026 unchanged.
- 2021–25: PF 2.52, max drawdown −5%; 2026 out-of-sample +6.8%. Its monthly returns are
  close to uncorrelated with the rest of the portfolio (−0.08).
- Option, not applied: `trend_sma: null` (trade against the 50-day trend too) doubles the
  trades, 2021–25 +42R vs +36R and 2026 +25R vs +6R, but halves the profit per trade and
  deepens the portfolio drawdowns 1–2.4 points (docs/RESEARCH_LOG.md, Nov 13 evening).
- The same rule lost on EURUSD, GBPUSD and gold (see docs/RESEARCH_HISTORY.md), so it trades USDJPY only.


### Position sizing and risk limits
- **Per trade:** 3% of equity (`risk.risk_per_trade_pct`), 4% on gold and USDJPY (their
  `risk:` override). `live.equity_cap: null` sizes on the real account equity, so profits
  compound and losses shrink trades. Converted to the account currency (CAD) with MT5's own rate:
  `units = equity × risk% / (stop distance × USD→CAD)`. Gold units are ounces (1 lot = 1 oz).
- **Risk brake** (`live.risk_brake`): while the account is below its peak, trades shrink:
  8% down → 2% risk, 15% down → 1%, 20% down → 0.5%. Full size again within 8% of the peak.
- **Circuit breaker:** no new trades at all 28% below the peak (`live.max_drawdown_pct`).
- **Portfolio risk cap:** before any order, the bot adds up what every open bot position would
  lose at its stop (all markets and magic numbers). If that plus the new trade exceeds
  `live.max_open_risk_pct` (12%), the trade is skipped and logged as `RISK CAP`. Positions whose
  stop is already at or past entry count as zero.
- **Margin cap:** entries shrink or skip so all open trades use at most 70% of equity as margin
  (`live.max_margin_used_pct`). Broker margin: FX 5%, gold 22%, US indices 10%.
- A 2% daily loss stops new entries for the rest of the day.

## Setup from a fresh clone
```
git clone https://github.com/Harsh-0214/MoneyPrinter2.git
cd MoneyPrinter2
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # fill in MT5 login, password, server, terminal path
python -m pytest -q             # 104 tests
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
start_bots.bat                                 # MT5 + one bot per market (4), auto-restart on crash
stop_bots.bat                                  # stop the bots (positions are left alone)
python run_live.py --pair XAUUSD --dry-run     # one bot, log only
python run_live.py --pair GBPUSD --sleeve pullback   # just one of a market's strategies (testing)
python run_report.py                           # demo results vs backtest expectations
```
- Each market bot runs all of its strategies in one loop, exactly like the backtest
  (`route_morning`). Each strategy uses its own bar timeframe (5 min or 1 h).
  EURUSD and GBPUSD's London stacks use each other as the SMT feed.
- Only closed bars are used. Missed bars are caught up. On startup and after every
  reconnect each strategy replays today's bars, or `warmup_days` of history for the daily strategies.
- Each strategy has its own magic number, so its trades are labelled separately in MT5.
  Main stacks are `live.magic` + the pair's index (EURUSD 12345, GBPUSD 12346, XAUUSD 12347,
  USDJPY 12348); sleeve j adds 100×j (GBP pullback 12446; gold fast 12447, add55 12547, add20 12647).
- One log per market bot: `logs/live_<PAIR>_<date>.log`. Each line is tagged with the strategy
  (`[London]`, `[Pullback]`, `[Trend 55d]`, `[Trend 20d]`, `[Breakout]`, ...). One chart file per market: `fxbot_<SYMBOL>.txt`.
- A second copy for the same pair refuses to start, so trades can't be doubled.
- **Terminal = plain English.** Each market window narrates in short `# ...` lines: startup,
  what each strategy is waiting for, "wants to SELL ... because ...", safety checks, trade size,
  fills, stop moves, closes with P/L, skips (news / spread / risk cap) and a daily summary.
  The technical log stays in the log file (`--verbose` also prints it in the terminal).
- **Journal:** `logs/journal_<date>.log` collects the important events of all four markets
  in one file. The FxbotOverlay indicator also prints them into MT5's **Experts** tab
  (from `fxbot_events_<SYMBOL>.txt`). Orders and fills also appear in MT5's own Journal tab.
- **Spread guard:** no new entry while the live spread is above `live.max_spread_mult`
  (2.5×) the pair's normal spread.
- **Drawdown circuit breaker:** smaller trades from 8% below the peak (risk brake), and no new
  trades at all once the account is `live.max_drawdown_pct` (28%) below its peak. The peak is in `data/state/peak_equity.json`;
  delete that file to resume after investigating.
- **Stall watchdog:** if the market is open but no new candles arrive for 20 min
  (3 h for hourly strategies), the bot reconnects to MT5.
- **Daily summary** per market at the start of each London day: closed trades, P/L, open trades, equity.
- **Fresh-data check:** `python run_oos_mt5.py` re-runs the live portfolio on 2026 data from
  MT5 that was never used for tuning (Jan 1 - Nov 11 2026: +17.0%, PF 2.60, max DD -4.7%).
- **Chart overlay:** attach the `FxbotOverlay` indicator (in `mt5/`, installed and
  compiled into MT5) to a chart. It draws the lines each bot is watching (ranges, breakout levels,
  trend averages), time lines (range end, entry cutoff, session exits), upcoming high-impact news,
  and for open trades the entry, stop, target and +1R breakeven level, plus a status panel.
  Every trade's stop loss is sent with the order, so it sits at the broker from the first second.
- **Logs:** `logs/live_<PAIR>_<date>.log`, with `STATUS` lines (what the bot sees),
  `ORDER` / `Order filled`, `Stop moved`, and `CLOSED` lines with P/L.
- **24/7:** `start_bots.bat` at Windows login (Task Scheduler: you have to create the task
  yourself), the PC set never to sleep on AC power, lid close = "Do nothing" when plugged in,
  and MT5 set to remember its password. Windows Update restarts stop the bots (one cost 7.5 h
  in Nov 2026): pause updates or schedule active hours. The bots don't restart on their own
  after a reboot unless the Task Scheduler task exists.
- **News calendar:** the bots share one downloaded calendar; a lock file makes sure only one bot
  downloads at a time (four at once got rate-limited).
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
run_calendar_effects.py  turn-of-month, overnight, pre-FOMC, gold by hour, month-end fix (research, none passed)
run_index_orb.py         NASDAQ / S&P / Dow opening-range breakout (research, rejected)
fetch_cot.py / run_cot.py      CFTC positioning data + 4 positioning tests (research, rejected)
fetch_mt5_stocks.py      broker H1 history for big US stocks -> data/mt5/stocks/
run_stocks.py            live strategies + momentum rotation on big US stocks (research, rejected)
run_stock_edges.py       stock-specific strategies: RSI-2 dip, IBS, gap drift, pairs (research, rejected)
run_carry.py             carry trade across 8 currencies, OECD rates (research, rejected)
run_news_reaction.py     follow / fade the first 15 min after big news (research, rejected)
fetch_mt5_extra.py       NZD daily + 2026 five-minute bars for the two tests above
fetch_mt5_more.py        broker H1 for 29 more markets + M15 for the live pairs and 5 crosses
run_more_trades.py       variants of the live units (re-entry, add-ons, faster gold, intraday, weekend gap)
run_portfolio_add.py     what a candidate unit adds to the live portfolio (margin, brake, 4% gold/JPY)
run_london_more.py       London Breakout "ran too far" cap re-test (15 stays)
run_london_crosses.py    London stack on AUD/CAD/CHF/NZD/EURGBP (broker M15, rejected)
run_chfjpy_pullback.py   CHFJPY pullback 2011-2026 long-history check (rejected)
docs/RESEARCH_LOG.md     every test, its rules and result (older: docs/RESEARCH_HISTORY.md)
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
  strategies/  london_sweep.py  london_breakout.py  trend_follow.py (gold)  daily_patterns.py (pullback, USDJPY breakout)
               (+ opening_range, trend_pullback, key_levels, tiny_range_fade, weekend_gap,
                  london_close_reversal, ny_breakout, prev_day, mean_reversion: tested, unused)
tests/                   104 unit tests
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
- `python run_news_test.py` reruns the news-settings comparison (results in `docs/RESEARCH_HISTORY.md`).

## Simulator assumptions (deliberately pessimistic)
- Signals fill at the next bar's open. Buys pay the ask. The spread widens to 3 pips at NY rollover.
- Stops fill with slippage, or at the open if price gaps through.
- If the stop and target are both hit in the same bar, the stop counts.
- Overnight swap is charged at the 17:00 New York rollover (triple on Wednesday). The intraday stack never pays it.
- News spikes are not modelled (the news filter only changes which entries are allowed).

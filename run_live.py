"""Live/demo runner.

    python run_live.py                       # demo account, EURUSD (default)
    python run_live.py --pair GBPUSD         # trade another pair from cfg['pairs']
    python run_live.py --dry-run             # log actions without sending orders
    python run_live.py --allow-live          # required to run on a real account

Runs the SAME morning stack and scored routing as the backtest
(cfg['strategies']['morning'] + fxbot.backtest.route_morning), including the
SMT feed from the pair's partner symbol. Run one process per pair; each pair
gets its own magic number (live.magic + index in cfg['pairs']).

Credentials are loaded from .env (see .env.example).
"""
import argparse
import logging
import os
import time
import zoneinfo
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

LONDON = zoneinfo.ZoneInfo("Europe/London")


def _setup_logging(tag):
    Path("logs").mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"logs/live_{tag}_{today}.log"),
        ],
    )
    return logging.getLogger("fxbot")


log = logging.getLogger("fxbot")


class DryRunBroker:
    """Wraps MT5Broker and intercepts every order-changing call."""

    def __init__(self, real_broker):
        self._b = real_broker

    def equity(self):
        return self._b.equity()

    def position(self):
        return self._b.position()

    def current_spread_pips(self):
        return self._b.current_spread_pips()

    def submit(self, order):
        log.info("DRY RUN: would submit %s %d units SL=%.5f TP=%s tag=%s",
                 "BUY" if order.side == 1 else "SELL",
                 order.units, order.stop_loss,
                 f"{order.take_profit:.5f}" if order.take_profit else "None", order.tag)
        return False

    def close_position(self, reason="manual"):
        log.info("DRY RUN: would close position reason=%s", reason)

    def update_stop(self, new_stop_price):
        log.info("DRY RUN: would move stop to %.5f", new_stop_price)

    def shutdown(self):
        self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


class CappedEquityBroker:
    """Make the bot size and risk-check as if the account were `cap` dollars.

    Reported equity = cap + (real equity - real equity at start), so 0.5% risk
    means 0.5% of ~cap, and the daily-loss kill switch works on the same base.
    """

    def __init__(self, broker, cap):
        self._b = broker
        self._cap = float(cap)
        self._start = broker.equity()

    def equity(self):
        return self._cap + (self._b.equity() - self._start)

    def position(self): return self._b.position()
    def current_spread_pips(self): return self._b.current_spread_pips()
    def submit(self, order): return self._b.submit(order)
    def close_position(self, reason="manual"): return self._b.close_position(reason)
    def update_stop(self, new_stop_price): return self._b.update_stop(new_stop_price)
    def shutdown(self): return self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


class PortfolioRiskGuard:
    """Refuses a new order if all bots' open risk plus this trade would exceed the cap.

    Open risk = what each open bot position (any of our magic numbers, any market)
    would lose if its stop were hit now, in account currency. A position whose stop
    is at or past its entry (breakeven / trailing) counts as zero.
    """

    def __init__(self, broker, mt5, magics, cap_money, new_trade_risk):
        self._b, self._mt5, self._magics = broker, mt5, set(magics)
        self._cap, self._new = cap_money, new_trade_risk

    def open_risk(self):
        mt5 = self._mt5
        total = 0.0
        for p in mt5.positions_get() or []:
            if p.magic not in self._magics or not p.sl:
                continue
            side = 1 if p.type == mt5.ORDER_TYPE_BUY else -1
            if (p.sl - p.price_open) * side >= 0:          # stop at/through entry: no risk left
                continue
            loss = mt5.order_calc_profit(p.type, p.symbol, p.volume, p.price_open, p.sl)
            total += abs(loss or 0.0)
        return total

    def submit(self, order):
        used = self.open_risk()
        if used + self._new > self._cap + 1e-6:
            log.warning("RISK CAP: %.0f already at risk + %.0f new > cap %.0f - trade skipped",
                        used, self._new, self._cap)
            return False
        return self._b.submit(order)

    def equity(self): return self._b.equity()
    def position(self): return self._b.position()
    def current_spread_pips(self): return self._b.current_spread_pips()
    def close_position(self, reason="manual"): return self._b.close_position(reason)
    def update_stop(self, new_stop_price): return self._b.update_stop(new_stop_price)
    def shutdown(self): return self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


class _NoOrderBroker:
    """Used while replaying today's bars at startup: state only, no orders."""

    def __init__(self, broker):
        self._b = broker
        self.trades = []

    def equity(self): return self._b.equity()
    def position(self): return self._b.position()
    def current_spread_pips(self): return self._b.current_spread_pips()
    def submit(self, order): return False
    def close_position(self, reason=""): pass
    def update_stop(self, new_stop_price): pass


def _sleep_to_next_bar(timeframe_minutes=5):
    """Sleep until 5 seconds after the next bar boundary."""
    now = datetime.now(timezone.utc).timestamp()
    bar_s = timeframe_minutes * 60
    wait = bar_s - (now % bar_s) + 5
    time.sleep(wait)


def _london_local(ts_utc):
    """Return (numpy datetime64[D], minutes since midnight) in London time.

    Same types the backtest passes to strategies.
    """
    import numpy as np
    local = ts_utc.astimezone(LONDON)
    return np.datetime64(local.date(), "D"), local.hour * 60 + local.minute


_EMA_CACHE = {}


def _add_daily_ema(mt5, symbol, cfg, bars):
    """Add the daily-trend column the strategies filter on, computed exactly like
    the backtest (fxbot.backtest.daily_ema_series) from ~320 days of H1 closes.
    Recomputed once per UTC day per symbol."""
    import pandas as pd
    from fxbot.backtest import daily_ema_series, trend_period
    from fxbot.data import server_ts_to_utc

    period = trend_period(cfg)
    key = (symbol, period, pd.Timestamp.now(tz="UTC").date())
    ema = _EMA_CACHE.get(key)
    if ema is None:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 24 * 320)
        if rates is None or len(rates) == 0:
            log.warning("No H1 history for %s - daily trend filter has no data", symbol)
            return
        h1 = pd.DataFrame(rates)
        h1.index = server_ts_to_utc(h1["time"].values)
        h1 = h1[h1.index.notna()]
        ema = daily_ema_series(h1["close"], period)
        for k in [k for k in _EMA_CACHE if k[2] != key[2]]:
            del _EMA_CACHE[k]
        _EMA_CACHE[key] = ema
        uses_trend = any(s.get("ema_filter") or s.get("daily_trend_filter")
                         for s in cfg.get("strategies", {}).get("morning", []))
        if uses_trend:
            log.info("Daily trend: %d-day average of %s = %.5f", period, symbol, ema.iloc[-1])
    bars["daily_ema"] = ema.reindex(bars.index, method="ffill")


def _fetch_completed_bars(mt5, symbol, smt_symbol, cfg, start_utc):
    """M1 bars since start_utc -> completed 5-min bars with spread + SMT columns.

    The still-forming M1 bar and the still-forming 5-min bar are dropped, so a
    strategy never sees a partial candle (the backtest only sees closed bars).
    """
    import pandas as pd
    from fxbot.brokers import compute_spread_pips
    from fxbot.data import resample, server_ts_to_utc

    tf = cfg["data"]["timeframe"]
    tf_delta = pd.Timedelta(tf)
    # Timeframes MT5 serves directly (gold runs on 1h); others are built from M1
    native = {"1h": getattr(mt5, "TIMEFRAME_H1", None), "15min": getattr(mt5, "TIMEFRAME_M15", None)}
    mt_tf = native.get(tf) or mt5.TIMEFRAME_M1

    def _m1(sym):
        # Pad the start: MT5 indexes by server time (UTC+2/+3)
        rates = mt5.copy_rates_range(sym, mt_tf,
                                     (start_utc - timedelta(hours=4)).replace(tzinfo=None),
                                     (datetime.now(timezone.utc) + timedelta(hours=4)).replace(tzinfo=None))
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df.index = server_ts_to_utc(df["time"].values)
        df = df[df.index.notna()]
        cols = ["open", "high", "low", "close"]
        if "spread" in df.columns:
            df["data_spread_pips"] = df["spread"] / 10.0
            cols.append("data_spread_pips")
        return df[cols].iloc[:-1]          # drop the forming M1 bar

    m1 = _m1(symbol)
    if m1 is None or len(m1) == 0:
        return None
    bars = m1.copy() if mt_tf != mt5.TIMEFRAME_M1 else resample(m1, tf)
    now = pd.Timestamp.now(tz="UTC")
    bars = bars[bars.index + tf_delta <= now]          # completed bars only
    bars = bars[bars.index >= pd.Timestamp(start_utc)]
    bars["spread_pips"] = compute_spread_pips(bars, cfg["costs"])

    _add_daily_ema(mt5, symbol, cfg, bars)

    if smt_symbol:
        s1 = _m1(smt_symbol)
        if s1 is not None and len(s1):
            sb = (s1 if mt_tf != mt5.TIMEFRAME_M1 else resample(s1, tf))[["high", "low"]].reindex(bars.index)
            bars["smt_high"] = sb["high"]
            bars["smt_low"] = sb["low"]
    return bars


def _log_status_changes(strategies, local_min, last, logger=None):
    """Log each strategy's 'what I see' line whenever it changes."""
    now = {}
    for s in strategies:
        if not hasattr(s, "describe"):
            continue
        try:
            st = s.describe(local_min).get("status", "")
        except Exception:
            continue
        now[type(s).__name__] = st
        if st and last.get(type(s).__name__) != st:
            (logger or log).info("STATUS %s", st)
    return now


def _log_closed_trade(broker, logger=None):
    """A position disappeared (stop / target hit at the broker, or our close)."""
    try:
        trades = broker.trades
    except Exception:
        trades = []
    if not trades:
        (logger or log).info("CLOSED position (no deal details available)")
        return
    t = trades[-1]
    (logger or log).info("CLOSED %s %s %d units: entry %.5f -> exit %.5f  P/L %.2f  reason=%s",
             t.tag, "BUY" if t.side == 1 else "SELL", t.units, t.entry_price,
             t.exit_price, t.pnl, t.exit_reason)


def _overlay_path(mt5, symbol):
    """<MT5 common data>/Files/fxbot_<symbol>.txt, read by the FxbotOverlay indicator."""
    info = mt5.terminal_info()
    if info is None or not getattr(info, "commondata_path", None):
        return None
    d = Path(info.commondata_path) / "Files"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"fxbot_{symbol}.txt")


def _build_morning(cfg):
    from fxbot.backtest import STRATEGY_MAP, instrument_pip
    pip = instrument_pip(cfg)
    if "strategies" in cfg:
        return [STRATEGY_MAP[s["name"]](s, pip) for s in cfg["strategies"]["morning"]]
    s = cfg["strategy"]
    return [STRATEGY_MAP[s.get("name", "london_breakout")](s, pip)]


def _pair_entry(cfg, pair_name):
    pairs = cfg.get("pairs") or [{"symbol": "EURUSD"}]
    names = [p["symbol"] for p in pairs]
    if pair_name not in names:
        raise SystemExit(f"--pair {pair_name} not in config pairs {names}")
    return names.index(pair_name), pairs[names.index(pair_name)], names


def _broker_symbol(cfg, pair):
    return pair.get("broker_symbol") or pair["symbol"] + cfg["live"].get("symbol_suffix", ".")


def _resolve_pair(cfg, pair_name):
    """Return (broker_symbol, smt_broker_symbol, magic) for the chosen pair."""
    idx, pair, names = _pair_entry(cfg, pair_name)
    smt_path = (pair.get("smt") or {}).get("path", "")
    smt_name = next((n for n in names if n != pair_name and n in smt_path), None)
    smt_sym = _broker_symbol(cfg, _pair_entry(cfg, smt_name)[1]) if smt_name else None
    return (_broker_symbol(cfg, pair), smt_sym, int(cfg["live"]["magic"]) + idx)


def _unit(cfg, pair, sleeve=None):
    """The unit (market main stack or one of its sleeves) this process trades."""
    from fxbot.backtest import expand_units
    key = f"{pair}:{sleeve}" if sleeve else pair
    units = {u["key"]: u for u in expand_units(cfg)}
    if key not in units:
        raise SystemExit(f"{key} is not configured. Options: {list(units)}")
    return units[key]


STRATEGY_LABELS = {"london_sweep": "London", "london_breakout": "London",
                   "daily_pullback": "Pullback", "trend_follow": "Trend"}


def _label(unit_cfg):
    specs = unit_cfg["strategies"]["morning"]
    names = []
    for s in specs:
        lab = STRATEGY_LABELS.get(s["name"], s["name"])
        if s["name"] == "trend_follow":
            lab = f"Trend {s.get('entry_days', 55)}d"
        if lab not in names:
            names.append(lab)
    return "+".join(names)


class _Prefixed(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['tag']}] {msg}", kwargs


class StrategyRunner:
    """One strategy group inside a market's bot (e.g. EURUSD's London stack, or its
    daily pullback). Keeps its own state, bar timeframe and MT5 magic number, so its
    trades are tracked separately in the account and it can hold a position at the
    same time as the market's other strategies. The market bot runs all of them in
    one loop; each one only trades when its own setup appears."""

    def __init__(self, full_cfg, unit, symbol, smt_symbol, all_magics, dry_run, allow_live):
        from fxbot.backtest import instrument_pip, pair_config
        self.unit, self.symbol, self.smt_symbol = unit, symbol, smt_symbol
        self.all_magics, self.dry_run, self.allow_live = all_magics, dry_run, allow_live
        self.cfg = pair_config(full_cfg, unit)
        self.cfg["live"] = dict(self.cfg["live"], symbol=symbol, magic=unit["magic"])
        self.label = _label(self.cfg)
        self.log = _Prefixed(log, {"tag": self.label})
        self.pip = instrument_pip(self.cfg)
        self.warmup_days = int(self.cfg.get("warmup_days", 0))
        self.slot_limit = int(self.cfg.get("slot_max_trades", 1))

    # ------------------------------------------------------------------ startup
    def connect(self, mt5):
        from fxbot.backtest import route_morning
        from fxbot.brokers.mt5_broker import MT5Broker
        from fxbot.risk import RiskManager
        cfg = self.cfg
        self.real_broker = MT5Broker(cfg, self.log, allow_live=self.allow_live)
        broker = DryRunBroker(self.real_broker) if self.dry_run else self.real_broker
        cap = cfg["live"].get("equity_cap")
        if cap:
            broker = CappedEquityBroker(broker, cap)
        max_open = cfg["live"].get("max_open_risk_pct")
        if max_open:
            base = float(cap or broker.equity())
            broker = PortfolioRiskGuard(broker, mt5, self.all_magics, float(max_open) / 100 * base,
                                        float(cfg["risk"]["risk_per_trade_pct"]) / 100 * base)
        self.broker = broker
        for s in [self.symbol] + ([self.smt_symbol] if self.smt_symbol else []):
            mt5.symbol_select(s, True)

        # Fresh strategy objects, then replay closed bars (today for the London
        # stack, `warmup_days` of history for daily strategies) to rebuild state.
        self.morning = _build_morning(cfg)
        r_cfg = dict(cfg["risk"])
        if "min_units" in cfg.get("instrument", {}):
            r_cfg["min_units"] = cfg["instrument"]["min_units"]
        self.risk = RiskManager(r_cfg, self.pip)
        now_local = datetime.now(timezone.utc).astimezone(LONDON)
        self.day_start_utc = now_local.replace(hour=0, minute=0, second=0,
                                               microsecond=0).astimezone(timezone.utc)
        bars = _fetch_completed_bars(mt5, self.symbol, self.smt_symbol, cfg,
                                     self.day_start_utc - timedelta(days=self.warmup_days))
        replay = _NoOrderBroker(broker)
        self.risk.new_day(broker.equity())
        self.fired_day, self.cur_day, self.last_ts = None, None, None
        if bars is not None:
            for bar in bars.itertuples():
                day, lmin = _london_local(bar.Index.to_pydatetime())
                self.cur_day = day
                self.fired_day = route_morning(self.morning, bar, day, lmin, replay, self.risk,
                                               self.fired_day, self.slot_limit)
                self.last_ts = bar.Index
        if broker.position() is not None and self.cur_day is not None:
            self.fired_day = self.cur_day           # a position from today uses the slot
            for s in self.morning:
                s.mark_fired()
        self.risk.quote_to_account = self.real_broker.quote_to_account()
        self.log.info("ready: magic=%d timeframe=%s replayed=%d bars, last=%s, position=%s",
                      self.unit["magic"], cfg["data"]["timeframe"],
                      0 if bars is None else len(bars), self.last_ts,
                      "open" if broker.position() is not None else "none")
        self.last_status = _log_status_changes(self.morning, _london_local(datetime.now(timezone.utc))[1],
                                               {}, self.log)

    # ------------------------------------------------------------------ each poll
    def step(self, mt5):
        from fxbot.backtest import route_morning
        since = self.last_ts.to_pydatetime() if self.last_ts is not None else self.day_start_utc
        bars = _fetch_completed_bars(mt5, self.symbol, self.smt_symbol, self.cfg,
                                     since - timedelta(minutes=10))
        if bars is None:
            self.log.warning("No bars from MT5, retrying next poll")
            return
        broker = self.broker
        new = bars[bars.index > self.last_ts] if self.last_ts is not None else bars
        had_pos = broker.position() is not None
        if len(new):
            live_spread = broker.current_spread_pips()
            self.risk.quote_to_account = self.real_broker.quote_to_account()
        for k, bar in enumerate(new.itertuples()):
            day, lmin = _london_local(bar.Index.to_pydatetime())
            if day != self.cur_day:
                self.cur_day = day
                self.risk.new_day(broker.equity())
            if k == len(new) - 1:
                # Size the newest bar's order on the actual live spread
                bar = bar._replace(spread_pips=max(bar.spread_pips, live_spread))
            self.fired_day = route_morning(self.morning, bar, day, lmin, broker, self.risk,
                                           self.fired_day, self.slot_limit)
            self.last_ts = bar.Index
        if had_pos and broker.position() is None:
            _log_closed_trade(broker, self.log)
        self.last_status = _log_status_changes(self.morning, _london_local(datetime.now(timezone.utc))[1],
                                               self.last_status, self.log)

    def overlay_lines(self):
        from fxbot.overlay import build_lines
        lmin = _london_local(datetime.now(timezone.utc))[1]
        lines = build_lines(self.morning, lmin, self.broker, self.symbol)[1:]   # drop per-runner header
        return [f"STATUS|[{self.label}] {l[7:]}" if l.startswith("STATUS|") else l for l in lines]


def run(cfg, pair="EURUSD", dry_run=False, allow_live=False, sleeve=None):
    """One bot per market: runs every strategy configured for `pair` (its main
    London/trend stack plus its `sleeves`) in a single loop."""
    import MetaTrader5 as mt5
    from fxbot.backtest import expand_units

    units = [u for u in expand_units(cfg)
             if u["market"] == pair and (sleeve is None or u["sleeve"] == sleeve)]
    if not units:
        raise SystemExit(f"No strategies configured for {pair}{':' + sleeve if sleeve else ''}")
    symbol, smt_symbol, _ = _resolve_pair(cfg, pair)
    all_magics = {u["magic"] for u in expand_units(cfg)}
    runners = [StrategyRunner(cfg, u, symbol, None if u["sleeve"] else smt_symbol,
                              all_magics, dry_run, allow_live) for u in units]
    cap = cfg["live"].get("equity_cap")
    log.info("%s bot: %d strateg%s - %s | symbol=%s smt=%s | sizing base %s | dry_run=%s",
             pair, len(runners), "y" if len(runners) == 1 else "ies",
             ", ".join(f"{r.label} (magic {r.unit['magic']})" for r in runners),
             symbol, smt_symbol, cap or "real equity", dry_run)

    failures = 0
    while True:
        try:
            for r in runners:
                r.connect(mt5)
            acct = mt5.account_info()
            log.info("Account currency %s: 1 %s move per unit = %.4f %s (sizing uses this)",
                     acct.currency, symbol[3:6], runners[0].risk.quote_to_account, acct.currency)
            overlay_path = _overlay_path(mt5, symbol)
            _remove_stale_overlays(overlay_path)

            def _draw():
                if overlay_path is None:
                    return
                try:
                    from fxbot.overlay import write_overlay
                    lines = [f"STATUS|fxbot {pair} | {len(runners)} strategies | "
                             f"updated {time.strftime('%H:%M:%S')}"]
                    for r in runners:
                        lines += r.overlay_lines()
                    write_overlay(overlay_path, lines)
                except Exception as e:          # drawing must never stop trading
                    log.warning("overlay write failed: %s", e)

            _draw()
            log.info("Bot started. equity=%.2f", runners[0].broker.equity())
            failures = 0
            while True:
                _sleep_to_next_bar()
                for r in runners:
                    r.step(mt5)
                b = runners[0].broker
                log.info("Poll %s London | spread %.1f pips | open: %s | equity %.2f",
                         datetime.now(timezone.utc).astimezone(LONDON).strftime("%H:%M"),
                         b.current_spread_pips(),
                         ", ".join(r.label for r in runners if r.broker.position() is not None) or "none",
                         b.equity())
                _draw()

        except KeyboardInterrupt:
            log.info("Bot stopped cleanly.")
            try:
                mt5.shutdown()
            except Exception:
                pass
            break

        except Exception as exc:
            failures += 1
            log.error("Error (failure %d/5): %s", failures, exc, exc_info=True)
            try:
                mt5.shutdown()
            except Exception:
                pass
            if failures >= 5:
                log.error("5 consecutive failures - exiting.")
                break
            log.info("Reconnecting in 60s...")
            time.sleep(60)


def _remove_stale_overlays(path):
    """Old per-strategy overlay files (fxbot_<SYMBOL>_<sleeve>.txt) would double-draw."""
    if not path:
        return
    import glob
    for f in glob.glob(path[:-4] + "_*.txt"):
        try:
            os.remove(f)
        except OSError:
            pass


def _single_instance_lock(pair):
    """Exclusive lock file per pair; returns the open handle, or None if taken.
    The OS releases it automatically when the process exits (even on a crash)."""
    Path("logs").mkdir(exist_ok=True)
    f = open(f"logs/.run_live_{pair}.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--pair", default="EURUSD")
    ap.add_argument("--sleeve", default=None,
                    help="extra strategy on that market, e.g. pullback (EURUSD/GBPUSD) or fast (XAUUSD)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-live", action="store_true")
    args = ap.parse_args()

    tag = f"{args.pair}_{args.sleeve}" if args.sleeve else args.pair
    global log
    log = _setup_logging(tag)
    lock = _single_instance_lock(tag)              # keep the handle open for the process life
    if lock is None:
        log.error("Another run_live.py is already running for %s - exiting so trades "
                  "aren't doubled. Close the other one first.", tag)
        raise SystemExit(2)
    cfg = yaml.safe_load(open(args.config))
    if args.allow_live and not cfg["live"].get("allow_live", False):
        raise SystemExit("--allow-live also requires live.allow_live: true in config.yaml")
    run(cfg, pair=args.pair, dry_run=args.dry_run, allow_live=args.allow_live, sleeve=args.sleeve)


if __name__ == "__main__":
    main()

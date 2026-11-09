"""Live/demo runner.

    python run_live.py                  # demo account (default)
    python run_live.py --dry-run        # log actions without sending orders
    python run_live.py --allow-live     # required to run on a real account

Credentials are loaded from .env (see .env.example).
"""
import argparse
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


def _setup_logging():
    Path("logs").mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"logs/live_{today}.log"),
        ],
    )
    return logging.getLogger("fxbot")


log = _setup_logging()


class DryRunBroker:
    """Wraps MT5Broker and intercepts order submission for dry-run mode."""

    def __init__(self, real_broker):
        self._b = real_broker

    def equity(self):
        return self._b.equity()

    def position(self):
        return self._b.position()

    def current_spread_pips(self):
        return self._b.current_spread_pips()

    def submit(self, order):
        log.info("DRY RUN: would submit %s %d units SL=%.5f TP=%s",
                 "BUY" if order.side == 1 else "SELL",
                 order.units, order.stop_loss,
                 f"{order.take_profit:.5f}" if order.take_profit else "None")
        return False

    def close_position(self, reason="manual"):
        log.info("DRY RUN: would close position reason=%s", reason)

    def shutdown(self):
        self._b.shutdown()

    @property
    def trades(self):
        return self._b.trades


def _next_bar_close(timeframe_minutes=5):
    """Sleep until 30 seconds after the next 5-minute bar closes."""
    now = datetime.now(timezone.utc)
    seconds_since_epoch = now.timestamp()
    bar_seconds = timeframe_minutes * 60
    seconds_into_bar = seconds_since_epoch % bar_seconds
    wait = bar_seconds - seconds_into_bar + 30
    target = datetime.fromtimestamp(now.timestamp() + wait, tz=timezone.utc)
    log.info("Waiting %.0fs for next bar close at %s", wait, target.strftime("%H:%M:%S"))
    time.sleep(wait)


def _london_local(ts_utc):
    """Return (date, minutes_since_midnight) in London time."""
    import zoneinfo
    london = zoneinfo.ZoneInfo("Europe/London")
    local = ts_utc.astimezone(london)
    return local.date(), local.hour * 60 + local.minute


def _replay_startup(broker, strategy, risk, cfg, pip):
    """Replay today's closed bars to rebuild strategy state without placing orders."""
    import MetaTrader5 as mt5
    import numpy as np
    import pandas as pd
    from fxbot.data import resample, server_ts_to_utc

    symbol = cfg["live"]["symbol"]
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    rates = mt5.copy_rates_range(
        symbol,
        mt5.TIMEFRAME_M1,
        today_start.replace(tzinfo=None),
        now_utc.replace(tzinfo=None),
    )
    if rates is None or len(rates) == 0:
        log.info("Startup replay: no bars yet today")
        return

    df = pd.DataFrame(rates)
    df.index = server_ts_to_utc(df["time"].values)
    df = df.drop(columns=["time"])
    df = df.rename(columns={"tick_volume": "volume"})
    if "spread" in df.columns:
        df["data_spread_pips"] = df["spread"] / 10.0

    bars = resample(df[["open", "high", "low", "close"] +
                        (["data_spread_pips"] if "data_spread_pips" in df.columns else [])],
                    cfg["data"]["timeframe"])

    atr_period = cfg["strategy"].get("atr_period", 14)
    tr = pd.concat([
        bars["high"] - bars["low"],
        (bars["high"] - bars["close"].shift()).abs(),
        (bars["low"] - bars["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    bars["atr"] = tr.ewm(span=atr_period, adjust=False).mean()
    if "data_spread_pips" not in bars.columns:
        bars["data_spread_pips"] = cfg["costs"]["spread_pips"]
    bars["spread_pips"] = bars["data_spread_pips"]

    # Wrap broker so no real orders go out during replay
    class _NoOrderBroker:
        def equity(self): return broker.equity()
        def position(self): return broker.position()
        def current_spread_pips(self): return broker.current_spread_pips()
        def submit(self, order): return False
        def close_position(self, reason=""): pass

    replay_broker = _NoOrderBroker()
    equity = broker.equity()
    risk.new_day(equity)

    for ts, bar in bars.iterrows():
        local_day, local_min = _london_local(ts)
        strategy.on_bar(bar, local_day, local_min, replay_broker, risk)

    hi = strategy.hi if strategy.hi != float("-inf") else float("nan")
    lo = strategy.lo if strategy.lo != float("inf") else float("nan")
    log.info(
        "Startup replay: %d bars, range hi=%.5f lo=%.5f, trades_today=%d, open_position=%s",
        len(bars), hi, lo, strategy.trades_today,
        "yes" if broker.position() is not None else "no",
    )


def _session_summary(broker, start_equity, log):
    trades = broker.trades
    equity = broker.equity()
    pnl = equity - start_equity
    log.info(
        "Session summary: trades=%d pnl=%.2f equity=%.2f",
        len(trades), pnl, equity,
    )


def run(cfg, dry_run=False, allow_live=False):
    from fxbot.backtest import STRATEGY_MAP
    from fxbot.brokers.mt5_broker import MT5Broker
    from fxbot.data import PIP, resample
    from fxbot.risk import RiskManager
    import pandas as pd

    pip = PIP
    s_name = cfg["strategy"].get("name", "london_breakout")
    strategy_cls = STRATEGY_MAP.get(s_name)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy '{s_name}'. Options: {list(STRATEGY_MAP)}")
    strategy = strategy_cls(cfg["strategy"], pip)
    risk = RiskManager(cfg["risk"], pip)

    consecutive_failures = 0
    current_day = None
    day_start_equity = None
    session_summary_logged = False

    while True:
        try:
            real_broker = MT5Broker(cfg, log, allow_live=allow_live)
            broker = DryRunBroker(real_broker) if dry_run else real_broker

            _replay_startup(broker, strategy, risk, cfg, pip)

            equity = broker.equity()
            current_day = date.today()
            day_start_equity = equity
            risk.new_day(equity)
            consecutive_failures = 0
            session_summary_logged = False

            log.info("Bot started. equity=%.2f dry_run=%s", equity, dry_run)

            import MetaTrader5 as mt5
            from fxbot.data import server_ts_to_utc as _sts_to_utc

            while True:
                _next_bar_close()

                symbol = cfg["live"]["symbol"]
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 300)
                if rates is None:
                    log.warning("Failed to fetch bars from MT5, retrying next bar")
                    continue

                df = pd.DataFrame(rates)
                df.index = _sts_to_utc(df["time"].values)
                df = df.drop(columns=["time"])
                if "spread" in df.columns:
                    df["data_spread_pips"] = df["spread"] / 10.0

                bars = resample(
                    df[["open", "high", "low", "close"] +
                       (["data_spread_pips"] if "data_spread_pips" in df.columns else [])],
                    cfg["data"]["timeframe"],
                )
                if len(bars) == 0:
                    log.warning("Resample returned 0 bars, skipping")
                    continue

                atr_period = cfg["strategy"].get("atr_period", 14)
                tr = pd.concat([
                    bars["high"] - bars["low"],
                    (bars["high"] - bars["close"].shift()).abs(),
                    (bars["low"] - bars["close"].shift()).abs(),
                ], axis=1).max(axis=1)
                bars["atr"] = tr.ewm(span=atr_period, adjust=False).mean()

                spread = broker.current_spread_pips()
                if "data_spread_pips" not in bars.columns:
                    bars["data_spread_pips"] = cfg["costs"]["spread_pips"]
                bars["spread_pips"] = bars["data_spread_pips"]
                bars.loc[bars.index[-1], "spread_pips"] = spread

                bar = bars.iloc[-1]
                ts = bar.name
                local_day, local_min = _london_local(ts)

                today_utc = datetime.now(timezone.utc).date()
                if today_utc != current_day:
                    current_day = today_utc
                    equity = broker.equity()
                    day_start_equity = equity
                    risk.new_day(equity)
                    session_summary_logged = False
                    log.info("New trading day. equity=%.2f", equity)

                equity = broker.equity()
                log.info(
                    "Bar %s spread=%.1fpip position=%s equity=%.2f",
                    ts.strftime("%H:%M"),
                    spread,
                    "open" if broker.position() is not None else "none",
                    equity,
                )

                # Session exit summary (once per day)
                session_exit_min = strategy.session_exit
                if local_min >= session_exit_min and not session_summary_logged:
                    _session_summary(broker, day_start_equity, log)
                    session_summary_logged = True

                strategy.on_bar(bar, local_day, local_min, broker, risk)

        except KeyboardInterrupt:
            log.info("Bot stopped cleanly.")
            try:
                broker.shutdown()
            except Exception:
                pass
            break

        except Exception as exc:
            consecutive_failures += 1
            log.error("Error (failure %d/5): %s", consecutive_failures, exc, exc_info=True)
            try:
                broker.shutdown()
            except Exception:
                pass
            if consecutive_failures >= 5:
                log.error("5 consecutive failures — exiting.")
                break
            log.info("Reconnecting in 60s...")
            time.sleep(60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-live", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    run(cfg, dry_run=args.dry_run, allow_live=args.allow_live)


if __name__ == "__main__":
    main()

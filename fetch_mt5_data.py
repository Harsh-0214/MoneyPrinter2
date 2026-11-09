"""Download EUR/USD 1-minute bars from your MetaTrader 5 terminal (Windows only).

    python fetch_mt5_data.py --start 2021-01-01 --end 2025-12-31 --symbol EURUSD.

The MT5 terminal must be open, logged in, and you must have opened an M1 chart
for the symbol and scrolled back to load the full history before running this.

Timestamps in the CSV are broker SERVER time (source_tz: NY+7 for FOREX.com).
Progress and any warnings are written to logs/fetch_YYYYMMDD_HHMMSS.log as well
as printed to the console.
"""
import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _setup_logging():
    Path("logs").mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"logs/fetch_{stamp}.log"
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)],
    )
    return logging.getLogger("fetch"), log_path


def main():
    log, log_path = _setup_logging()

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD.")  # FOREX.com uses EURUSD. (trailing dot)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data/EURUSD_M1.csv")
    ap.add_argument("--timeframe", default="M1", choices=["M1", "M5", "M15", "H1"])
    ap.add_argument("--retries", type=int, default=3,
                    help="Times to retry a month that returns suspiciously few bars")
    args = ap.parse_args()

    log.info("Log file: %s", log_path)
    log.info("Symbol: %s  timeframe: %s  range: %s -> %s  output: %s",
             args.symbol, args.timeframe, args.start, args.end, args.out)

    import MetaTrader5 as mt5
    TF_MAP = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
              "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1}
    timeframe = TF_MAP[args.timeframe]

    if not mt5.initialize():
        raise SystemExit(f"Could not connect to MT5: {mt5.last_error()}. Is the terminal open and logged in?")
    if not mt5.symbol_select(args.symbol, True):
        mt5.shutdown()
        raise SystemExit(
            f"Symbol '{args.symbol}' not found.\n"
            "Open Market Watch in MT5, find the symbol, right-click -> Show All if needed.\n"
            "Run:  python -c \"import MetaTrader5 as mt5; mt5.initialize(); "
            "print([s.name for s in mt5.symbols_get() if 'EUR' in s.name and 'USD' in s.name])\""
        )

    info = mt5.account_info()
    log.info("Connected | account=%d | server=%s | equity=%.2f", info.login, info.server, info.equity)

    months = pd.date_range(args.start, args.end, freq="MS").tolist()
    edges = (
        [pd.Timestamp(args.start)]
        + [m for m in months if m > pd.Timestamp(args.start)]
        + [pd.Timestamp(args.end) + pd.Timedelta(days=1)]
    )

    frames = []
    thin_months = []

    for a, b in zip(edges[:-1], edges[1:]):
        # Typical trading days in a month: ~21. At 1440 bars/day that's ~30k bars.
        # Fewer than 1000 likely means MT5 hasn't downloaded history for that period.
        rates = None
        for attempt in range(1, args.retries + 1):
            rates = mt5.copy_rates_range(
                args.symbol,
                timeframe,
                a.to_pydatetime().replace(tzinfo=timezone.utc),
                b.to_pydatetime().replace(tzinfo=timezone.utc),
            )
            n = 0 if rates is None else len(rates)
            if n >= 1000 or attempt == args.retries:
                break
            log.warning("  %s -> %s: only %d bars on attempt %d, retrying in 5s...",
                        a.date(), b.date(), n, attempt)
            time.sleep(5)

        n = 0 if rates is None else len(rates)
        status = "OK" if n >= 1000 else "THIN"
        log.info("  %s -> %s: %s bars [%s]", a.date(), b.date(), f"{n:,}", status)
        if status == "THIN":
            thin_months.append(str(a.date()))
        if n > 0:
            frames.append(pd.DataFrame(rates))

    mt5.shutdown()

    if not frames:
        raise SystemExit(
            "No data returned at all.\n"
            "Make sure you opened an M1 chart for the symbol in MT5 and scrolled\n"
            "all the way back (Home key) to trigger the history download, then retry."
        )

    df = pd.concat(frames).drop_duplicates("time")
    df["time"] = pd.to_datetime(df["time"], unit="s")   # broker server time (NY+7 for FOREX.com)
    df[["time", "open", "high", "low", "close", "tick_volume", "spread"]].to_csv(args.out, index=False)

    log.info("Saved %s bars to %s", f"{len(df):,}", args.out)
    if thin_months:
        log.warning(
            "%d month(s) had fewer than 1000 bars — history may be incomplete: %s",
            len(thin_months), ", ".join(thin_months),
        )
        log.warning("Open an M1 chart in MT5, press Home to load history, then re-run.")
    else:
        log.info("All months look complete. Run check_weekly_open.py next.")


if __name__ == "__main__":
    main()

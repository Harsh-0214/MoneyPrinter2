"""Chart overlay: strategies describe what they see; times map to MT5 server time."""
import pandas as pd
import yaml

from fxbot.backtest import _build_strategies, route_morning
from fxbot.brokers import SimBroker, compute_spread_pips
from fxbot.data import PIP, generate_synthetic, resample, server_ts_to_utc, utc_to_server_epoch
from fxbot.overlay import build_lines
from fxbot.risk import RiskManager


def test_server_epoch_roundtrip():
    for ts in ["2024-01-15 08:00", "2024-07-15 08:00", "2024-03-15 12:34"]:
        t = pd.Timestamp(ts, tz="UTC")
        assert server_ts_to_utc([utc_to_server_epoch(t)])[0] == t


def test_overlay_lines_after_a_morning():
    cfg = yaml.safe_load(open("config.yaml"))
    morning, _ = _build_strategies(cfg)
    bars = resample(generate_synthetic(start="2024-01-03", days=1), "5min")
    bars["spread_pips"] = compute_spread_pips(bars, cfg["costs"])
    broker = SimBroker(50000)
    risk = RiskManager(cfg["risk"], PIP)
    risk.new_day(50000)
    local = bars.index.tz_convert("Europe/London").tz_localize(None)
    fired = None
    for i, bar in enumerate(bars.itertuples()):
        if local[i].hour >= 9:
            break
        broker.on_bar(bar)
        day = local[i].to_datetime64().astype("datetime64[D]")
        fired = route_morning(morning, bar, day, local[i].hour * 60 + local[i].minute, broker, risk, fired)
    lines = build_lines(morning, 9 * 60, broker, "EURUSD.")
    kinds = [l.split("|")[0] for l in lines]
    assert kinds[0] == "STATUS"
    assert any(l.startswith("STATUS|Sweep:") for l in lines)
    assert any(l.startswith("STATUS|Breakout:") for l in lines)
    assert "BOX" in kinds and kinds.count("HLINE") >= 4
    for l in lines:
        if l.startswith("HLINE"):
            assert len(l.split("|")) == 5
        if l.startswith("BOX"):
            assert len(l.split("|")) == 7

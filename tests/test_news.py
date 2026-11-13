"""News filter: calendar parsing, UTC/DST conversion, currency filtering, blackout,
and the live feed's failure fallback (network is always mocked)."""
import json
import logging
import os

import pandas as pd
import pytest

import build_news_calendar as bnc
from fxbot import news
from fxbot.risk import RiskManager, resolve_news_currencies

BASE = {"risk_per_trade_pct": 1, "max_daily_loss_pct": 2, "max_leverage": 10, "min_units": 1}
T = pd.Timestamp


def _cal(rows):
    return news.normalize(pd.DataFrame(rows, columns=["time", "currency", "event"]))


def _rm(symbol=None, **kw):
    return RiskManager(dict(BASE, **kw), 0.0001, symbol)


# ------------------------------------------------------------------ parsing / UTC
FF_SAMPLE = [
    {"title": "CPI m/m", "country": "USD", "date": "2026-11-10T08:30:00-05:00", "impact": "High"},
    {"title": "GDP m/m", "country": "GBP", "date": "2026-11-12T02:00:00-05:00", "impact": "High"},
    {"title": "Sentix", "country": "EUR", "date": "2026-11-09T04:30:00-05:00", "impact": "Low"},
    {"title": "Bank Holiday", "country": "USD", "date": "2026-11-11T00:00:00-05:00", "impact": "Holiday"},
    {"title": "NFP", "country": "USD", "date": "2026-07-03T08:30:00-04:00", "impact": "High"},
    {"title": "broken", "country": "USD", "date": "not a date", "impact": "High"},
]


def test_parse_ff_json_keeps_high_impact_in_utc():
    df = news.parse_ff_json(FF_SAMPLE)
    assert list(df.event) == ["NFP", "CPI m/m", "GDP m/m"]       # sorted, low/holiday/broken dropped
    assert df.time.iloc[1] == T("2026-11-10 13:30", tz="UTC")     # EST -5
    assert df.time.iloc[0] == T("2026-07-03 12:30", tz="UTC")     # EDT -4
    assert df.time.iloc[2] == T("2026-11-12 07:00", tz="UTC")


def test_historical_dst_conversion():
    # NFP 08:30 New York: summer 12:30 UTC, winter 13:30 UTC
    assert bnc._utc("2024-07-05", "08:30", bnc.NY) == T("2024-07-05 12:30", tz="UTC")
    assert bnc._utc("2024-01-05", "08:30", bnc.NY) == T("2024-01-05 13:30", tz="UTC")
    # 2024-03-12: US already on summer time, UK not yet (US CPI 12:30 UTC = 12:30 London)
    assert bnc._utc("2024-03-12", "08:30", bnc.NY) == T("2024-03-12 12:30", tz="UTC")
    # BoE noon London: BST -> 11:00 UTC, GMT -> 12:00 UTC
    assert bnc._utc("2024-08-01", "12:00", bnc.LON) == T("2024-08-01 11:00", tz="UTC")
    assert bnc._utc("2024-02-01", "12:00", bnc.LON) == T("2024-02-01 12:00", tz="UTC")


def test_historical_calendar_contents():
    df = bnc.build()
    t = pd.to_datetime(df.time, utc=True)
    assert t.min() >= T("2021-01-01", tz="UTC") and t.max() <= T("2026-01-01", tz="UTC")
    counts = df.event.value_counts()
    assert counts["US Non-Farm Payrolls"] == 59 and counts["FOMC rate decision"] == 40
    assert counts["ECB rate decision"] == 40 and counts["BoE rate decision"] == 40
    assert counts["Eurozone flash CPI"] == 60
    # Eurostat flash 11:00 CET -> 10:00 UTC in winter
    assert T("2024-01-05 10:00", tz="UTC") in set(t[df.event == "Eurozone flash CPI"])
    ecb = t[df.event == "ECB rate decision"]
    assert T("2022-06-09 11:45", tz="UTC") in set(ecb)   # 13:45 CEST before the time change
    assert T("2022-07-21 12:15", tz="UTC") in set(ecb)   # 14:15 CEST after
    assert set(df.currency) == {"USD", "EUR", "GBP"}


def test_committed_calendar_matches_builder():
    path = "data/news/high_impact_2021_2025.csv"
    if not os.path.exists(path):
        pytest.skip("calendar not built")
    on_disk = news.load_calendar(path)
    built = news.normalize(bnc.build())
    assert len(on_disk) == len(built)
    assert (on_disk.time.values == built.time.values).all()


# ------------------------------------------------------------------ currencies
def test_currencies_for_symbol():
    assert news.currencies_for_symbol("EURUSD") == ["EUR", "USD"]
    assert news.currencies_for_symbol("GBPUSD.") == ["GBP", "USD"]
    assert news.currencies_for_symbol("XAUUSD") == ["USD"]
    assert resolve_news_currencies("auto", "XAUUSD") == ["USD"]
    assert resolve_news_currencies("all", "EURUSD") is None
    assert resolve_news_currencies(["usd"], "EURUSD") == ["USD"]
    assert resolve_news_currencies("auto", None) is None


CAL = [("2024-05-02 11:00", "GBP", "UK thing"), ("2024-05-02 09:00", "EUR", "EZ CPI"),
       ("2024-05-03 12:30", "USD", "US Non-Farm Payrolls")]


def test_currency_aware_blackout():
    for sym, blocked in [("EURUSD", {"EZ CPI", "US Non-Farm Payrolls"}),
                         ("GBPUSD", {"UK thing", "US Non-Farm Payrolls"}),
                         ("XAUUSD", {"US Non-Farm Payrolls"})]:
        r = _rm(sym, news_blackout_minutes=30)
        r.set_news(_cal(CAL))
        hits = {e for t, _, e in CAL if r.near_news(T(t, tz="UTC"))}
        assert hits == blocked, sym


def test_can_trade_blackout_window_and_callback():
    r = _rm("EURUSD", news_blackout_minutes=30)
    r.set_news(_cal(CAL))
    seen = []
    r.on_news_skip = lambda ev, t: seen.append(ev["event"])
    assert not r.can_trade(50000, T("2024-05-02 08:30", tz="UTC"))     # exactly 30 min before
    assert not r.can_trade(50000, T("2024-05-02 09:25", tz="UTC"))
    assert r.can_trade(50000, T("2024-05-02 09:31", tz="UTC"))
    assert r.can_trade(50000, T("2024-05-02 08:29", tz="UTC"))
    assert seen == ["EZ CPI", "EZ CPI"] and r.last_news_block["event"] == "EZ CPI"


def test_day_block_skips_whole_london_day():
    r = _rm("EURUSD", news_blackout_minutes=15, news_day_block=["payrolls"])
    r.set_news(_cal(CAL))
    assert r.near_news(T("2024-05-03 07:05", tz="UTC"))       # 08:05 London, NFP day
    assert not r.near_news(T("2024-05-02 07:05", tz="UTC"))   # not an NFP day


def test_legacy_news_file_still_works(tmp_path):
    p = tmp_path / "news.csv"
    p.write_text("time\n2024-01-05T13:30:00Z\n")
    r = _rm("EURUSD", news_file=str(p), news_blackout_minutes=30)
    assert r.near_news(T("2024-01-05 13:10", tz="UTC"))
    assert not r.near_news(T("2024-01-05 14:10", tz="UTC"))
    r.set_news(_cal(CAL))                                       # live calendar added, legacy kept
    assert r.near_news(T("2024-01-05 13:10", tz="UTC"))


def test_filter_off_by_default_ignores_calendar():
    r = _rm("EURUSD", news_calendar="data/news/high_impact_2021_2025.csv")
    assert len(r.news) == 0


def test_filter_on_loads_historical_calendar():
    path = "data/news/high_impact_2021_2025.csv"
    if not os.path.exists(path):
        pytest.skip("calendar not built")
    r = _rm("XAUUSD", news_filter=True, news_calendar=path)
    assert set(r.news_events.currency) == {"USD"}
    assert r.near_news(T("2024-01-05 13:30", tz="UTC"))       # NFP


# ------------------------------------------------------------------ live feed
class Clock:
    def __init__(self, t): self.t = t
    def __call__(self): return self.t


def test_live_calendar_caches_and_refreshes(tmp_path):
    calls = []
    clock = Clock(T("2026-11-10 06:00", tz="UTC").timestamp())

    def fetch(url):
        calls.append(url)
        return FF_SAMPLE
    cal = news.LiveCalendar(cache_dir=str(tmp_path), refresh_hours=4, fetch=fetch, now=clock)
    ev = cal.refresh()
    assert len(calls) == 1 and len(ev) == 3
    clock.t += 3600
    cal.refresh()
    assert len(calls) == 1                                      # cache still fresh
    # a restarted bot reads the cache instead of refetching
    cal2 = news.LiveCalendar(cache_dir=str(tmp_path), refresh_hours=4, fetch=fetch, now=clock)
    assert len(cal2.refresh()) == 3 and len(calls) == 1
    clock.t += 4 * 3600
    cal.refresh()
    assert len(calls) == 2


def test_live_calendar_network_failure_falls_back_to_cache(tmp_path, caplog):
    clock = Clock(T("2026-11-10 06:00", tz="UTC").timestamp())
    ok = news.LiveCalendar(cache_dir=str(tmp_path), fetch=lambda u: FF_SAMPLE, now=clock)
    ok.refresh()
    clock.t += 5 * 3600                                         # cache now stale

    def boom(url):
        raise ConnectionError("no internet")
    bad = news.LiveCalendar(cache_dir=str(tmp_path), fetch=boom, now=clock)
    with caplog.at_level(logging.WARNING, logger="fxbot"):
        ev = bad.refresh()
    assert len(ev) == 3                                         # stale cache used
    assert any("fetch failed" in r.getMessage() for r in caplog.records)


def test_live_calendar_failure_without_cache_means_no_filter(tmp_path):
    def junk(url):
        return json.loads("{not json")
    cal = news.LiveCalendar(cache_dir=str(tmp_path / "empty"), fetch=junk)
    ev = cal.refresh()
    assert len(ev) == 0
    r = _rm("EURUSD")
    r.set_news(ev)
    assert r.can_trade(50000, T("2026-11-10 13:30", tz="UTC"))


def test_live_status_line_and_skip_log(caplog):
    import run_live
    r = _rm("EURUSD", news_blackout_minutes=30)
    r.set_news(_cal(CAL))
    assert run_live.news_status_line(r, T("2024-05-02 09:10", tz="UTC")).startswith("NEWS: no new entries")
    assert "EZ CPI" in run_live.news_status_line(r, T("2024-05-02 06:00", tz="UTC"))
    runner = run_live.StrategyRunner.__new__(run_live.StrategyRunner)
    runner._news_logged, runner.risk = set(), r
    runner.log = logging.getLogger("fxbot")
    r.on_news_skip = runner._log_news_skip
    with caplog.at_level(logging.INFO, logger="fxbot"):
        r.can_trade(50000, T("2024-05-02 09:00", tz="UTC"))
        r.can_trade(50000, T("2024-05-02 09:05", tz="UTC"))     # same event: logged once
    msgs = [x.getMessage() for x in caplog.records if "NEWS: skipping entry" in x.getMessage()]
    assert len(msgs) == 1 and "EUR EZ CPI at 09:00 UTC" in msgs[0]


def test_live_calendar_bots_share_one_download(tmp_path, caplog):
    """Four bots whose caches expire together: only one downloads; a 429 makes all wait."""
    clock = Clock(T("2026-11-10 06:00", tz="UTC").timestamp())
    calls = []

    def fetch(url):
        calls.append(url)
        return FF_SAMPLE
    bots = [news.LiveCalendar(cache_dir=str(tmp_path), refresh_hours=4, fetch=fetch, now=clock) for _ in range(4)]
    bots[0].refresh()
    clock.t += 5 * 3600                                         # all caches stale at once
    for b in bots:
        assert len(b.refresh()) == 3
    assert len(calls) == 2                                      # first fill + ONE refresh, not four

    clock.t += 5 * 3600

    def limited(url):
        calls.append(url)
        raise RuntimeError("429 Client Error: Too Many Requests")
    for b in bots:
        b._fetch = limited
    with caplog.at_level(logging.WARNING, logger="fxbot"):
        for b in bots:
            assert len(b.refresh()) == 3                        # cache still served
    assert len(calls) == 3                                      # one attempt only
    clock.t += 20 * 60                                          # 20 min later: still backing off
    for b in bots:
        b.refresh()
    assert len(calls) == 3
    clock.t += 15 * 60                                          # 35 min: one bot may try again
    for b in bots:
        b.refresh()
    assert len(calls) == 4


def test_protect_open_trade_before_news():
    from types import SimpleNamespace
    from fxbot.brokers.base import Position
    from fxbot.risk import protect_before_news
    r = _rm("EURUSD"); r.set_news(news.normalize(pd.DataFrame({"time": [T("2026-11-10 13:30", tz="UTC")],
                                                              "currency": ["USD"], "event": ["US CPI"]})))
    class B:
        def __init__(self, tag): self.pos, self.done = Position(1, 1000, 1.1000, T("2026-11-10 09:00", tz="UTC"), 1.0950, 1.11, 0.005, 0.0, tag), []
        def position(self): return self.pos
        def close_position(self, reason=""): self.done.append(("close", reason))
        def update_stop(self, px, take_profit=None): self.done.append(("stop", px))
    r.news_protect = None
    b = B("long_break"); assert protect_before_news(r, b, T("2026-11-10 13:15", tz="UTC"), 1.1020) is None    # off
    r.news_protect = "breakeven_or_close"
    b = B("long_break"); assert protect_before_news(r, b, T("2026-11-10 12:00", tz="UTC"), 1.1020) is None    # too early
    b = B("long_break"); assert protect_before_news(r, b, T("2026-11-10 13:15", tz="UTC"), 1.1020) == "breakeven"
    assert b.done == [("stop", 1.1000)]
    b = B("long_break"); assert protect_before_news(r, b, T("2026-11-10 13:15", tz="UTC"), 1.0980) == "close"
    b = B("trend_long"); assert protect_before_news(r, b, T("2026-11-10 13:15", tz="UTC"), 1.0980) is None    # multi-day: skip


def test_only_one_bot_downloads_while_locked(tmp_path):
    """Bots wake in the same second: the one holding the lock downloads, the others wait."""
    calls = []

    def fetch(url):
        calls.append(url)
        return FF_SAMPLE

    a = news.LiveCalendar(cache_dir=str(tmp_path), fetch=fetch)
    b = news.LiveCalendar(cache_dir=str(tmp_path), fetch=fetch)
    lock = a._take_lock()
    assert lock is not None and b._take_lock() is None     # exclusive
    b.refresh()
    assert calls == []                                      # b didn't fetch while a held it
    a._release_lock(lock)
    a.refresh()
    assert len(calls) == 1 and len(a.events)
    b._last_try = 0
    b.refresh()                                             # cache fresh -> b just loads it
    assert len(calls) == 1 and len(b.events) == len(a.events)
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp") or f.endswith(".lock")]

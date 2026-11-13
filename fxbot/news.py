"""High-impact economic news calendar: historical CSV (backtests) and live feed.

Calendar format everywhere (CSV and DataFrame): columns
    time      UTC timestamp (ISO, e.g. 2024-03-08T13:30:00Z)
    currency  USD / EUR / GBP ... ("ALL" = relevant to every market)
    event     short name, e.g. "US Non-Farm Payrolls"

Historical file: data/news/high_impact_2021_2025.csv, built by build_news_calendar.py.
Live feed: the public Forex Factory weekly JSON (this week's events only; times are
New York local with a UTC offset). Fetched at most every `refresh_hours`, cached in
data/news/, and any failure falls back to the cache (or to no filter). Nothing here
may ever raise into the trading loop.
"""
import json
import logging
import os
import time

import pandas as pd

LIVE_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
USER_AGENT = "Mozilla/5.0 (compatible; fxbot-calendar/1.0)"     # generic, no personal info
FIAT = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"}
COLUMNS = ["time", "currency", "event"]

log = logging.getLogger("fxbot")


def currencies_for_symbol(symbol):
    """Currencies whose news moves this market: EURUSD -> [EUR, USD],
    'GBPUSD.' -> [GBP, USD], XAUUSD -> [USD] (gold reacts to US data)."""
    s = "".join(ch for ch in str(symbol or "").upper() if ch.isalpha())
    out = [c for c in (s[:3], s[3:6]) if c in FIAT]
    return out


def empty_calendar():
    return pd.DataFrame({"time": pd.to_datetime([], utc=True),
                         "currency": pd.Series([], dtype=object),
                         "event": pd.Series([], dtype=object)})


def normalize(df):
    """Any calendar-like frame -> sorted (time UTC, currency, event). A frame with only
    a `time` column (the old news_file format) applies to every market."""
    if df is None or len(df) == 0:
        return empty_calendar()
    out = pd.DataFrame({"time": pd.to_datetime(df["time"], utc=True)})
    out["currency"] = (df["currency"].astype(str).str.upper().str.strip()
                       if "currency" in df else "ALL")
    out["event"] = df["event"].astype(str) if "event" in df else "news"
    out = out.dropna(subset=["time"]).drop_duplicates().sort_values("time")
    return out.reset_index(drop=True)


def load_calendar(path):
    """Read a calendar CSV ('#' lines are comments). Missing file -> empty calendar."""
    if not path or not os.path.exists(path):
        return empty_calendar()
    return normalize(pd.read_csv(path, comment="#"))


def save_calendar(df, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    d = normalize(df)
    d = d.assign(time=d["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    tmp = f"{path}.{os.getpid()}.tmp"          # per-process: bots never share a temp file
    d[COLUMNS].to_csv(tmp, index=False)
    _replace_retry(tmp, path)


def _replace_retry(src, dst, tries=10):
    """os.replace, retried: on Windows it fails while another bot is reading dst."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                try:
                    os.remove(src)
                except OSError:
                    pass
                raise
            time.sleep(0.1 * (i + 1))


def filter_currencies(df, currencies):
    """Keep events for these currencies (plus 'ALL'). currencies=None keeps everything."""
    if currencies is None:
        return df
    want = {c.upper() for c in currencies} | {"ALL"}
    return df[df["currency"].isin(want)].reset_index(drop=True)


def parse_ff_json(items, impacts=("High",)):
    """Forex Factory weekly JSON (list of {title, country, date, impact, ...}, date like
    '2026-11-10T08:30:00-05:00') -> calendar frame of the chosen impact levels."""
    rows = []
    for it in items or []:
        try:
            if it.get("impact") not in impacts:
                continue
            t = pd.Timestamp(it["date"])
            t = t.tz_localize("America/New_York") if t.tzinfo is None else t
            rows.append({"time": t.tz_convert("UTC"),
                         "currency": str(it.get("country", "")).upper(),
                         "event": str(it.get("title", "news"))})
        except Exception:                   # one odd row must not lose the rest
            continue
    return normalize(pd.DataFrame(rows, columns=COLUMNS)) if rows else empty_calendar()


def _http_get_json(url, timeout=15):
    import requests
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                     timeout=timeout)
    r.raise_for_status()
    return r.json()


class LiveCalendar:
    """Upcoming high-impact events from the live feed, cached on disk.

    refresh() is cheap to call every poll: it only hits the network when the cache is
    older than refresh_hours (shared by all bots through the cache file). Past events
    from earlier weeks are kept for keep_days, so a week rollover never drops today's.
    """

    def __init__(self, cache_dir="data/news", url=LIVE_URL, refresh_hours=4.0,
                 keep_days=14, fetch=None, now=None):
        self.cache_path = os.path.join(cache_dir, "live_calendar.csv")
        self.meta_path = os.path.join(cache_dir, "live_calendar.meta.json")
        # Shared by every bot: the last download attempt and how long to wait before the
        # next one. The bots refresh on the same schedule, so without this all of them
        # hit the feed in the same second and get rate-limited (HTTP 429).
        self.attempt_path = os.path.join(cache_dir, "live_calendar.attempt.json")
        self.url = url
        self.refresh_s = float(refresh_hours) * 3600
        self.keep_days = keep_days
        self._fetch = fetch or _http_get_json
        self._now = now or time.time
        self.events = empty_calendar()
        self._last_try = 0.0
        self._loaded_mtime = None

    def _recent_shared_attempt(self):
        try:
            with open(self.attempt_path) as f:
                a = json.load(f)
            return self._now() - float(a["at"]) < float(a.get("wait", 900))
        except Exception:
            return False

    def _write_attempt(self, wait_s):
        try:
            os.makedirs(os.path.dirname(self.attempt_path) or ".", exist_ok=True)
            tmp = self.attempt_path + f".{os.getpid()}.tmp"
            with open(tmp, "w") as f:
                json.dump({"at": self._now(), "wait": wait_s, "pid": os.getpid()}, f)
            _replace_retry(tmp, self.attempt_path)
        except Exception:
            pass

    def _take_lock(self, stale_s=120):
        """Only one bot downloads at a time: an exclusive lock file (atomic create).
        A lock older than stale_s is left over from a crashed bot and is taken over."""
        lock = self.cache_path + ".lock"
        try:
            if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > stale_s:
                os.remove(lock)
        except OSError:
            pass
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except OSError:
            return None

    @staticmethod
    def _release_lock(lock):
        try:
            os.remove(lock)
        except OSError:
            pass

    def _cache_age(self):
        try:
            with open(self.meta_path) as f:
                return self._now() - float(json.load(f)["fetched_at"])
        except Exception:
            return float("inf")

    def _load_cache(self):
        try:
            self.events = load_calendar(self.cache_path)
            self._loaded_mtime = os.path.getmtime(self.cache_path) if os.path.exists(self.cache_path) else None
        except Exception as e:
            log.warning("NEWS: cached calendar unreadable (%s) - news filter has no data", e)
            self.events = empty_calendar()

    def refresh(self, force=False):
        """Returns the current calendar frame. Never raises."""
        try:
            age = self._cache_age()
            if not force and age < self.refresh_s:
                mt = os.path.getmtime(self.cache_path) if os.path.exists(self.cache_path) else None
                if len(self.events) == 0 or mt != self._loaded_mtime:
                    self._load_cache()       # another bot refreshed it, or first call
                return self.events
            # Don't hammer the feed: this bot retries at most every 15 minutes, and no bot
            # tries while another one's attempt is recent (shared attempt file).
            if not force and self._now() - self._last_try < 900:
                return self.events
            if not force and os.path.exists(self.cache_path) and self._recent_shared_attempt():
                mt = os.path.getmtime(self.cache_path)
                if len(self.events) == 0 or mt != self._loaded_mtime:
                    self._load_cache()       # another bot is (or was just) fetching
                return self.events
            self._last_try = self._now()
            lock = self._take_lock()
            if lock is None:                 # another bot is downloading right now
                if len(self.events) == 0:
                    self._load_cache()
                return self.events
            try:
                return self._download(force)
            finally:
                self._release_lock(lock)
        except Exception as e:                # absolutely never break the bot
            log.warning("NEWS: calendar refresh error (%s) - keeping previous calendar", e)
        return self.events

    def _download(self, force):
        """Called with the lock held. Re-checks, then fetches and merges into the cache."""
        try:
            if not force and (self._cache_age() < self.refresh_s or
                              (os.path.exists(self.cache_path) and self._recent_shared_attempt())):
                self._load_cache()            # another bot finished just before we got the lock
                return self.events
            self._write_attempt(900)
            try:
                fresh = parse_ff_json(self._fetch(self.url))
            except Exception as e:
                limited = "429" in str(e)
                if limited:
                    self._write_attempt(1800)    # rate-limited: every bot waits 30 minutes
                log.warning("NEWS: calendar fetch failed (%s) - using cached calendar%s", e,
                            "; all bots wait 30 min before retrying" if limited else "")
                if len(self.events) == 0:
                    self._load_cache()
                return self.events
            old = load_calendar(self.cache_path)
            cutoff = pd.Timestamp(self._now(), unit="s", tz="UTC") - pd.Timedelta(days=self.keep_days)
            merged = normalize(pd.concat([old[old["time"] >= cutoff], fresh], ignore_index=True))
            save_calendar(merged, self.cache_path)
            mtmp = f"{self.meta_path}.{os.getpid()}.tmp"
            with open(mtmp, "w") as f:
                json.dump({"fetched_at": self._now(), "url": self.url, "events": len(fresh)}, f)
            _replace_retry(mtmp, self.meta_path)
            self.events = merged
            self._loaded_mtime = os.path.getmtime(self.cache_path)
            log.info("NEWS: calendar refreshed, %d high-impact events this week", len(fresh))
        except Exception as e:                # absolutely never break the bot
            log.warning("NEWS: calendar refresh error (%s) - keeping previous calendar", e)
        return self.events


def upcoming(df, now_utc, currencies=None, hours=24, limit=3):
    """Next events (within `hours`) for these currencies, for status lines."""
    d = filter_currencies(df, currencies)
    now_utc = pd.Timestamp(now_utc)
    now_utc = now_utc.tz_localize("UTC") if now_utc.tzinfo is None else now_utc
    m = (d["time"] >= now_utc) & (d["time"] <= now_utc + pd.Timedelta(hours=hours))
    return d[m].head(limit)


def describe_event(ev):
    """'US CPI at 13:30 UTC' style text for logs/overlay."""
    t = pd.Timestamp(ev["time"]).tz_convert("UTC")
    return f"{ev['currency']} {ev['event']} at {t:%H:%M} UTC ({t:%a %d %b})"

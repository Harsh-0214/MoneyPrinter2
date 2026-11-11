"""Journal: important bot events go to the combined log and the MT5 events file."""
import logging

from fxbot import journal


def test_classify_picks_trading_events_only():
    assert journal.classify("[London] ORDER SELL 0.14 lots @ ~1.34283  SL=1.34595") == "ORDER"
    assert journal.classify("[London] Order filled: ticket=1 fill_price=1.3") == "FILLED"
    assert journal.classify("[Trend 55d] Stop moved to 4100.00") == "STOP"
    assert journal.classify("[London] CLOSED short_break SELL 14000 units ... P/L 125.99") == "CLOSED"
    assert journal.classify("RISK CAP: 2000 already at risk + 500 new > cap 2500") == "SKIP"
    assert journal.classify("[London] STATUS Sweep: high swept") == "STATUS"
    assert journal.classify("DAILY SUMMARY EURUSD: ...") == "DAILY"
    assert journal.classify("Poll 08:05 London | spread 1.2 pips") is None      # routine noise
    assert journal.classify("Bar 08:05 spread=1.2pip") is None


def test_handler_writes_combined_and_mt5_files(tmp_path):
    log = logging.getLogger("fxbot.test_journal")
    log.setLevel(logging.INFO)
    log.propagate = False
    mt5_dir = tmp_path / "common"
    mt5_dir.mkdir()
    h = journal.attach(log, "EURUSD", str(mt5_dir), "EURUSD.", log_dir=str(tmp_path / "logs"))
    assert journal.attach(log, "EURUSD", str(mt5_dir), "EURUSD.") is h        # attached once
    log.info("[London] ORDER BUY 1.13 lots @ ~1.10000  SL=1.09500")
    log.info("Poll 08:05 London | spread 1.2")                               # not journaled
    log.error("Error (failure 1/5): boom")
    combined = list((tmp_path / "logs").glob("journal_*.log"))
    assert len(combined) == 1
    text = combined[0].read_text(encoding="utf-8")
    assert "EURUSD" in text and "ORDER" in text and "ERROR" in text and "Poll" not in text
    mt5_lines = (mt5_dir / "fxbot_events_EURUSD..txt").read_text().splitlines()
    assert mt5_lines[0].startswith("ORDER|") and mt5_lines[1].startswith("ERROR|")
    log.removeHandler(h)

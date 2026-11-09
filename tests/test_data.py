import pandas as pd

from fxbot.data import load_csv, resample


def test_mt5_export_format(tmp_path):
    p = tmp_path / "mt5.csv"
    p.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
                 "2024.01.02\t10:00:00\t1.10000\t1.10050\t1.09950\t1.10020\t120\t0\t8\n"
                 "2024.01.02\t10:01:00\t1.10020\t1.10030\t1.10000\t1.10010\t90\t0\t12\n")
    df = load_csv(p, "Europe/Helsinki")                  # server time UTC+2 in January
    assert df.index[0] == pd.Timestamp("2024-01-02 08:00", tz="UTC")
    assert df["data_spread_pips"].tolist() == [0.8, 1.2]


def test_dukascopy_format(tmp_path):
    p = tmp_path / "duka.csv"
    p.write_text("Gmt time,Open,High,Low,Close,Volume\n"
                 "02.01.2024 08:00:00.000,1.1,1.1005,1.0995,1.1002,10\n"
                 "02.01.2024 08:01:00.000,1.1002,1.1003,1.1,1.1001,10\n")
    df = load_csv(p, "UTC")
    assert df.index[1] == pd.Timestamp("2024-01-02 08:01", tz="UTC")
    bars = resample(df, "5min")
    assert len(bars) == 1 and bars["high"].iloc[0] == 1.1005

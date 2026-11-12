"""Download the broker's own H1 history from MT5 (read-only) into data/mt5/<SYMBOL>_H1.csv.

    python fetch_mt5_h1.py

~99k bars per symbol: hourly from mid-2018 (indices, metals, oil), daily-ish before that.
Columns: time (UTC), open/high/low/close (BID), spread_pts (MT5 points), point.
Used by run_new_markets.py.
"""
import sys, os
sys.path.insert(0, os.getcwd())
import MetaTrader5 as mt5, pandas as pd
from fxbot.data import server_ts_to_utc
mt5.initialize()
syms = ['SPX500','NAS100','US30','GER40','UK100','JPN225','XAGUSD','US Oil','EURJPY.','GBPJPY.','CADJPY.','AUDJPY.',
        'XAUUSD','USDJPY.','EURUSD.','GBPUSD.','AUDUSD.']
for n in syms:
    mt5.symbol_select(n, True)
    r = mt5.copy_rates_from_pos(n, mt5.TIMEFRAME_H1, 0, 99000)
    if r is None or not len(r):
        print(n, 'none', mt5.last_error()); continue
    df = pd.DataFrame(r)
    df.index = server_ts_to_utc(df['time'].values)
    df = df[df.index.notna()]
    df = df[~df.index.duplicated()].sort_index()
    info = mt5.symbol_info(n)
    out = pd.DataFrame({'open':df.open,'high':df.high,'low':df.low,'close':df.close,
                        'spread_pts':df.spread,'point':info.point})
    fn = 'data/mt5/' + n.replace(' ','').replace('.','') + '_H1.csv'
    out.to_csv(fn, index_label='time')
    print(n, len(out), out.index[0], out.index[-1], 'median spread pts', df.spread.median(), fn)

"""Every trade of every arsenal strategy on every market (2021-25 histdata) -> results/arsenal_trades.csv.

    python make_arsenal_trades.py          (~20-40 min, 6 workers)

Used by run_selector.py. 1% risk per trade, real spreads/slippage, R-multiples per trade.
"""
from multiprocessing import Pool

import pandas as pd

import run_arsenal as AR


def main():
    markets = list(AR.MARKETS)
    jobs = [(n, m) for n in AR.STRATS for m in markets]
    print(f"{len(jobs)} runs ...", flush=True)
    out = []
    with Pool(6, initializer=AR._init, initargs=(markets,)) as pool:
        for i, t in enumerate(pool.imap_unordered(AR.run_trades, jobs), 1):
            if t is not None:
                out.append(t)
            if i % 20 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    df = pd.concat(out, ignore_index=True)
    df.to_csv("results/arsenal_trades.csv", index=False)
    print(f"{len(df)} trades, {df.groupby(['strategy', 'market']).ngroups} strategy-market pairs")


if __name__ == "__main__":
    main()

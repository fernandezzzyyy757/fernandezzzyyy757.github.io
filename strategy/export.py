import csv
import os
import pandas as pd
from backtest import Trade


def export_trades(trades: list[Trade], symbol: str, out_dir: str = '.') -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'{symbol}_trades.csv')

    fields = [
        'symbol', 'direction', 'entry_date', 'entry_price',
        'stop', 'target', 'size',
        'exit_date', 'exit_price', 'exit_reason',
        'r_multiple', 'pnl',
    ]

    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            w.writerow({
                'symbol':      t.symbol,
                'direction':   t.direction,
                'entry_date':  t.entry_date,
                'entry_price': round(t.entry_price, 4),
                'stop':        round(t.stop, 4),
                'target':      round(t.target, 4),
                'size':        t.size,
                'exit_date':   t.exit_date,
                'exit_price':  round(t.exit_price, 4) if t.exit_price else '',
                'exit_reason': t.exit_reason or '',
                'r_multiple':  round(t.r_multiple, 3),
                'pnl':         round(t.pnl, 2),
            })

    return path


def export_equity(equity: pd.Series, symbol: str, out_dir: str = '.') -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'{symbol}_equity.csv')
    equity.dropna().rename('equity').to_csv(path, header=True)
    return path

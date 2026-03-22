"""RSI(2) R:R sweep — find optimal SL/TP for XAU and other pairs."""
import pandas as pd
import numpy as np
import yfinance as yf


def fetch_yf(ticker):
    data = yf.download(ticker, period='60d', interval='15m', progress=False)
    if data.empty:
        return None
    if hasattr(data.columns, 'levels'):
        data.columns = data.columns.get_level_values(0)
    return pd.DataFrame({
        'o': data['Open'].values, 'h': data['High'].values,
        'l': data['Low'].values, 'c': data['Close'].values,
    }).dropna()


def calc_rsi(closes, period=2):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_g = gain.rolling(window=period, min_periods=period).mean()
    avg_l = loss.rolling(window=period, min_periods=period).mean()
    return 100 - (100 / (1 + avg_g / avg_l))


def bt(df, sl, tp):
    closes = df['c'].astype(float)
    rsi = calc_rsi(closes, 2)
    ema = closes.ewm(span=50, adjust=False).mean()
    trades = []
    in_t = False
    es = None
    s = t = 0
    for i in range(56, len(df)):
        if in_t:
            if es == 'L':
                if df['l'].iloc[i] <= s:
                    trades.append(-sl)
                    in_t = False
                elif df['h'].iloc[i] >= t:
                    trades.append(tp)
                    in_t = False
            else:
                if df['h'].iloc[i] >= s:
                    trades.append(-sl)
                    in_t = False
                elif df['l'].iloc[i] <= t:
                    trades.append(tp)
                    in_t = False
            continue
        r = rsi.iloc[i]
        p = closes.iloc[i]
        e = ema.iloc[i]
        if pd.isna(r) or pd.isna(e):
            continue
        if r < 15 and p > e:
            es = 'L'
            s = p * (1 - sl)
            t = p * (1 + tp)
            in_t = True
        elif r > 85 and p < e:
            es = 'S'
            s = p * (1 + sl)
            t = p * (1 - tp)
            in_t = True
    if not trades:
        return None
    w = sum(1 for x in trades if x > 0)
    n = len(trades)
    wr = w / n * 100
    gw = sum(x for x in trades if x > 0)
    gl = abs(sum(x for x in trades if x < 0))
    pf = gw / gl if gl > 0 else 999
    total = sum(trades) * 100
    return n, w, round(wr, 1), round(pf, 2), round(total, 1)


def run():
    pairs = [
        ('GC=F', 'XAU'),
        ('SOL-USD', 'SOL'),
        ('AVAX-USD', 'AVAX'),
        ('SI=F', 'XAG'),
        ('CL=F', 'WTI'),
        ('ETH-USD', 'ETH'),
        ('BTC-USD', 'BTC'),
    ]

    for ticker, sym in pairs:
        df = fetch_yf(ticker)
        if df is None or len(df) < 200:
            print(f"\n{sym}: no data")
            continue

        print(f"\n{'='*60}")
        print(f"  {sym} RSI(2) R:R Sweep ({len(df)} bars, 60d 15m)")
        print(f"{'='*60}")
        print(f"  SL%   TP%   R:R  Trades Wins   WR%    PF   Total%")
        print(f"  {'-'*52}")

        results = []
        for sl10 in [3, 4, 5, 6, 8, 10, 12, 15, 20]:
            for tp10 in [2, 3, 4, 5, 6, 8, 10, 12, 15, 20]:
                s = sl10 / 1000
                t = tp10 / 1000
                r = bt(df, s, t)
                if r and r[0] >= 3:
                    results.append((s, t, t / s) + r)

        results.sort(key=lambda x: x[7], reverse=True)
        for s, t, rr, n, w, wr, pf, tot in results[:12]:
            flag = ' ***' if pf >= 1.5 and n >= 5 else ''
            print(f"  {s*100:.1f}%  {t*100:.1f}%  {rr:.1f}x  {n:>5}  {w:>4}  {wr:>5.1f}%  {pf:>5.2f}  {tot:>+6.1f}%{flag}")

        if results:
            b = results[0]
            print(f"\n  BEST: SL={b[0]*100:.1f}% TP={b[1]*100:.1f}% R:R={b[2]:.1f}x")
            print(f"    {b[3]}T {b[4]}W {b[5]:.1f}%WR PF={b[6]:.2f} Total={b[7]:+.1f}%")


if __name__ == '__main__':
    run()

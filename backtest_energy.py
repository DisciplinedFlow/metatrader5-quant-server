import os, json
os.environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
import django; django.setup()
import pandas as pd, numpy as np

# Load energy + gold data
ALL_DATA = {}
for sym, path in [("USOUSD", "/tmp/usousd_m15.json"), ("UKOUSDft", "/tmp/ukousdft_m15.json"),
                   ("NG-C", "/tmp/ngc_m15.json"), ("XAUUSD", "/tmp/xauusd_m15.json")]:
    with open(path) as f:
        r = json.load(f)
    b = r.get("data", r) if isinstance(r, dict) else r
    d = pd.DataFrame(b)
    d["time"] = pd.to_datetime(d["time"])
    d = d.sort_values("time").reset_index(drop=True)
    ALL_DATA[sym] = d
    print("%s: %d bars, %s to %s" % (sym, len(d), d["time"].iloc[0].date(), d["time"].iloc[-1].date()))

SP = {"USOUSD": 0.05, "UKOUSDft": 0.05, "NG-C": 0.010, "XAUUSD": 0.30}
ENERGY = ["USOUSD", "UKOUSDft", "NG-C"]

def compute_atr(d, p=14):
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).rolling(p).mean().values

def ema(arr, p):
    s = pd.Series(arr)
    return s.ewm(span=p, adjust=False).mean().values

def rsi(d, p=14):
    c = d["close"].values
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_g = pd.Series(gain).rolling(p).mean().values
    avg_l = pd.Series(loss).rolling(p).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_g / avg_l
        return np.where(avg_l == 0, 100, 100 - 100 / (1 + rs))

def adx(d, p=14):
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    up = np.diff(h, prepend=h[0])
    dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0)
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    atr_s = pd.Series(tr).rolling(p).mean().values
    pdi = pd.Series(pdm).rolling(p).mean().values / np.where(atr_s == 0, 1, atr_s) * 100
    ndi = pd.Series(ndm).rolling(p).mean().values / np.where(atr_s == 0, 1, atr_s) * 100
    dx = np.abs(pdi - ndi) / np.where((pdi + ndi) == 0, 1, pdi + ndi) * 100
    return pd.Series(dx).rolling(p).mean().values, pdi, ndi

# ========== STRATEGY SIGNAL GENERATORS ==========

def trend_ema_crossover(d):
    """EMA 8/21 crossover — classic trend following"""
    fast = ema(d["close"].values, 8)
    slow = ema(d["close"].values, 21)
    sigs = []
    for i in range(22, len(d), 2):
        if fast[i] > slow[i] and fast[i-1] <= slow[i-1]:
            sigs.append((i, 0))  # BUY
        elif fast[i] < slow[i] and fast[i-1] >= slow[i-1]:
            sigs.append((i, 1))  # SELL
    return sigs

def trend_ema_adx(d):
    """EMA 8/21 crossover + ADX > 25 (confirmed trend)"""
    fast = ema(d["close"].values, 8)
    slow = ema(d["close"].values, 21)
    adx_vals, pdi, ndi = adx(d)
    sigs = []
    for i in range(30, len(d), 2):
        if np.isnan(adx_vals[i]): continue
        if adx_vals[i] < 25: continue  # No trend
        if fast[i] > slow[i] and fast[i-1] <= slow[i-1]:
            sigs.append((i, 0))
        elif fast[i] < slow[i] and fast[i-1] >= slow[i-1]:
            sigs.append((i, 1))
    return sigs

def momentum_breakout(d):
    """Donchian breakout — 20-bar high/low break"""
    h = d["high"].values
    l = d["low"].values
    c = d["close"].values
    sigs = []
    for i in range(25, len(d), 2):
        hh = np.max(h[i-20:i])
        ll = np.min(l[i-20:i])
        if c[i] > hh:
            sigs.append((i, 0))  # Breakout long
        elif c[i] < ll:
            sigs.append((i, 1))  # Breakout short
    return sigs

def pullback_ema(d):
    """Trend pullback — price above EMA50, pull back to EMA21, bounce"""
    ema21 = ema(d["close"].values, 21)
    ema50 = ema(d["close"].values, 50)
    c = d["close"].values
    l = d["low"].values
    h = d["high"].values
    sigs = []
    for i in range(52, len(d), 2):
        # Uptrend: EMA21 > EMA50, price touched EMA21 and bounced
        if ema21[i] > ema50[i] and l[i] <= ema21[i] * 1.001 and c[i] > ema21[i]:
            sigs.append((i, 0))
        # Downtrend: EMA21 < EMA50, price touched EMA21 and rejected
        if ema21[i] < ema50[i] and h[i] >= ema21[i] * 0.999 and c[i] < ema21[i]:
            sigs.append((i, 1))
    return sigs

def rsi_momentum(d):
    """RSI momentum — buy when RSI crosses above 50 in uptrend, sell below 50 in downtrend"""
    rsi_vals = rsi(d, 14)
    ema50 = ema(d["close"].values, 50)
    c = d["close"].values
    sigs = []
    for i in range(52, len(d), 2):
        if np.isnan(rsi_vals[i]): continue
        if c[i] > ema50[i] and rsi_vals[i] > 50 and rsi_vals[i-1] <= 50:
            sigs.append((i, 0))
        if c[i] < ema50[i] and rsi_vals[i] < 50 and rsi_vals[i-1] >= 50:
            sigs.append((i, 1))
    return sigs

def cvd_lop(d, lb=20):
    """CVD Lack of Participants on energy"""
    dl = d["tick_volume"].values * (2*d["close"].values - d["high"].values - d["low"].values) / np.where((d["high"].values - d["low"].values) == 0, 1e-10, d["high"].values - d["low"].values)
    cv = np.cumsum(dl)
    sigs = []
    for i in range(lb+5, len(d), 2):
        rl = d["low"].values[i-5:i+1]; pl = d["low"].values[i-lb:i-5]
        if rl.min() < pl.min() and cv[i-5+np.argmin(rl)] > cv[i-lb+np.argmin(pl)]:
            sigs.append((i, 0))
        rh = d["high"].values[i-5:i+1]; ph = d["high"].values[i-lb:i-5]
        if rh.max() > ph.max() and cv[i-5+np.argmax(rh)] < cv[i-lb+np.argmax(ph)]:
            sigs.append((i, 1))
    return sigs

def trend_bias_only_long(d):
    """Buy-only EMA crossover — for supply shock (price only goes up)"""
    fast = ema(d["close"].values, 8)
    slow = ema(d["close"].values, 21)
    sigs = []
    for i in range(22, len(d), 2):
        if fast[i] > slow[i] and fast[i-1] <= slow[i-1]:
            sigs.append((i, 0))  # BUY only
    return sigs

# ========== BACKTESTER ==========

def backtest(name, fn, syms, sl, tp, cd=8):
    total, wins = 0, 0
    for sym in syms:
        d = ALL_DATA.get(sym)
        if d is None: continue
        atr_vals = compute_atr(d)
        high = d["high"].values; low = d["low"].values; close = d["close"].values
        sigs = fn(d)
        sp = SP.get(sym, 0.05)
        last = -cd
        for idx, dr in sigs:
            if idx - last < cd or idx >= len(d) - 1: continue
            av = atr_vals[idx]
            if np.isnan(av) or av <= 0: continue
            sd = sl * av; td = tp * av
            e = close[idx] + (sp/2 if dr == 0 else -sp/2)
            end = min(idx + 200, len(d))
            for j in range(idx + 1, end):
                if dr == 0:
                    if low[j] <= e - sd: total += 1; last = idx; break
                    if high[j] >= e + td: wins += 1; total += 1; last = idx; break
                else:
                    if high[j] >= e + sd: total += 1; last = idx; break
                    if low[j] <= e - td: wins += 1; total += 1; last = idx; break
    wr = wins / total * 100 if total else 0
    pf = (wins * tp) / ((total - wins) * sl) if total > wins else 0
    return (name, total, wins, wr, pf)

# ========== RUN ALL COMBINATIONS ==========
rs = []

strategies = {
    "EMA Cross 8/21": trend_ema_crossover,
    "EMA+ADX(25)": trend_ema_adx,
    "Donchian Break": momentum_breakout,
    "Pullback EMA21/50": pullback_ema,
    "RSI Momentum": rsi_momentum,
    "CVD LoP": cvd_lop,
    "BUY-Only EMA": trend_bias_only_long,
}

for sname, fn in strategies.items():
    for sl, tp in [(1.5, 3.0), (2.0, 4.0), (2.5, 5.0)]:
        rs.append(backtest("%s Energy %s/%s" % (sname, sl, tp), fn, ENERGY, sl, tp))
        rs.append(backtest("%s Oil %s/%s" % (sname, sl, tp), fn, ["USOUSD", "UKOUSDft"], sl, tp))
        rs.append(backtest("%s NG %s/%s" % (sname, sl, tp), fn, ["NG-C"], sl, tp))
    # Also test on XAUUSD for comparison
    rs.append(backtest("%s XAUUSD 2.0/4.0" % sname, fn, ["XAUUSD"], 2.0, 4.0))

rs = [r for r in rs if r[1] > 5]  # min 5 trades
rs.sort(key=lambda r: r[3], reverse=True)

print("")
print("=" * 75)
print("ENERGY STRATEGY BACKTEST — 78 days M15 (includes Iran war period)")
print("=" * 75)
print("%-38s %6s %5s %6s %5s" % ("Strategy", "Trades", "Wins", "WR%", "PF"))
print("-" * 68)
for name, t, w, wr, pf in rs[:35]:
    m = " ***" if wr >= 45 else " **" if wr >= 40 else " *" if wr >= 35 else ""
    print("%-38s %6d %5d %5.1f%% %5.2f%s" % (name, t, w, wr, pf, m))

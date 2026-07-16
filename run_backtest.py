import os, json
os.environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
import django; django.setup()
import pandas as pd, numpy as np

# Load data
ALL_DATA = {}
for sym in ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "XAGUSD"]:
    with open("/tmp/%s_m15.json" % sym.lower()) as f:
        r = json.load(f)
    b = r.get("data", r) if isinstance(r, dict) else r
    d = pd.DataFrame(b); d["time"] = pd.to_datetime(d["time"]); d = d.sort_values("time").reset_index(drop=True)
    ALL_DATA[sym] = d
print("Loaded %d symbols" % len(ALL_DATA))

SP = {"XAUUSD": 0.30, "EURUSD": 0.00015, "GBPUSD": 0.00018, "USDJPY": 0.015, "XAGUSD": 0.030}

def compute_atr(d, p=14):
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).rolling(p).mean().values

def lop_signals(d, lb=20):
    close = d["close"].values; high = d["high"].values; low = d["low"].values; tv = d["tick_volume"].values
    hl = high - low; hl[hl == 0] = 1e-10
    delta = tv * (2 * close - high - low) / hl
    cvd = np.cumsum(delta)
    sigs = []
    for i in range(lb + 5, len(d), 2):  # step 2 for speed
        rl_slice = low[i-5:i+1]; pl_slice = low[i-lb:i-5]
        rl_min_idx = i - 5 + np.argmin(rl_slice); pl_min_idx = i - lb + np.argmin(pl_slice)
        if low[rl_min_idx] < low[pl_min_idx] and cvd[rl_min_idx] > cvd[pl_min_idx]:
            sigs.append((i, 0))  # BUY=0
        rh_slice = high[i-5:i+1]; ph_slice = high[i-lb:i-5]
        rh_max_idx = i - 5 + np.argmax(rh_slice); ph_max_idx = i - lb + np.argmax(ph_slice)
        if high[rh_max_idx] > high[ph_max_idx] and cvd[rh_max_idx] < cvd[ph_max_idx]:
            sigs.append((i, 1))  # SELL=1
    return sigs

def abs_signals(d, lb=20):
    close = d["close"].values; high = d["high"].values; low = d["low"].values; tv = d["tick_volume"].values
    hl = high - low; hl[hl == 0] = 1e-10
    delta = tv * (2 * close - high - low) / hl
    cvd = np.cumsum(delta)
    sigs = []
    for i in range(lb + 5, len(d), 2):
        pc = (close[i] - close[i-lb]) / close[i-lb]
        cc = cvd[i] - cvd[i-lb]
        vm = np.mean(tv[i-lb:i+1]) * 2
        if pc < -0.001 and cc > 0 and abs(cc) > vm:
            sigs.append((i, 0))
        if pc > 0.001 and cc < 0 and abs(cc) > vm:
            sigs.append((i, 1))
    return sigs

def struct_signals(d):
    high = d["high"].values; low = d["low"].values
    sigs = []
    for i in range(27, len(d), 3):
        if high[i] > high[i-1] and low[i] > low[i-1]:
            sigs.append((i, 0))
        elif high[i] < high[i-1] and low[i] < low[i-1]:
            sigs.append((i, 1))
    return sigs

def backtest(name, fn, syms, sl, tp, sess=False, cd=8):
    total, wins = 0, 0
    for sym in syms:
        d = ALL_DATA.get(sym)
        if d is None: continue
        atr_vals = compute_atr(d)
        high = d["high"].values; low = d["low"].values; close = d["close"].values
        hours = d["time"].dt.hour.values
        sigs = fn(d)
        sp = SP.get(sym, 0.0002)
        last = -cd
        for idx, dr in sigs:
            if idx - last < cd or idx >= len(d) - 1: continue
            av = atr_vals[idx]
            if np.isnan(av) or av <= 0: continue
            if sess and not (7 <= hours[idx] < 10 or 13 <= hours[idx] < 17): continue
            sd = sl * av; td = tp * av
            e = close[idx] + (sp/2 if dr == 0 else -sp/2)
            end = min(idx + 200, len(d))
            for j in range(idx + 1, end):
                if dr == 0:  # BUY
                    if low[j] <= e - sd: total += 1; last = idx; break
                    if high[j] >= e + td: wins += 1; total += 1; last = idx; break
                else:  # SELL
                    if high[j] >= e + sd: total += 1; last = idx; break
                    if low[j] <= e - td: wins += 1; total += 1; last = idx; break
    wr = wins / total * 100 if total else 0
    pf = (wins * tp) / ((total - wins) * sl) if total > wins else 0
    return (name, total, wins, wr, pf)

ALL = list(ALL_DATA.keys())
XAU = ["XAUUSD"]
rs = []

for sl, tp in [(1.5, 3.0), (1.8, 3.6), (2.0, 4.0), (2.5, 5.0)]:
    rs.append(backtest("LoP ALL %s/%s" % (sl, tp), lop_signals, ALL, sl, tp))
    rs.append(backtest("LoP ALL+Sess %s/%s" % (sl, tp), lop_signals, ALL, sl, tp, sess=True))
    rs.append(backtest("LoP XAU %s/%s" % (sl, tp), lop_signals, XAU, sl, tp))
    rs.append(backtest("LoP XAU+Sess %s/%s" % (sl, tp), lop_signals, XAU, sl, tp, sess=True))
print("CVD LoP done")

for sl, tp in [(1.8, 3.6), (2.0, 4.0), (2.5, 5.0)]:
    rs.append(backtest("Absorp ALL %s/%s" % (sl, tp), abs_signals, ALL, sl, tp))
    rs.append(backtest("Absorp+Sess %s/%s" % (sl, tp), abs_signals, ALL, sl, tp, sess=True))
print("Absorption done")

for sl, tp in [(1.8, 3.6), (2.0, 4.0), (2.5, 5.0)]:
    rs.append(backtest("Struct ALL %s/%s" % (sl, tp), struct_signals, ALL, sl, tp))
    rs.append(backtest("Struct+Sess %s/%s" % (sl, tp), struct_signals, ALL, sl, tp, sess=True))
    rs.append(backtest("Struct XAU %s/%s" % (sl, tp), struct_signals, XAU, sl, tp))
    rs.append(backtest("Struct XAU+S %s/%s" % (sl, tp), struct_signals, XAU, sl, tp, sess=True))
print("Structure done")

rs = [r for r in rs if r[1] > 0]
rs.sort(key=lambda r: r[3], reverse=True)

print("")
print("%-32s %6s %5s %6s %5s" % ("Strategy", "Trades", "Wins", "WR%", "PF"))
print("-" * 62)
for name, t, w, wr, pf in rs:
    m = " ***" if wr >= 45 else " **" if wr >= 40 else " *" if wr >= 35 else ""
    print("%-32s %6d %5d %5.1f%% %5.2f%s" % (name, t, w, wr, pf, m))

import os, json
os.environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
import django; django.setup()
import pandas as pd, numpy as np

ALL_DATA = {}
for sym, path in [("USOUSD", "/tmp/usousd_m15.json"), ("UKOUSDft", "/tmp/ukousdft_m15.json"),
                   ("NG-C", "/tmp/ngc_m15.json"), ("XAUUSD", "/tmp/xauusd_m15.json")]:
    with open(path) as f: r = json.load(f)
    b = r.get("data", r) if isinstance(r, dict) else r
    d = pd.DataFrame(b); d["time"] = pd.to_datetime(d["time"]); d = d.sort_values("time").reset_index(drop=True)
    # Filter to WAR PERIOD ONLY (Feb 28+)
    d = d[d["time"] >= "2026-02-28"].reset_index(drop=True)
    ALL_DATA[sym] = d
    print("%s: %d bars (war period)" % (sym, len(d)))

SP = {"USOUSD": 0.05, "UKOUSDft": 0.05, "NG-C": 0.010, "XAUUSD": 0.30}
ENERGY = ["USOUSD", "UKOUSDft", "NG-C"]

def compute_atr(d, p=14):
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).rolling(p).mean().values

def ema(arr, p):
    return pd.Series(arr).ewm(span=p, adjust=False).mean().values

def adx(d, p=14):
    h, l, c = d["high"].values, d["low"].values, d["close"].values
    up = np.diff(h, prepend=h[0]); dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0); ndm = np.where((dn > up) & (dn > 0), dn, 0)
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1)))); tr[0]=h[0]-l[0]
    a = pd.Series(tr).rolling(p).mean().values
    pdi = pd.Series(pdm).rolling(p).mean().values / np.where(a==0,1,a) * 100
    ndi = pd.Series(ndm).rolling(p).mean().values / np.where(a==0,1,a) * 100
    dx = np.abs(pdi-ndi) / np.where((pdi+ndi)==0,1,pdi+ndi) * 100
    return pd.Series(dx).rolling(p).mean().values, pdi, ndi

def trend_ema(d):
    f = ema(d["close"].values, 8); s = ema(d["close"].values, 21); sigs = []
    for i in range(22, len(d), 2):
        if f[i] > s[i] and f[i-1] <= s[i-1]: sigs.append((i, 0))
        elif f[i] < s[i] and f[i-1] >= s[i-1]: sigs.append((i, 1))
    return sigs

def trend_ema_adx(d):
    f = ema(d["close"].values, 8); s = ema(d["close"].values, 21); av, pi, ni = adx(d); sigs = []
    for i in range(30, len(d), 2):
        if np.isnan(av[i]) or av[i] < 25: continue
        if f[i] > s[i] and f[i-1] <= s[i-1]: sigs.append((i, 0))
        elif f[i] < s[i] and f[i-1] >= s[i-1]: sigs.append((i, 1))
    return sigs

def donchian_break(d):
    h = d["high"].values; l = d["low"].values; c = d["close"].values; sigs = []
    for i in range(25, len(d), 2):
        if c[i] > np.max(h[i-20:i]): sigs.append((i, 0))
        elif c[i] < np.min(l[i-20:i]): sigs.append((i, 1))
    return sigs

def pullback(d):
    e21 = ema(d["close"].values, 21); e50 = ema(d["close"].values, 50)
    c = d["close"].values; l = d["low"].values; h = d["high"].values; sigs = []
    for i in range(52, len(d), 2):
        if e21[i] > e50[i] and l[i] <= e21[i]*1.001 and c[i] > e21[i]: sigs.append((i, 0))
        if e21[i] < e50[i] and h[i] >= e21[i]*0.999 and c[i] < e21[i]: sigs.append((i, 1))
    return sigs

def buy_only_ema(d):
    f = ema(d["close"].values, 8); s = ema(d["close"].values, 21); sigs = []
    for i in range(22, len(d), 2):
        if f[i] > s[i] and f[i-1] <= s[i-1]: sigs.append((i, 0))
    return sigs

def buy_only_pullback(d):
    e21 = ema(d["close"].values, 21); e50 = ema(d["close"].values, 50)
    c = d["close"].values; l = d["low"].values; sigs = []
    for i in range(52, len(d), 2):
        if e21[i] > e50[i] and l[i] <= e21[i]*1.002 and c[i] > e21[i]: sigs.append((i, 0))
    return sigs

def buy_only_adx(d):
    f = ema(d["close"].values, 8); s = ema(d["close"].values, 21); av, pi, ni = adx(d); sigs = []
    for i in range(30, len(d), 2):
        if np.isnan(av[i]) or av[i] < 20: continue
        if f[i] > s[i] and f[i-1] <= s[i-1]: sigs.append((i, 0))
    return sigs

def backtest(name, fn, syms, sl, tp, cd=8):
    total, wins = 0, 0
    for sym in syms:
        d = ALL_DATA.get(sym)
        if d is None or len(d) < 60: continue
        atr_vals = compute_atr(d)
        high = d["high"].values; low = d["low"].values; close = d["close"].values
        sigs = fn(d); sp = SP.get(sym, 0.05); last = -cd
        for idx, dr in sigs:
            if idx - last < cd or idx >= len(d) - 1: continue
            av = atr_vals[idx]
            if np.isnan(av) or av <= 0: continue
            sd = sl * av; td = tp * av
            e = close[idx] + (sp/2 if dr == 0 else -sp/2)
            for j in range(idx + 1, min(idx + 200, len(d))):
                if dr == 0:
                    if low[j] <= e - sd: total += 1; last = idx; break
                    if high[j] >= e + td: wins += 1; total += 1; last = idx; break
                else:
                    if high[j] >= e + sd: total += 1; last = idx; break
                    if low[j] <= e - td: wins += 1; total += 1; last = idx; break
    wr = wins / total * 100 if total else 0
    pf = (wins * tp) / ((total - wins) * sl) if total > wins else 0
    return (name, total, wins, wr, pf)

rs = []
strats = {"EMA 8/21": trend_ema, "EMA+ADX": trend_ema_adx, "Donchian": donchian_break,
          "Pullback": pullback, "BUY EMA": buy_only_ema, "BUY Pullback": buy_only_pullback,
          "BUY ADX": buy_only_adx}

for sn, fn in strats.items():
    for sl, tp in [(1.5, 3.0), (2.0, 4.0), (2.5, 5.0)]:
        rs.append(backtest("%s Energy %s/%s" % (sn, sl, tp), fn, ENERGY, sl, tp))
        rs.append(backtest("%s Oil %s/%s" % (sn, sl, tp), fn, ["USOUSD", "UKOUSDft"], sl, tp))
        rs.append(backtest("%s NG %s/%s" % (sn, sl, tp), fn, ["NG-C"], sl, tp))
    rs.append(backtest("%s XAU 2.0/4.0" % sn, fn, ["XAUUSD"], 2.0, 4.0))

rs = [r for r in rs if r[1] > 3]
rs.sort(key=lambda r: r[3], reverse=True)

print("")
print("=" * 75)
print("ENERGY STRATEGIES — WAR PERIOD ONLY (Feb 28 - Mar 19, 2026)")
print("=" * 75)
print("%-36s %6s %5s %6s %5s" % ("Strategy", "Trades", "Wins", "WR%", "PF"))
print("-" * 66)
for name, t, w, wr, pf in rs[:30]:
    m = " ***" if wr >= 45 else " **" if wr >= 40 else " *" if wr >= 35 else ""
    print("%-36s %6d %5d %5.1f%% %5.2f%s" % (name, t, w, wr, pf, m))

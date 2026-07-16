#!/usr/bin/env python3
"""
Claude Trade CLI — Interactive trading terminal for Claude-assisted decisions.

Usage:
    python trade_cli.py status          # Account + open positions
    python trade_cli.py scan            # Scan all symbols for signals
    python trade_cli.py analyze XAUUSD  # Deep analysis of one symbol
    python trade_cli.py buy  SYMBOL VOLUME SL TP
    python trade_cli.py sell SYMBOL VOLUME SL TP
    python trade_cli.py close TICKET
    python trade_cli.py close-all

API endpoint: http://localhost:5001
"""

import sys
import json
import math
import statistics
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
except ImportError:
    print("pip install requests")
    sys.exit(1)

BASE = "http://localhost:5001"
SESSION = requests.Session()
SESSION.headers["Content-Type"] = "application/json"

SYMBOLS = [
    "XAUUSD", "XAGUSD",
    "NG-C", "UKOUSDft", "USOUSD",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
]

# ANSI colors
GRN  = "\033[92m"
RED  = "\033[91m"
YEL  = "\033[93m"
CYN  = "\033[96m"
BLD  = "\033[1m"
DIM  = "\033[2m"
RST  = "\033[0m"


# ─────────────────────────────────────────────────────────────────────────────
# MT5 API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(path, params=None, timeout=8):
    try:
        r = SESSION.get(f"{BASE}{path}", params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return None


def _post(path, body, timeout=15):
    try:
        r = SESSION.post(f"{BASE}{path}", json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return None


def account_info():
    return _get("/account_info")


def get_positions():
    data = _get("/get_positions") or []
    if isinstance(data, dict):
        return data.get("positions", [])
    return data


def get_tick(symbol):
    return _get(f"/symbol_info_tick/{symbol}")


def fetch_bars(symbol, timeframe="H4", bars=60):
    """Fetch OHLCV bars. timeframe: M1, M5, M15, H1, H4, D1."""
    TF_MAP = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408}
    tf_val = TF_MAP.get(timeframe, 16388)
    return _get("/fetch_data_pos", params={"symbol": symbol, "timeframe": tf_val, "bars": bars}) or []


def fetch_ticks(symbol, count=500, seconds_back=30):
    data = _get("/fetch_ticks", params={"symbol": symbol, "count": count, "seconds_back": seconds_back})
    return data if isinstance(data, list) else []


def send_order(symbol, direction, volume, sl, tp):
    """Place market order. direction: 'BUY' or 'SELL'."""
    body = {
        "symbol": symbol,
        "volume": float(volume),
        "type": direction.upper(),
        "sl": float(sl),
        "tp": float(tp),
        "type_filling": "ORDER_FILLING_IOC",
        "magic": 234001,  # CLI magic number (different from algo 234000)
    }
    result = _post("/order", body)
    return result


def close_position(ticket, symbol, order_type, volume):
    body = {"position": {"type": int(order_type), "ticket": int(ticket), "symbol": symbol, "volume": float(volume)}}
    return _post("/close_position", body)


# ─────────────────────────────────────────────────────────────────────────────
# Signal computation (pure math, no external deps)
# ─────────────────────────────────────────────────────────────────────────────

def compute_ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    emas = [None] * (period - 1)
    emas.append(sum(values[:period]) / period)
    for v in values[period:]:
        emas.append(emas[-1] * (1 - k) + v * k)
    return emas


def compute_atr(bars, period=14):
    """ATR from OHLCV bar list (dicts with high/low/close)."""
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return statistics.mean(trs) if trs else 0
    recent = trs[-period:]
    return statistics.mean(recent)


def htf_bias(bars):
    """EMA(8) vs EMA(34) crossover direction from H4 bars."""
    closes = [b["close"] for b in bars]
    ema8  = compute_ema(closes, 8)
    ema34 = compute_ema(closes, 34)
    if ema8[-1] is None or ema34[-1] is None:
        return "neutral"
    if ema8[-1] > ema34[-1]:
        return "bullish"
    elif ema8[-1] < ema34[-1]:
        return "bearish"
    return "neutral"


def detect_fvg(bars):
    """Return list of dicts: direction, high, low, mitigated, age_bars."""
    fvgs = []
    last_close = bars[-1]["close"]
    for i in range(2, len(bars)):
        # Bullish FVG: gap between bar[i-2].high and bar[i].low
        if bars[i]["low"] > bars[i - 2]["high"]:
            mid = (bars[i]["low"] + bars[i - 2]["high"]) / 2
            mitigated = last_close < bars[i]["low"]
            fvgs.append({"dir": "bullish", "high": bars[i]["low"], "low": bars[i - 2]["high"],
                         "mid": mid, "mitigated": mitigated, "age": len(bars) - i})
        # Bearish FVG: gap between bar[i-2].low and bar[i].high
        if bars[i]["high"] < bars[i - 2]["low"]:
            mid = (bars[i]["high"] + bars[i - 2]["low"]) / 2
            mitigated = last_close > bars[i]["high"]
            fvgs.append({"dir": "bearish", "high": bars[i - 2]["low"], "low": bars[i]["high"],
                         "mid": mid, "mitigated": mitigated, "age": len(bars) - i})
    return fvgs


def cvd_proxy_from_ticks(ticks):
    """Compute cumulative volume delta from tick data."""
    if not ticks:
        return None, 0
    cvd = 0
    for t in ticks:
        bid = t.get("bid", 0)
        ask = t.get("ask", 0)
        last = t.get("last", 0)
        vol = t.get("volume", 0)
        if last > 0 and bid > 0:
            if last >= ask:
                cvd += vol
            elif last <= bid:
                cvd -= vol
    # direction from last 30% of ticks
    n = max(1, len(ticks) // 3)
    recent = ticks[-n:]
    rcvd = 0
    for t in recent:
        bid = t.get("bid", 0)
        ask = t.get("ask", 0)
        last = t.get("last", 0)
        vol = t.get("volume", 0)
        if last > 0 and bid > 0:
            if last >= ask:
                rcvd += vol
            elif last <= bid:
                rcvd -= vol
    direction = "bullish" if rcvd > 0 else ("bearish" if rcvd < 0 else "neutral")
    return direction, cvd


def session_now():
    """Current trading session based on UTC hour."""
    h = datetime.now(timezone.utc).hour
    if 7 <= h < 10:
        return "London Open"
    elif 10 <= h < 13:
        return "London Mid"
    elif 13 <= h < 17:
        return "NY Open"
    elif 17 <= h < 21:
        return "NY Mid"
    elif 21 <= h or h < 2:
        return "Asian"
    return "Off-hours"


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pnl_color(v):
    return GRN if v >= 0 else RED


def _bias_color(b):
    if b == "bullish": return GRN
    if b == "bearish": return RED
    return YEL


def _fmt_price(p, digits=5):
    return f"{p:.{digits}f}"


def print_header(title):
    w = 72
    print(f"\n{BLD}{'─' * w}{RST}")
    print(f"{BLD}  {title}{RST}")
    print(f"{BLD}{'─' * w}{RST}")


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

def cmd_status():
    acc = account_info()
    positions = get_positions()

    print_header(f"ACCOUNT STATUS  —  {session_now()} session  —  {datetime.utcnow().strftime('%H:%M UTC')}")

    if acc:
        bal  = acc.get("balance", 0)
        eq   = acc.get("equity", 0)
        prof = acc.get("profit", 0)
        lvl  = acc.get("margin_level", 0)
        c = _pnl_color(prof)
        print(f"  Balance: {BLD}{bal:,.2f} EUR{RST}  |  Equity: {eq:,.2f}  |  "
              f"Float P&L: {c}{BLD}{prof:+.2f} EUR{RST}  |  Margin level: {lvl:.0f}%")

    print()

    if not positions:
        print(f"  {DIM}No open positions.{RST}")
    else:
        print(f"  {'TICKET':<12} {'SYMBOL':<12} {'DIR':<5} {'ENTRY':>10} {'CURRENT':>10} "
              f"{'SL':>10} {'TP':>10} {'P&L':>9} {'VOL':<6}")
        print(f"  {'─'*12} {'─'*12} {'─'*5} {'─'*10} {'─'*10} {'─'*10} {'─'*10} {'─'*9} {'─'*6}")
        total_pnl = 0
        for p in positions:
            direction = "BUY" if p["type"] == 0 else "SELL"
            pnl = p.get("profit", 0)
            total_pnl += pnl
            c = _pnl_color(pnl)
            comment = p.get("comment", "")
            print(f"  {p['ticket']:<12} {p['symbol']:<12} {direction:<5} "
                  f"{p['price_open']:>10.5f} {p['price_current']:>10.5f} "
                  f"{p['sl']:>10.5f} {p['tp']:>10.5f} "
                  f"{c}{pnl:>+9.2f}{RST} {p['volume']:<6.2f}  {DIM}{comment}{RST}")
        c = _pnl_color(total_pnl)
        print(f"\n  Total float P&L: {c}{BLD}{total_pnl:+.2f} EUR{RST}")

    print()


def cmd_scan():
    """Scan all symbols and show signal summary."""
    positions = get_positions()
    open_syms = {p["symbol"] for p in positions}

    print_header(f"SIGNAL SCAN  —  {session_now()}  —  {datetime.utcnow().strftime('%H:%M UTC')}")
    print(f"  {'SYMBOL':<12} {'BIAS':<9} {'ATR':>7} {'CVD':>9} {'FVG-B':>6} {'FVG-Ba':>7} "
          f"{'SPREAD':>8} {'PRICE':>12} {'POS':<6}")
    print(f"  {'─'*12} {'─'*9} {'─'*7} {'─'*9} {'─'*6} {'─'*7} {'─'*8} {'─'*12} {'─'*6}")

    # Batch bars request — batch endpoint expects string timeframe like "H4"
    bars_data = _post("/fetch_data_pos_batch", {"symbols": SYMBOLS, "timeframe": "H4", "bars": 60})
    ticks_data = _post("/fetch_ticks_batch", {"symbols": SYMBOLS, "count": 300, "seconds_back": 30})

    for sym in SYMBOLS:
        bars = (bars_data or {}).get(sym, [])
        ticks = (ticks_data or {}).get(sym, [])

        tick = get_tick(sym)
        bid = tick.get("bid", 0) if tick else 0
        ask = tick.get("ask", 0) if tick else 0
        spread = ask - bid if bid and ask else 0

        # Compute signals
        if bars and len(bars) >= 40:
            atr = compute_atr(bars)
            bias = htf_bias(bars)
            fvgs = detect_fvg(bars[-30:])  # last 30 bars
            last_price = bars[-1]["close"]
            near_fvg_bull = sum(1 for f in fvgs if f["dir"] == "bullish" and not f["mitigated"]
                                and abs(last_price - f["mid"]) <= 2 * atr)
            near_fvg_bear = sum(1 for f in fvgs if f["dir"] == "bearish" and not f["mitigated"]
                                and abs(last_price - f["mid"]) <= 2 * atr)
        else:
            atr, bias, near_fvg_bull, near_fvg_bear = 0, "?", 0, 0

        cvd_dir, _ = cvd_proxy_from_ticks(ticks)
        in_pos = "●" if sym in open_syms else ""

        bc = _bias_color(bias)
        cc = _bias_color(cvd_dir or "neutral")
        ic = GRN if in_pos else ""

        atr_str = f"{atr:.4f}" if atr else "  —"
        sp_str  = f"{spread:.5f}" if spread else "  —"
        price_str = f"{bid:.5f}" if bid else "  —"

        print(f"  {sym:<12} {bc}{bias:<9}{RST} {atr_str:>7} "
              f"{cc}{(cvd_dir or '—'):<9}{RST} {near_fvg_bull:>6} {near_fvg_bear:>7} "
              f"{sp_str:>8} {price_str:>12} {ic}{in_pos}{RST}")

    print(f"\n  FVG-B = bullish FVGs within 2×ATR  |  FVG-Ba = bearish FVGs within 2×ATR")
    print(f"  ● = position open\n")


def cmd_analyze(symbol):
    """Deep analysis of a single symbol."""
    print_header(f"ANALYSIS: {symbol}  —  {datetime.utcnow().strftime('%H:%M UTC')}")

    # Fetch data
    bars_h4  = fetch_bars(symbol, "H4", 60)
    bars_h1  = fetch_bars(symbol, "H1", 50)
    ticks    = fetch_ticks(symbol, count=500, seconds_back=60)
    tick     = get_tick(symbol)
    positions = [p for p in get_positions() if p["symbol"] == symbol]

    if not bars_h4:
        print(f"  {RED}Could not fetch bars for {symbol}{RST}")
        return

    # ── Price ──
    bid = tick.get("bid", 0) if tick else 0
    ask = tick.get("ask", 0) if tick else 0
    spread = ask - bid
    spread_pct = (spread / bid * 100) if bid else 0
    print(f"  Price: {BLD}Bid={bid:.5f}  Ask={ask:.5f}{RST}  Spread={spread:.5f} ({spread_pct:.3f}%)")

    # ── ATR ──
    atr_h4 = compute_atr(bars_h4)
    atr_h1 = compute_atr(bars_h1) if bars_h1 else 0
    print(f"  ATR H4={atr_h4:.5f}  ATR H1={atr_h1:.5f}  "
          f"(spread = {spread/atr_h4*100:.1f}% of H4 ATR)" if atr_h4 else "")

    # ── HTF Bias ──
    bias_h4 = htf_bias(bars_h4)
    bias_h1 = htf_bias(bars_h1) if bars_h1 else "?"
    bc4 = _bias_color(bias_h4)
    bc1 = _bias_color(bias_h1)
    print(f"  HTF Bias: H4={bc4}{BLD}{bias_h4.upper()}{RST}  H1={bc1}{bias_h1}{RST}")

    # ── CVD ──
    cvd_dir, cvd_total = cvd_proxy_from_ticks(ticks)
    cc = _bias_color(cvd_dir or "neutral")
    print(f"  CVD ({len(ticks)} ticks): direction={cc}{BLD}{cvd_dir or '—'}{RST}  cumulative={cvd_total:+.0f}")

    # ── FVGs ──
    last_price = bars_h4[-1]["close"]
    fvgs = detect_fvg(bars_h4[-40:])
    near_bull = [f for f in fvgs if f["dir"] == "bullish" and not f["mitigated"]
                 and abs(last_price - f["mid"]) <= 3 * atr_h4]
    near_bear = [f for f in fvgs if f["dir"] == "bearish" and not f["mitigated"]
                 and abs(last_price - f["mid"]) <= 3 * atr_h4]

    if near_bull or near_bear:
        print(f"\n  FVGs within 3×ATR:")
        for f in near_bull:
            dist = abs(last_price - f["mid"])
            print(f"    {GRN}▲ Bullish{RST}  zone={f['low']:.5f}–{f['high']:.5f}  "
                  f"mid={f['mid']:.5f}  dist={dist:.5f}  age={f['age']}bars")
        for f in near_bear:
            dist = abs(last_price - f["mid"])
            print(f"    {RED}▼ Bearish{RST}  zone={f['low']:.5f}–{f['high']:.5f}  "
                  f"mid={f['mid']:.5f}  dist={dist:.5f}  age={f['age']}bars")
    else:
        print(f"  {DIM}No nearby FVGs (within 3×ATR){RST}")

    # ── Trade levels ──
    print(f"\n  {BLD}Suggested levels (based on H4 ATR={atr_h4:.5f}):{RST}")
    entry_buy = ask
    sl_buy  = entry_buy - 1.8 * atr_h4
    tp_buy  = entry_buy + 3.6 * atr_h4
    entry_sell = bid
    sl_sell  = entry_sell + 1.8 * atr_h4
    tp_sell  = entry_sell - 3.6 * atr_h4
    print(f"  BUY  entry={ask:.5f}  SL={sl_buy:.5f}  TP={tp_buy:.5f}  "
          f"({GRN}risk={1.8*atr_h4:.5f}  reward={3.6*atr_h4:.5f}{RST})")
    print(f"  SELL entry={bid:.5f}  SL={sl_sell:.5f}  TP={tp_sell:.5f}  "
          f"({RED}risk={1.8*atr_h4:.5f}  reward={3.6*atr_h4:.5f}{RST})")

    # ── Open positions ──
    if positions:
        print(f"\n  {YEL}{BLD}OPEN POSITION:{RST}")
        for p in positions:
            direction = "BUY" if p["type"] == 0 else "SELL"
            pnl = p.get("profit", 0)
            c = _pnl_color(pnl)
            print(f"    ticket={p['ticket']} {direction} vol={p['volume']} "
                  f"entry={p['price_open']} sl={p['sl']} tp={p['tp']} "
                  f"P&L={c}{pnl:+.2f} EUR{RST}")

    # ── Last 5 H4 bars ──
    print(f"\n  {BLD}Last 5 H4 bars:{RST}")
    for b in bars_h4[-5:]:
        raw_t = b.get("time", "")
        try:
            t = datetime.strptime(str(raw_t)[:19], "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M") if "T" not in str(raw_t) else datetime.fromisoformat(str(raw_t)[:19]).strftime("%m-%d %H:%M")
        except Exception:
            t = str(raw_t)[:16]
        rng = b["high"] - b["low"]
        body = abs(b["close"] - b["open"])
        color = GRN if b["close"] >= b["open"] else RED
        candle = "▲" if b["close"] >= b["open"] else "▼"
        print(f"    {DIM}{t}{RST}  {color}{candle}{RST} "
              f"O={b['open']:.5f} H={b['high']:.5f} L={b['low']:.5f} C={b['close']:.5f}  "
              f"range={rng:.5f}  body={body:.5f}")

    print()


def cmd_buy(symbol, volume, sl, tp):
    print(f"\n  Placing BUY {symbol} vol={volume} SL={sl} TP={tp} ...")
    tick = get_tick(symbol)
    if tick:
        ask = tick.get("ask", 0)
        risk = abs(ask - sl)
        reward = abs(tp - ask)
        rr = reward / risk if risk > 0 else 0
        print(f"  Entry={ask:.5f}  Risk={risk:.5f}  Reward={reward:.5f}  R:R={rr:.2f}")
        if rr < 1.5:
            print(f"  {RED}{BLD}REJECTED: R:R={rr:.2f} < 1.5 minimum{RST}")
            return
    result = send_order(symbol, "BUY", volume, sl, tp)
    if result and "result" in result:
        r = result["result"]
        ticket = r.get("order", r.get("ticket", "?"))
        price = r.get("price", "?")
        print(f"  {GRN}{BLD}ORDER PLACED  ticket={ticket}  price={price}{RST}")
    else:
        print(f"  {RED}FAILED: {result}{RST}")


def cmd_sell(symbol, volume, sl, tp):
    print(f"\n  Placing SELL {symbol} vol={volume} SL={sl} TP={tp} ...")
    tick = get_tick(symbol)
    if tick:
        bid = tick.get("bid", 0)
        risk = abs(bid - sl)
        reward = abs(tp - bid)
        rr = reward / risk if risk > 0 else 0
        print(f"  Entry={bid:.5f}  Risk={risk:.5f}  Reward={reward:.5f}  R:R={rr:.2f}")
        if rr < 1.5:
            print(f"  {RED}{BLD}REJECTED: R:R={rr:.2f} < 1.5 minimum{RST}")
            return
    result = send_order(symbol, "SELL", volume, sl, tp)
    if result and "result" in result:
        r = result["result"]
        ticket = r.get("order", r.get("ticket", "?"))
        price = r.get("price", "?")
        print(f"  {GRN}{BLD}ORDER PLACED  ticket={ticket}  price={price}{RST}")
    else:
        print(f"  {RED}FAILED: {result}{RST}")


def cmd_close(ticket):
    positions = get_positions()
    pos = next((p for p in positions if str(p["ticket"]) == str(ticket)), None)
    if not pos:
        print(f"  {RED}No open position with ticket {ticket}{RST}")
        return
    direction = "BUY" if pos["type"] == 0 else "SELL"
    pnl = pos.get("profit", 0)
    c = _pnl_color(pnl)
    print(f"\n  Closing ticket={ticket} {pos['symbol']} {direction} "
          f"vol={pos['volume']} P&L={c}{pnl:+.2f} EUR{RST} ...")
    result = close_position(ticket, pos["symbol"], pos["type"], pos["volume"])
    if result and "result" in result:
        r = result["result"]
        print(f"  {GRN}{BLD}CLOSED  profit={r.get('profit', '?')}{RST}")
    else:
        print(f"  {RED}FAILED: {result}{RST}")


def cmd_close_all():
    positions = get_positions()
    if not positions:
        print(f"  {DIM}No open positions.{RST}")
        return
    print(f"\n  Closing {len(positions)} position(s)...")
    for pos in positions:
        ticket = pos["ticket"]
        direction = "BUY" if pos["type"] == 0 else "SELL"
        pnl = pos.get("profit", 0)
        c = _pnl_color(pnl)
        result = close_position(ticket, pos["symbol"], pos["type"], pos["volume"])
        if result and "result" in result:
            print(f"  {GRN}✓{RST} {pos['symbol']} {direction} ticket={ticket} P&L={c}{pnl:+.2f}{RST}")
        else:
            print(f"  {RED}✗{RST} {pos['symbol']} ticket={ticket} FAILED: {result}")


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("help", "--help", "-h"):
        print(__doc__)
        return

    cmd = args[0].lower()

    if cmd == "status":
        cmd_status()

    elif cmd == "scan":
        cmd_scan()

    elif cmd == "analyze":
        if len(args) < 2:
            print("Usage: analyze SYMBOL"); return
        cmd_analyze(args[1].upper())

    elif cmd == "buy":
        if len(args) < 5:
            print("Usage: buy SYMBOL VOLUME SL TP"); return
        cmd_buy(args[1].upper(), float(args[2]), float(args[3]), float(args[4]))

    elif cmd == "sell":
        if len(args) < 5:
            print("Usage: sell SYMBOL VOLUME SL TP"); return
        cmd_sell(args[1].upper(), float(args[2]), float(args[3]), float(args[4]))

    elif cmd == "close":
        if len(args) < 2:
            print("Usage: close TICKET"); return
        cmd_close(args[1])

    elif cmd == "close-all":
        confirm = input("Close ALL positions? (yes/no): ").strip().lower()
        if confirm == "yes":
            cmd_close_all()
        else:
            print("Cancelled.")

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()

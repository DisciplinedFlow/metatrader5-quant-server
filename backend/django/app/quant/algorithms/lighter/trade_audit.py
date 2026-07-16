"""One-off audit: pull exchange trade history and compute real PnL + fees."""
import os, sys, requests, json
from datetime import datetime, timezone

PROXY = os.environ.get("LIGHTER_SIGNER_PROXY_URL", "http://host.docker.internal:5555")
resp = requests.get(PROXY + "/trades", params={"limit": 100}, timeout=10)
data = resp.json()
trades = data["trades"]

OUR = 718566
total_fees = 0.0
total_pnl = 0.0
sym_map = {0: "ETH", 1: "BTC", 2: "SOL", 92: "XAU", 93: "XAG", 96: "EUR"}

for t in sorted(trades, key=lambda x: x["timestamp"]):
    ts = int(t["timestamp"]) / 1000
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
    mid = t["market_id"]
    sym = sym_map.get(mid, "m" + str(mid))
    price = float(t["price"])
    size = float(t["size"])
    usd = float(t["usd_amount"])

    is_ask = (t["ask_account_id"] == OUR)
    is_bid = (t["bid_account_id"] == OUR)

    if is_ask:
        side = "SELL"
        fee_raw = t.get("maker_fee", 0) if t.get("is_maker_ask") else t.get("taker_fee", 0)
        pnl = float(t.get("ask_account_pnl") or 0)
    elif is_bid:
        side = " BUY"
        fee_raw = t.get("taker_fee", 0) if t.get("is_maker_ask") else t.get("maker_fee", 0)
        pnl = float(t.get("bid_account_pnl") or 0)
    else:
        continue

    fee_usd = fee_raw * usd / 1000000.0
    total_fees += fee_usd
    total_pnl += pnl

    p = ""
    if pnl != 0:
        p = "pnl=%+.4f" % pnl
    print("%s %4s %s px=%10.3f sz=%8.4f $%8.2f fee=$%.4f %s" % (
        dt, sym, side, price, size, usd, fee_usd, p))

print("")
print("Total fills: %d" % len(trades))
print("Realized PnL: $%.4f" % total_pnl)
print("Total fees: $%.4f" % total_fees)
print("Net: $%.4f" % (total_pnl - total_fees))

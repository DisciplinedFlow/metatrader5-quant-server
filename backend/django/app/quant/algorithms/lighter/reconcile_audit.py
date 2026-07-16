"""Cross-reference DB positions with Lighter exchange fills."""
import os, sys, requests
from datetime import datetime, timezone

sys.path.insert(0, "/app")
os.environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
import django; django.setup()

from app.crypto.models import CryptoPosition, CryptoTrade

PROXY = os.environ.get("LIGHTER_SIGNER_PROXY_URL", "http://host.docker.internal:5555")
OUR = 718566

# ── Fetch ALL exchange trades ──
all_exchange = []
cursor = None
for _ in range(5):
    params = {"limit": 100}
    if cursor:
        params["cursor"] = cursor
    resp = requests.get(PROXY + "/trades", params=params, timeout=10)
    data = resp.json()
    trades = data.get("trades", [])
    all_exchange.extend(trades)
    cursor = data.get("next_cursor")
    if not cursor or not trades:
        break

SYM_MAP = {
    0: "ETH", 1: "BTC", 2: "SOL", 3: "DOGE", 9: "AVAX", 10: "NEAR",
    92: "XAU", 93: "XAG", 96: "EURUSD", 112: "TSLA",
}

# ── Parse exchange fills ──
exchange_fills = []
for t in all_exchange:
    is_ask = (t["ask_account_id"] == OUR)
    is_bid = (t["bid_account_id"] == OUR)
    if not is_ask and not is_bid:
        continue

    mid = t["market_id"]
    sym = SYM_MAP.get(mid, "m%d" % mid)
    side = "SELL" if is_ask else "BUY"
    pnl = float(t.get("ask_account_pnl") or 0) if is_ask else float(t.get("bid_account_pnl") or 0)

    if is_ask:
        fee_raw = t.get("maker_fee", 0) if t.get("is_maker_ask") else t.get("taker_fee", 0)
    else:
        fee_raw = t.get("taker_fee", 0) if t.get("is_maker_ask") else t.get("maker_fee", 0)

    usd = float(t.get("usd_amount", 0))
    fee_usd = float(fee_raw or 0) * usd / 1000000.0

    exchange_fills.append({
        "ts": int(t["timestamp"]),
        "sym": sym,
        "side": side,
        "price": float(t["price"]),
        "size": float(t["size"]),
        "usd": usd,
        "pnl": pnl,
        "fee_usd": fee_usd,
        "tx": t.get("tx_hash", "")[:20],
    })

exchange_fills.sort(key=lambda x: x["ts"])

# ── DB positions ──
db_all = list(CryptoPosition.objects.all().order_by("opened_at"))

# ── Per-symbol comparison ──
exch_pnl = {}
exch_fees = {}
exch_vol = {}
exch_count = {}

for f in exchange_fills:
    k = f["sym"]
    exch_pnl[k] = exch_pnl.get(k, 0) + f["pnl"]
    exch_fees[k] = exch_fees.get(k, 0) + f["fee_usd"]
    exch_vol[k] = exch_vol.get(k, 0) + f["usd"]
    exch_count[k] = exch_count.get(k, 0) + 1

db_pnl = {}
db_fees = {}
db_count = {}

for p in db_all:
    k = p.symbol
    db_pnl[k] = db_pnl.get(k, 0) + float(p.pnl_usd or 0)
    db_count[k] = db_count.get(k, 0) + 1
    for t in p.trades.all():
        db_fees[k] = db_fees.get(k, 0) + float(t.fee or 0)

all_syms = sorted(set(list(exch_pnl.keys()) + list(db_pnl.keys())))

print("%-5s %6s %6s %10s %10s %10s %10s %10s" % (
    "SYM", "DB#", "EX#", "DB_PNL", "EXCH_PNL", "DIFF", "EXCH_FEES", "EXCH_VOL"))
print("-" * 80)

t_db = t_ex = t_dbf = t_exf = 0
for sym in all_syms:
    dp = db_pnl.get(sym, 0)
    ep = exch_pnl.get(sym, 0)
    df = db_fees.get(sym, 0)
    ef = exch_fees.get(sym, 0)
    dc = db_count.get(sym, 0)
    ec = exch_count.get(sym, 0)
    ev = exch_vol.get(sym, 0)
    diff = dp - ep
    t_db += dp; t_ex += ep; t_dbf += df; t_exf += ef
    flag = " ***" if abs(diff) > 0.5 else ""
    print("%-5s %6d %6d $%9.4f $%9.4f $%9.4f $%9.4f $%9.0f%s" % (
        sym, dc, ec, dp, ep, diff, ef, ev, flag))

print("-" * 80)
print("%-5s %6s %6s $%9.4f $%9.4f $%9.4f $%9.4f" % (
    "TOTAL", "", "", t_db, t_ex, t_db - t_ex, t_exf))

# ── TX hash matching ──
db_txs = set()
for p in db_all:
    for t in p.trades.all():
        if t.order_id:
            db_txs.add(t.order_id[:20])

matched = sum(1 for f in exchange_fills if f["tx"] in db_txs)
print("\nExchange fills: %d | DB positions: %d" % (len(exchange_fills), len(db_all)))
print("TX matched: %d/%d | Unmatched (ghost): %d" % (matched, len(exchange_fills), len(exchange_fills) - matched))

# ── Show ghost fills ──
ghosts = [f for f in exchange_fills if f["tx"] not in db_txs and f["pnl"] != 0]
if ghosts:
    print("\n=== Ghost fills with PnL impact ===")
    for g in ghosts:
        ts = datetime.fromtimestamp(g["ts"] / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")
        print("  %s %4s %s px=%.3f sz=%.4f $%.2f pnl=%+.4f fee=$%.4f" % (
            ts, g["sym"], g["side"], g["price"], g["size"], g["usd"], g["pnl"], g["fee_usd"]))
    ghost_pnl = sum(g["pnl"] for g in ghosts)
    ghost_fees = sum(g["fee_usd"] for g in ghosts)
    print("  Ghost total: pnl=$%.4f fees=$%.4f" % (ghost_pnl, ghost_fees))

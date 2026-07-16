"""
Backfill: Reconcile exchange trade history with DB positions.

Groups exchange fills into position lifecycles (open→close) by symbol,
then matches to existing DB positions or creates new ones for ghosts.

Run: docker exec celery-crypto python3 /tmp/backfill_trades.py
"""
import os, sys, requests
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, "/app")
os.environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
import django; django.setup()

from app.crypto.models import CryptoPosition, CryptoTrade
from django.db import transaction

PROXY = os.environ.get("LIGHTER_SIGNER_PROXY_URL", "http://host.docker.internal:5555")
OUR = 718566
SYM_MAP = {
    0: "ETH", 1: "BTC", 2: "SOL", 3: "DOGE", 9: "AVAX", 10: "NEAR",
    92: "XAU", 93: "XAG", 96: "EURUSD", 112: "TSLA",
}

DRY_RUN = "--apply" not in sys.argv

# ── Fetch exchange trades ──
resp = requests.get(PROXY + "/trades", params={"limit": 100}, timeout=10)
data = resp.json()
trades = data.get("trades", [])

# Parse and dedup
seen = set()
fills = []
for t in trades:
    tid = str(t.get("trade_id_str", t.get("trade_id")))
    if tid in seen:
        continue
    seen.add(tid)

    is_ask = (t["ask_account_id"] == OUR)
    is_bid = (t["bid_account_id"] == OUR)
    if not is_ask and not is_bid:
        continue

    mid = t["market_id"]
    sym = SYM_MAP.get(mid, "m%d" % mid)
    side = "SELL" if is_ask else "BUY"
    price = float(t["price"])
    size = float(t["size"])
    usd = float(t.get("usd_amount", 0))
    tx = t.get("tx_hash", "")

    if is_ask:
        pnl = float(t.get("ask_account_pnl") or 0)
        fee_raw = t.get("maker_fee", 0) if t.get("is_maker_ask") else t.get("taker_fee", 0)
    else:
        pnl = float(t.get("bid_account_pnl") or 0)
        fee_raw = t.get("taker_fee", 0) if t.get("is_maker_ask") else t.get("maker_fee", 0)

    fee_usd = float(fee_raw or 0) * usd / 1_000_000

    fills.append({
        "ts": int(t["timestamp"]),
        "sym": sym,
        "side": side,
        "price": price,
        "size": size,
        "usd": usd,
        "pnl": pnl,
        "fee_usd": fee_usd,
        "tx": tx,
    })

fills.sort(key=lambda x: x["ts"])
print("Exchange fills (deduped): %d" % len(fills))

# ── Get existing DB trade tx hashes ──
db_txs = set()
for t in CryptoTrade.objects.all():
    if t.order_id:
        db_txs.add(t.order_id)

# ── Find unmatched fills ──
unmatched = [f for f in fills if f["tx"] not in db_txs]
matched = len(fills) - len(unmatched)
print("Already matched in DB: %d" % matched)
print("Unmatched fills to backfill: %d" % len(unmatched))

if not unmatched:
    print("Nothing to backfill!")
    sys.exit(0)

# ── Group unmatched fills into position lifecycles ──
# For each symbol, track net position. When net crosses zero, that's a closed position.
# Fills with realized PnL are closing fills.

# Separate opening fills (no pnl) from closing fills (has pnl)
opens = [f for f in unmatched if f["pnl"] == 0]
closes = [f for f in unmatched if f["pnl"] != 0]

print("\nUnmatched opens: %d" % len(opens))
print("Unmatched closes: %d" % len(closes))

# ── Group closing fills by approximate time (within 5s = same position close) ──
close_groups = []
for f in closes:
    added = False
    for g in close_groups:
        if g["sym"] == f["sym"] and abs(g["fills"][-1]["ts"] - f["ts"]) < 5000:
            g["fills"].append(f)
            g["total_pnl"] += f["pnl"]
            g["total_fee"] += f["fee_usd"]
            g["total_size"] += f["size"]
            added = True
            break
    if not added:
        close_groups.append({
            "sym": f["sym"],
            "fills": [f],
            "total_pnl": f["pnl"],
            "total_fee": f["fee_usd"],
            "total_size": f["size"],
        })

print("\nGhost position closes to create: %d" % len(close_groups))
print()

# ── Match close groups to existing DB positions or create new ones ──
created = 0
updated = 0

for g in close_groups:
    sym = g["sym"]
    close_ts = datetime.fromtimestamp(g["fills"][0]["ts"] / 1000, tz=timezone.utc)
    close_price = sum(f["price"] * f["size"] for f in g["fills"]) / max(g["total_size"], 0.0001)
    pnl = g["total_pnl"]
    fee = g["total_fee"]

    # Determine close side (if closing fill is BUY, position was SHORT)
    close_side = g["fills"][0]["side"]
    pos_side = "SHORT" if close_side == "BUY" else "LONG"

    # Try to find matching DB position (same symbol, same side, closed near same time)
    db_match = CryptoPosition.objects.filter(
        symbol=sym,
        side=pos_side,
        status="CLOSED",
        closed_at__gte=close_ts - __import__("datetime").timedelta(seconds=30),
        closed_at__lte=close_ts + __import__("datetime").timedelta(seconds=30),
    ).first()

    ts_str = close_ts.strftime("%m-%d %H:%M:%S")

    if db_match:
        # Already tracked — check if PnL matches
        db_pnl = float(db_match.pnl_usd or 0)
        diff = abs(db_pnl - pnl)
        if diff > 0.01:
            print("  UPDATE %s %s %s: DB pnl=$%.4f -> exch pnl=$%.4f (diff=$%.4f)" % (
                ts_str, sym, pos_side, db_pnl, pnl, diff))
            if not DRY_RUN:
                db_match.pnl_usd = pnl
                db_match.save(update_fields=["pnl_usd"])
            updated += 1
        else:
            pass  # Already correct
    else:
        # Ghost position — find corresponding open fills
        # Look for opening fills for same symbol before the close
        open_fills = [f for f in opens if f["sym"] == sym and f["ts"] < g["fills"][0]["ts"]]

        if open_fills:
            # Use the most recent batch of opens
            entry_price = sum(f["price"] * f["size"] for f in open_fills) / sum(f["size"] for f in open_fills)
            entry_size = sum(f["size"] for f in open_fills)
            entry_ts = datetime.fromtimestamp(open_fills[0]["ts"] / 1000, tz=timezone.utc)
            entry_fee = sum(f["fee_usd"] for f in open_fills)
        else:
            # No matching opens — estimate from close price and pnl
            entry_price = close_price
            entry_size = g["total_size"]
            entry_ts = close_ts - __import__("datetime").timedelta(seconds=60)
            entry_fee = 0

        print("  CREATE %s %s %s: entry=%.3f close=%.3f size=%.4f pnl=$%.4f fee=$%.4f" % (
            ts_str, sym, pos_side, entry_price, close_price, entry_size, pnl, fee))

        if not DRY_RUN:
            with transaction.atomic():
                pos = CryptoPosition.objects.create(
                    symbol=sym,
                    side=pos_side,
                    entry_price=entry_price,
                    size=entry_size,
                    leverage=15,
                    entry_signal="lighter:backfilled",
                    stop_loss=0,
                    take_profit=0,
                    status="CLOSED",
                    venue="LIGHTER",
                    pnl_usd=pnl,
                    close_price=close_price,
                    close_reason="BACKFILLED",
                    opened_at=entry_ts,
                    closed_at=close_ts,
                )

                # Create close trade record
                for f in g["fills"]:
                    CryptoTrade.objects.create(
                        position=pos,
                        order_id=f["tx"],
                        side=f["side"],
                        price=f["price"],
                        size=f["size"],
                        fee=f["fee_usd"],
                        status="FILLED",
                    )

                # Create entry trade records
                for f in open_fills:
                    CryptoTrade.objects.create(
                        position=pos,
                        order_id=f["tx"],
                        side=f["side"],
                        price=f["price"],
                        size=f["size"],
                        fee=f["fee_usd"],
                        status="FILLED",
                    )

        created += 1

print()
if DRY_RUN:
    print("=== DRY RUN === (run with --apply to execute)")
    print("Would create: %d positions" % created)
    print("Would update: %d positions" % updated)
else:
    print("Created: %d positions" % created)
    print("Updated: %d positions" % updated)

# Final count
total = CryptoPosition.objects.count()
closed = CryptoPosition.objects.filter(status="CLOSED").count()
print("DB total: %d (closed: %d)" % (total, closed))

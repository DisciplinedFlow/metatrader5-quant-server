#!/usr/bin/env python3
"""
Lighter.xyz broker win-rate computation.
Fetches all closed orders from the exchange and computes real P&L statistics.

Run on macOS (not Docker) — lighter-sdk requires native Go library.
  cd backend/lighter-proxy && python3 winrate.py
"""
import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env')

import lighter

API_URL = os.getenv('LIGHTER_API_URL', 'https://mainnet.zklighter.elliot.ai')
PRIVATE_KEY = os.getenv('LIGHTER_PRIVATE_KEY', '')
API_KEY_INDEX = int(os.getenv('LIGHTER_API_KEY_INDEX', '2'))
ACCOUNT_INDEX = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '718566'))

# market_id → symbol name (from proxy.py MARKETS dict)
MARKET_IDS = {
    0: 'ETH', 1: 'BTC', 2: 'SOL', 3: 'DOGE', 7: 'XRP', 8: 'LINK',
    9: 'AVAX', 10: 'NEAR', 11: 'DOT', 12: 'TON', 16: 'SUI', 24: 'HYPE',
    25: 'BNB', 27: 'AAVE', 39: 'ADA', 48: 'PAXG', 50: 'ARB', 55: 'OP',
    92: 'XAU', 93: 'XAG', 96: 'EURUSD', 97: 'GBPUSD', 98: 'USDJPY',
    99: 'USDCHF', 100: 'USDCAD', 106: 'AUDUSD', 107: 'NZDUSD',
    110: 'NVDA', 112: 'TSLA', 113: 'AAPL', 114: 'AMZN', 115: 'MSFT',
    116: 'GOOGL', 117: 'META', 128: 'SPY', 129: 'QQQ', 145: 'WTI',
}


async def fetch_all_orders():
    """Fetch all inactive (filled/cancelled) orders with cursor pagination."""
    signer = lighter.SignerClient(
        url=API_URL,
        api_private_keys={API_KEY_INDEX: PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )
    err = signer.check_client()
    if err is not None:
        raise ConnectionError("SignerClient check failed: {}".format(err))

    token, _ = signer.create_auth_token_with_expiry(-1, api_key_index=API_KEY_INDEX)

    api_client = lighter.ApiClient(configuration=lighter.Configuration(host=API_URL))
    order_api = lighter.OrderApi(api_client)

    all_orders = []
    cursor = None
    page = 0

    while True:
        page += 1
        kwargs = dict(account_index=ACCOUNT_INDEX, limit=100, auth=token)
        if cursor:
            kwargs['cursor'] = cursor

        resp = await order_api.account_inactive_orders_without_preload_content(**kwargs)
        body = await resp.read()
        data = json.loads(body.decode())

        if page == 1:
            # Show top-level keys so we know the pagination field names
            top_keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            print("  Response keys: {}".format(top_keys))

        orders = data.get('account_orders', data.get('orders', [])) if isinstance(data, dict) else data
        if not orders:
            break

        all_orders.extend(orders)
        # Use earliest order_index as cursor for next page (descending order pagination)
        earliest = min(o.get('order_index', 0) for o in orders)
        print("  Page {}: {} orders (total {}) earliest_idx={}".format(
            page, len(orders), len(all_orders), earliest))

        if page == 1:
            # Show all pagination-related fields from response
            for k, v in data.items():
                if k != 'account_orders' and k != 'orders':
                    print("  Pagination field '{}': {}".format(k, v))

        # Cursor / has_next pagination — try multiple conventions
        has_next = data.get('has_next', data.get('hasNext', len(orders) >= 100))
        next_cursor = data.get('next', data.get('cursor', data.get('next_cursor', earliest - 1)))
        if not has_next or len(orders) < 100:
            break
        cursor = next_cursor

        # Refresh auth token every 5 pages (token valid ~10 min)
        if page % 5 == 0:
            token, _ = signer.create_auth_token_with_expiry(-1, api_key_index=API_KEY_INDEX)

    await api_client.close()
    return all_orders, data  # return last data page for field inspection


def _fval(o, *keys, default=0.0):
    """Try multiple field names, return float."""
    for k in keys:
        v = o.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return default


def simulate_trades(orders):
    """
    Simulate FIFO position accounting to extract closed trades with P&L.

    Entry: reduce_only=False, filled_base_amount > 0
    Exit:  reduce_only=True,  filled_base_amount > 0

    LONG position: entry is_ask=False (BUY), exit is_ask=True (SELL)
    SHORT position: entry is_ask=True (SELL), exit is_ask=False (BUY)
    """
    def sort_key(o):
        return o.get('created_at') or o.get('updated_at') or o.get('timestamp') or ''

    sorted_orders = sorted(orders, key=sort_key)

    # Filter to filled orders only
    filled = []
    for o in sorted_orders:
        status = str(o.get('status', '')).upper()
        size = _fval(o, 'filled_base_amount', 'filled_amount', 'base_amount')
        if size > 0 and status in ('FILLED', 'PARTIALLY_FILLED', ''):
            filled.append(o)

    # Include all orders that have filled_base_amount > 0 regardless of status text
    if not filled:
        filled = [o for o in sorted_orders if _fval(o, 'filled_base_amount', 'filled_amount') > 0]

    # FIFO position stacks per market: {market_id: [{'size', 'entry_price', 'is_long', ...}]}
    open_positions = defaultdict(list)
    closed_trades = []

    for o in filled:
        market_id = o.get('market_index')
        is_ask = bool(o.get('is_ask', False))       # True = SELL side
        reduce_only = bool(o.get('reduce_only', False))
        size = _fval(o, 'filled_base_amount', 'filled_amount', 'base_amount')
        price = _fval(o, 'avg_filled_price', 'price', 'avg_price', 'filled_price')

        if size <= 0 or price <= 0:
            continue

        symbol = MARKET_IDS.get(market_id, 'MKT{}'.format(market_id))
        raw_ts = o.get('created_at') or o.get('timestamp') or 0
        try:
            ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        except Exception:
            ts = str(raw_ts)[:19]

        if not reduce_only:
            # Opening: push to stack
            is_long = not is_ask  # BUY = LONG
            open_positions[market_id].append({
                'size': size,
                'entry_price': price,
                'is_long': is_long,
                'symbol': symbol,
                'entry_ts': ts,
            })
        else:
            # Closing: match against open stack (FIFO)
            # Closing a LONG means is_ask=True (selling); closing a SHORT means is_ask=False (buying)
            closing_long = is_ask  # True = closing a LONG position

            remaining = size
            new_stack = []
            for pos in open_positions[market_id]:
                if pos['is_long'] != closing_long or remaining <= 0:
                    new_stack.append(pos)
                    continue

                close_size = min(remaining, pos['size'])
                remaining -= close_size

                if pos['is_long']:
                    pnl = (price - pos['entry_price']) * close_size
                else:
                    pnl = (pos['entry_price'] - price) * close_size

                closed_trades.append({
                    'symbol': symbol,
                    'side': 'LONG' if pos['is_long'] else 'SHORT',
                    'entry_price': pos['entry_price'],
                    'exit_price': price,
                    'size': close_size,
                    'pnl': pnl,
                    'entry_ts': pos['entry_ts'],
                    'exit_ts': ts,
                    'won': pnl > 0,
                })

                leftover = pos['size'] - close_size
                if leftover > 1e-9:
                    pos_copy = dict(pos)
                    pos_copy['size'] = leftover
                    new_stack.append(pos_copy)

            open_positions[market_id] = new_stack

    return closed_trades, open_positions


def print_report(trades, open_positions):
    if not trades:
        print("\nNo closed trades found — nothing to analyse.")
        return

    wins = [t for t in trades if t['won']]
    losses = [t for t in trades if not t['won']]
    win_rate = len(wins) / len(trades) * 100
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss else float('inf')

    print("\n" + "=" * 62)
    print("  LIGHTER.XYZ BROKER WIN-RATE REPORT")
    print("=" * 62)
    print("{:<26} {}".format("Total closed trades:", len(trades)))
    print("{:<26} {} ({:.1f}%)".format("Wins:", len(wins), win_rate))
    print("{:<26} {} ({:.1f}%)".format("Losses:", len(losses), 100 - win_rate))
    print("{:<26} ${:.4f}".format("Total P&L:", total_pnl))
    print("{:<26} ${:.4f}".format("Avg win:", avg_win))
    print("{:<26} ${:.4f}".format("Avg loss:", avg_loss))
    print("{:<26} {:.2f}".format("Profit factor:", profit_factor))
    best = max(trades, key=lambda t: t['pnl'])
    worst = min(trades, key=lambda t: t['pnl'])
    print("{:<26} ${:.4f}  ({} {})".format("Best trade:", best['pnl'], best['symbol'], best['side']))
    print("{:<26} ${:.4f}  ({} {})".format("Worst trade:", worst['pnl'], worst['symbol'], worst['side']))

    # ── By symbol ──────────────────────────────────────────────
    print("\n{:<8} {:>7} {:>6} {:>7} {:>11}".format("Symbol", "Trades", "Wins", "WR%", "P&L"))
    print("-" * 42)
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t['symbol']].append(t)
    for sym in sorted(by_sym):
        ts = by_sym[sym]
        w = sum(1 for t in ts if t['won'])
        wr = w / len(ts) * 100
        pnl = sum(t['pnl'] for t in ts)
        print("{:<8} {:>7} {:>6} {:>6.1f}% {:>11.4f}".format(sym, len(ts), w, wr, pnl))

    # ── Last 25 trades ─────────────────────────────────────────
    print("\n{:<12} {:<6} {:<5} {:>12} {:>12} {:>10} {}".format(
        "Date", "Sym", "Side", "Entry", "Exit", "PNL", "W/L"
    ))
    print("-" * 72)
    for t in trades[-25:]:
        print("{:<12} {:<6} {:<5} {:>12.4f} {:>12.4f} {:>10.4f} {}".format(
            t['exit_ts'][:10],
            t['symbol'],
            t['side'][:4],
            t['entry_price'],
            t['exit_price'],
            t['pnl'],
            "WIN" if t['won'] else "LOSS",
        ))

    # ── Still-open positions ───────────────────────────────────
    open_count = sum(len(v) for v in open_positions.values())
    if open_count:
        print("\n--- {} Still-Open (unmatched entry) ---".format(open_count))
        for mid, positions in open_positions.items():
            sym = MARKET_IDS.get(mid, 'MKT{}'.format(mid))
            for pos in positions:
                print("  {} {} size={:.6f} @ {:.4f}  entered {}".format(
                    sym,
                    'LONG' if pos['is_long'] else 'SHORT',
                    pos['size'],
                    pos['entry_price'],
                    pos['entry_ts'],
                ))


async def main():
    print("Account: {}  Key index: {}".format(ACCOUNT_INDEX, API_KEY_INDEX))
    print("Fetching all inactive orders from Lighter exchange...")
    orders, last_page = await fetch_all_orders()
    print("\nTotal raw orders fetched: {}".format(len(orders)))

    if not orders:
        print("No orders found — check auth and account index.")
        return

    # Show raw structure of first order for debugging
    print("\n--- Sample order fields ---")
    print(json.dumps(orders[0], indent=2, default=str)[:1000])

    trades, open_positions = simulate_trades(orders)
    print_report(trades, open_positions)


if __name__ == '__main__':
    asyncio.run(main())

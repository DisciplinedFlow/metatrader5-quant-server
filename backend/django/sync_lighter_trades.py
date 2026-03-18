"""Correlate exchange fills with DB positions since the brain wipe (Mar 16 05:32 UTC)."""
import os, asyncio, sys, json
from datetime import datetime, timezone as tz
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
import django; django.setup()
import lighter

from app.crypto.models import CryptoPosition
from app.quant.algorithms.lighter.config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from collections import Counter, defaultdict

LIGHTER_API_URL = os.environ.get('LIGHTER_API_URL', 'https://mainnet.zklighter.elliot.ai')
ACCT = int(os.environ.get('LIGHTER_ACCOUNT_INDEX', 718566))
PRIVATE_KEY = os.environ.get('LIGHTER_PRIVATE_KEY', '')
API_KEY_INDEX = int(os.environ.get('LIGHTER_API_KEY_INDEX', 2))
ID_TO_SYM = {v['id']: k for k, v in LIGHTER_MARKETS.items()}

# DB wipe timestamp
WIPE_TS = int(datetime(2026, 3, 16, 5, 32, 0, tzinfo=tz.utc).timestamp() * 1000)


async def fetch_all_trades():
    api = lighter.ApiClient(configuration=lighter.Configuration(host=LIGHTER_API_URL))
    signer = lighter.SignerClient(url=LIGHTER_API_URL, account_index=ACCT, api_private_keys={API_KEY_INDEX: PRIVATE_KEY})
    try:
        token = signer.create_auth_token_with_expiry(api_key_index=API_KEY_INDEX)[0]
        order_api = lighter.OrderApi(api)
        all_trades = []
        cursor = None
        for page in range(20):
            kwargs = dict(account_index=ACCT, auth=token, limit=100, sort_by='timestamp')
            if cursor:
                kwargs['cursor'] = cursor
            result = await order_api.trades(**kwargs)
            trades = result.trades if hasattr(result, 'trades') else []
            if not trades:
                break
            all_trades.extend(trades)
            cursor = result.next_cursor if hasattr(result, 'next_cursor') else None
            if not cursor:
                break
        return [t.to_dict() if hasattr(t, 'to_dict') else vars(t) for t in all_trades]
    finally:
        await api.close()
        await signer.close()


def analyze(exchange_trades):
    # Filter to only post-wipe fills
    post_wipe = [t for t in exchange_trades if int(t.get('timestamp', 0)) >= WIPE_TS]
    pre_wipe = [t for t in exchange_trades if int(t.get('timestamp', 0)) < WIPE_TS]

    print(f'Total exchange fills: {len(exchange_trades)}')
    print(f'Pre-wipe fills (before Mar 16 05:32): {len(pre_wipe)}')
    print(f'Post-wipe fills (after Mar 16 05:32): {len(post_wipe)}')

    # DB stats
    db_all = list(CryptoPosition.objects.order_by('opened_at').values(
        'id', 'symbol', 'side', 'entry_price', 'size', 'status',
        'opened_at', 'closed_at', 'pnl_usd', 'close_price', 'entry_signal'
    ))
    db_open = [p for p in db_all if p['status'] == 'OPEN']
    db_closed = [p for p in db_all if p['status'] == 'CLOSED']
    print(f'\nDB positions: {len(db_all)} (open={len(db_open)}, closed={len(db_closed)})')

    # Post-wipe fills by symbol
    pw_counts = Counter()
    for t in post_wipe:
        mid = int(t.get('market_id', -1))
        sym = ID_TO_SYM.get(mid, f'mkt_{mid}')
        pw_counts[sym] += 1

    db_counts = Counter()
    for p in db_all:
        db_counts[p['symbol']] += 1

    print('\n=== POST-WIPE: Exchange Fills vs DB Positions ===')
    print(f'{"Symbol":10s} {"Exch Fills":>12s} {"DB Positions":>14s} {"~Expected Pos":>14s} {"Gap":>6s}')
    all_syms = sorted(set(list(pw_counts.keys()) + list(db_counts.keys())))
    total_gap = 0
    for sym in all_syms:
        fills = pw_counts.get(sym, 0)
        db_pos = db_counts.get(sym, 0)
        expected = fills // 2  # rough: each position = open fill + close fill
        gap = expected - db_pos
        total_gap += max(0, gap)
        marker = ' <<<' if gap > 2 else ''
        print(f'{sym:10s} {fills:12d} {db_pos:14d} {expected:14d} {gap:+6d}{marker}')

    print(f'\nTotal estimated missing: ~{total_gap} positions')

    # Try to identify specific missing windows
    # Sort post-wipe fills by time and look for clusters with no DB match
    pw_sorted = sorted(post_wipe, key=lambda t: int(t.get('timestamp', 0)))

    # Build DB timestamp set (minute-level)
    db_minutes = set()
    for p in db_all:
        if p['opened_at']:
            db_minutes.add(int(p['opened_at'].timestamp()) // 60)
        if p['closed_at']:
            db_minutes.add(int(p['closed_at'].timestamp()) // 60)

    # Find gaps: exchange fills with no DB activity within 2 minutes
    gap_fills = []
    for t in pw_sorted:
        ts = int(t.get('timestamp', 0))
        ts_min = ts // 60000
        # Check if any DB activity within 2 minutes
        has_db = any(abs(ts_min - dm) <= 2 for dm in db_minutes)
        if not has_db:
            mid = int(t.get('market_id', -1))
            sym = ID_TO_SYM.get(mid, f'mkt_{mid}')
            dt = datetime.fromtimestamp(ts / 1000, tz=tz.utc)
            gap_fills.append((dt, sym, float(t.get('price', 0)), float(t.get('base_amount', t.get('size', 0)))))

    if gap_fills:
        print(f'\n=== EXCHANGE FILLS WITH NO DB ACTIVITY (proxy was probably down) ===')
        current_hour = None
        for dt, sym, price, size in gap_fills:
            hour_key = dt.strftime('%Y-%m-%d %H:00')
            if hour_key != current_hour:
                print(f'\n  --- {hour_key} UTC ---')
                current_hour = hour_key
            print(f'  {dt.strftime("%H:%M:%S")} {sym:8s} price={price:.4f} size={size:.6f}')
        print(f'\nTotal gap fills: {len(gap_fills)}')


exchange_trades = asyncio.run(fetch_all_trades())
analyze(exchange_trades)

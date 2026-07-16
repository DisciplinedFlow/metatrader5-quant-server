#!/usr/bin/env python3
"""
Lighter.xyz Strategy Backtest + Broker Performance Report
=========================================================

Section 1 — Broker data table: real fill history from exchange (Mar 17-19)
Section 2 — Walk-forward backtest of all 6 CVD strategies + EMA Momentum
             on Binance historical klines (no look-ahead bias)

Run on macOS (lighter-sdk + requests available):
    cd backend/lighter-proxy && python3 strategy_backtest.py
"""
import asyncio
import json
import os
import sys
import time as _time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'django'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

import lighter

API_URL = os.getenv('LIGHTER_API_URL', 'https://mainnet.zklighter.elliot.ai')
PRIVATE_KEY = os.getenv('LIGHTER_PRIVATE_KEY', '')
API_KEY_INDEX = int(os.getenv('LIGHTER_API_KEY_INDEX', '2'))
ACCOUNT_INDEX = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '718566'))

BINANCE_URL = 'https://api.binance.com/api/v3/klines'
LIGHTER_TO_BINANCE = {
    'BTC':  'BTCUSDT',
    'ETH':  'ETHUSDT',
    'SOL':  'SOLUSDT',
    'AVAX': 'AVAXUSDT',
    'DOGE': 'DOGEUSDT',
    # XAU: Binance has no spot gold. Use PAXG (1:1 gold-backed token) as proxy.
    'XAU':  'PAXGUSDT',
}
MARKET_IDS = {
    0: 'ETH', 1: 'BTC', 2: 'SOL', 3: 'DOGE', 7: 'XRP', 8: 'LINK',
    9: 'AVAX', 10: 'NEAR', 11: 'DOT', 12: 'TON', 16: 'SUI', 24: 'HYPE',
    25: 'BNB', 27: 'AAVE', 39: 'ADA', 48: 'PAXG', 50: 'ARB', 55: 'OP',
    92: 'XAU', 93: 'XAG', 96: 'EURUSD', 97: 'GBPUSD', 98: 'USDJPY',
    99: 'USDCHF', 100: 'USDCAD', 106: 'AUDUSD', 107: 'NZDUSD',
    110: 'NVDA', 112: 'TSLA', 113: 'AAPL', 114: 'AMZN', 115: 'MSFT',
    116: 'GOOGL', 117: 'META', 128: 'SPY', 129: 'QQQ', 145: 'WTI',
}

# ── Strategy definitions (from DB) ────────────────────────────────────────────
STRATEGIES = [
    {'name': 'LoP',       'cvd_type': 'lack_of_participants', 'sl': 0.020, 'tp': 0.050, 'tf': '15m'},
    {'name': 'Absorb',    'cvd_type': 'absorption',           'sl': 0.020, 'tp': 0.060, 'tf': '15m'},
    {'name': 'RT-Lead',   'cvd_type': 'real_time_leading',    'sl': 0.015, 'tp': 0.040, 'tf': '15m'},
    {'name': 'Extremes',  'cvd_type': 'extremes',             'sl': 0.030, 'tp': 0.080, 'tf': '15m'},
    {'name': 'MTF',       'cvd_type': 'multi_timeframe',      'sl': 0.020, 'tp': 0.050, 'tf': '1h'},
    {'name': 'SpotPerp',  'cvd_type': 'spot_vs_perpetual',    'sl': 0.025, 'tp': 0.060, 'tf': '15m'},
    {'name': 'EMA-Mom',   'cvd_type': 'ema_momentum',         'sl': 0.020, 'tp': 0.040, 'tf': '1h'},
]

# Pairs to backtest per strategy type
CVD_PAIRS   = ['BTC', 'ETH', 'SOL', 'XAU']   # OB-filtered pairs only
MOM_PAIRS   = ['BTC', 'ETH', 'SOL', 'XAU', 'AVAX', 'DOGE']

LOOKBACK     = 20    # CVD divergence lookback (bars)
CANDLES_15M  = 1000  # ~10 days of 15m bars
CANDLES_1H   = 500   # ~21 days of 1h bars


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Broker data fetcher (identical logic to winrate.py)
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_all_orders():
    signer = lighter.SignerClient(
        url=API_URL,
        api_private_keys={API_KEY_INDEX: PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )
    err = signer.check_client()
    if err is not None:
        raise ConnectionError("SignerClient: {}".format(err))

    token, _ = signer.create_auth_token_with_expiry(-1, api_key_index=API_KEY_INDEX)
    api_client = lighter.ApiClient(configuration=lighter.Configuration(host=API_URL))
    order_api = lighter.OrderApi(api_client)

    all_orders, cursor = [], None
    for page in range(1, 20):
        kwargs = dict(account_index=ACCOUNT_INDEX, limit=100, auth=token)
        if cursor:
            kwargs['cursor'] = cursor
        resp = await order_api.account_inactive_orders_without_preload_content(**kwargs)
        body = await resp.read()
        data = json.loads(body.decode())
        orders = data.get('account_orders', data.get('orders', []))
        if not orders:
            break
        all_orders.extend(orders)
        has_next = data.get('has_next', len(orders) >= 100)
        cursor = data.get('next_cursor')
        if not has_next or not cursor or len(orders) < 100:
            break
        if page % 5 == 0:
            token, _ = signer.create_auth_token_with_expiry(-1, api_key_index=API_KEY_INDEX)

    await api_client.close()
    return all_orders


def _fval(o, *keys):
    for k in keys:
        v = o.get(k)
        if v is not None:
            try: return float(v)
            except: pass
    return 0.0


def simulate_broker_trades(orders):
    """FIFO position accounting to extract closed trades."""
    def ts_key(o):
        return o.get('created_at') or o.get('timestamp') or 0

    filled = [o for o in orders if _fval(o, 'filled_base_amount', 'filled_amount') > 0]
    filled.sort(key=ts_key)

    open_pos = defaultdict(list)
    closed = []

    for o in filled:
        mid      = o.get('market_index')
        is_ask   = bool(o.get('is_ask', False))
        reduce   = bool(o.get('reduce_only', False))
        size     = _fval(o, 'filled_base_amount', 'filled_amount')
        price    = _fval(o, 'avg_filled_price', 'price', 'avg_price')
        symbol   = MARKET_IDS.get(mid, 'MKT{}'.format(mid))
        raw_ts   = o.get('created_at') or o.get('timestamp') or 0
        try:
            ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
        except:
            ts = str(raw_ts)[:16]

        if size <= 0 or price <= 0:
            continue

        if not reduce:
            open_pos[mid].append({'size': size, 'entry': price, 'is_long': not is_ask,
                                  'symbol': symbol, 'ts': ts})
        else:
            closing_long = is_ask
            remaining, new_stack = size, []
            for pos in open_pos[mid]:
                if pos['is_long'] != closing_long or remaining <= 0:
                    new_stack.append(pos); continue
                cs = min(remaining, pos['size'])
                remaining -= cs
                pnl = (price - pos['entry']) * cs if pos['is_long'] else (pos['entry'] - price) * cs
                closed.append({'symbol': symbol, 'side': 'LONG' if pos['is_long'] else 'SHORT',
                                'entry': pos['entry'], 'exit': price, 'size': cs,
                                'pnl': pnl, 'ts_in': pos['ts'], 'ts_out': ts, 'won': pnl > 0})
                if pos['size'] > cs:
                    p = dict(pos); p['size'] = pos['size'] - cs; new_stack.append(p)
            open_pos[mid] = new_stack

    return closed


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Backtest engine
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_binance_klines(symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame:
    """Fetch OHLCV + CVD from Binance. Returns DataFrame with cvd column."""
    bsym = LIGHTER_TO_BINANCE.get(symbol)
    if not bsym:
        return pd.DataFrame()
    try:
        resp = requests.get(BINANCE_URL,
                            params={'symbol': bsym, 'interval': interval, 'limit': limit},
                            timeout=10)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        print("  Binance fetch failed for {} {}: {}".format(symbol, interval, e))
        return pd.DataFrame()

    df = pd.DataFrame(raw, columns=[
        'ts', 'open', 'high', 'low', 'close', 'volume',
        'close_ts', 'quote_vol', 'trades', 'taker_buy_vol', 'taker_buy_quote_vol', '_',
    ])
    for col in ('open', 'high', 'low', 'close', 'volume', 'taker_buy_vol'):
        df[col] = df[col].astype(float)
    df['cvd_delta'] = 2.0 * df['taker_buy_vol'] - df['volume']
    df['cvd'] = df['cvd_delta'].cumsum()
    return df.reset_index(drop=True)


def _detect_cvd(highs, lows, closes, cvd, cvd_type, lookback=20):
    """Single-bar divergence detection — same logic as live cvd_calculator.py."""
    if len(closes) < lookback + 5:
        return 0

    h = highs[-lookback:]
    l = lows[-lookback:]
    c = closes[-lookback:]
    cv = cvd[-lookback:]
    half = lookback // 2
    ph, rh = h[:half], h[half:]
    pl, rl = l[:half], l[half:]
    pcv, rcv = cv[:half], cv[half:]

    if cvd_type in ('lack_of_participants', 'real_time_leading', 'spot_vs_perpetual'):
        if max(rh) > max(ph) and max(rcv) < max(pcv): return -1
        if min(rl) < min(pl) and min(rcv) > min(pcv): return  1

    elif cvd_type == 'absorption':
        if max(rcv) > max(pcv) and max(rh) <= max(ph) * 1.0015: return -1
        if min(rcv) < min(pcv) and min(rl) >= min(pl) * 0.9985: return  1

    elif cvd_type == 'extremes':
        rng = max(h) - min(l)
        if rng < 1e-10: return 0
        pp = (c[-1] - min(l)) / rng
        cv_rng = max(cv) - min(cv)
        cp = (cv[-1] - min(cv)) / (cv_rng + 1e-10)
        if pp > 0.80 and cp < 0.45: return -1
        if pp < 0.20 and cp > 0.55: return  1

    return 0


def _ema(series, span):
    return pd.Series(series).ewm(span=span, adjust=False).mean().values


def _detect_ema_momentum(closes, period_fast=8, period_slow=21):
    """EMA(8/21) momentum signal — mirrors momentum_entry.py logic."""
    if len(closes) < period_slow + 10:
        return 0
    ef  = _ema(closes, period_fast)
    es  = _ema(closes, period_slow)
    ef_prev = _ema(closes[:-1], period_fast)

    sep = abs(ef[-1] - es[-1]) / es[-1] if es[-1] else 0.0
    if sep < 0.003:   # min EMA separation
        return 0

    recent = closes[-5:]
    up = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
    dn = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])

    if ef[-1] > es[-1] and ef[-1] > ef_prev[-1] and up >= 3: return  1
    if ef[-1] < es[-1] and ef[-1] < ef_prev[-1] and dn >= 3: return -1
    return 0


def backtest_strategy(df: pd.DataFrame, cvd_type: str, sl: float, tp: float,
                      max_hold_bars: int = 48) -> list:
    """
    Walk-forward backtest — no look-ahead bias.

    Signal at bar N → entry at open of bar N+1 → exit when SL/TP hit on subsequent bars.
    """
    highs  = df['high'].values
    lows   = df['low'].values
    opens  = df['open'].values
    closes = df['close'].values
    cvd    = df['cvd'].values if 'cvd' in df.columns else np.zeros(len(closes))

    trades = []
    min_start = max(LOOKBACK + 5, 30)
    i = min_start

    while i < len(closes) - 1:
        # Detect signal at bar i using only bars [0..i]
        if cvd_type == 'ema_momentum':
            sig = _detect_ema_momentum(closes[:i+1])
        else:
            sig = _detect_cvd(highs[:i+1], lows[:i+1], closes[:i+1], cvd[:i+1],
                               cvd_type, LOOKBACK)

        if sig == 0:
            i += 1
            continue

        # Entry at next bar's open
        entry_bar = i + 1
        if entry_bar >= len(closes):
            break

        entry_price = opens[entry_bar]
        if sig == 1:   # LONG
            sl_price = entry_price * (1 - sl)
            tp_price = entry_price * (1 + tp)
        else:          # SHORT
            sl_price = entry_price * (1 + sl)
            tp_price = entry_price * (1 - tp)

        # Walk forward bar-by-bar to find exit
        result_pnl = None
        exit_bar = entry_bar
        for j in range(entry_bar + 1, min(entry_bar + max_hold_bars, len(closes))):
            bar_l, bar_h = lows[j], highs[j]
            if sig == 1:
                if bar_l <= sl_price:
                    result_pnl = -sl; exit_bar = j; break
                if bar_h >= tp_price:
                    result_pnl =  tp; exit_bar = j; break
            else:
                if bar_h >= sl_price:
                    result_pnl = -sl; exit_bar = j; break
                if bar_l <= tp_price:
                    result_pnl =  tp; exit_bar = j; break

        if result_pnl is None:
            # Close at last bar (timeout)
            last_close = closes[min(entry_bar + max_hold_bars - 1, len(closes) - 1)]
            result_pnl = (last_close - entry_price) / entry_price * sig
            exit_bar = min(entry_bar + max_hold_bars - 1, len(closes) - 1)

        trades.append({'pnl_pct': result_pnl, 'won': result_pnl > 0,
                       'sig': sig, 'entry_bar': entry_bar, 'exit_bar': exit_bar})
        # Advance past the trade to avoid overlapping entries
        i = exit_bar + 1

    return trades


def compute_stats(trades: list, sl: float, tp: float) -> dict:
    if not trades:
        return {'n': 0, 'wr': 0.0, 'pf': 0.0, 'exp': 0.0, 'total': 0.0}
    wins   = [t for t in trades if t['won']]
    losses = [t for t in trades if not t['won']]
    wr     = len(wins) / len(trades) * 100
    avg_w  = sum(t['pnl_pct'] for t in wins)   / len(wins)   if wins   else 0
    avg_l  = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
    pf     = abs(avg_w / avg_l) if avg_l else 999.0
    exp    = wr / 100 * tp - (1 - wr / 100) * sl   # expected value per trade
    total  = sum(t['pnl_pct'] for t in trades) * 100
    return {'n': len(trades), 'wr': wr, 'pf': pf, 'exp': exp * 100, 'total': total}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Reporting helpers
# ═══════════════════════════════════════════════════════════════════════════════

SEP   = '─' * 80
SEP2  = '═' * 80
RESET = '\033[0m'
RED   = '\033[31m'
GRN   = '\033[32m'
YEL   = '\033[33m'
BOLD  = '\033[1m'


def color(val, good_above=50.0, bad_below=35.0):
    if val >= good_above: return GRN + '{:.1f}'.format(val) + RESET
    if val <= bad_below:  return RED + '{:.1f}'.format(val) + RESET
    return YEL + '{:.1f}'.format(val) + RESET


def print_broker_table(closed_trades):
    """Print broker fill data as formatted table."""
    print()
    print(BOLD + SEP2 + RESET)
    print(BOLD + '  SECTION 1 — BROKER FILLS (Lighter.xyz Mar 17–19 2026)' + RESET)
    print(BOLD + SEP2 + RESET)

    if not closed_trades:
        print('  No closed trades found.')
        return

    wins  = [t for t in closed_trades if t['won']]
    total_pnl = sum(t['pnl'] for t in closed_trades)
    wr    = len(wins) / len(closed_trades) * 100
    avg_w = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_l = sum(t['pnl'] for t in [x for x in closed_trades if not x['won']])
    avg_l = avg_l / (len(closed_trades) - len(wins)) if len(closed_trades) > len(wins) else 0
    pf    = abs(avg_w / avg_l) if avg_l else 999.0

    print()
    print('  {:26}  {}'.format('Total closed trades:', len(closed_trades)))
    print('  {:26}  {} of {} ({})'.format('Win rate:', len(wins), len(closed_trades),
                                           color(wr)))
    print('  {:26}  ${:.4f}'.format('Total P&L:', total_pnl))
    print('  {:26}  ${:.4f}'.format('Avg win:', avg_w))
    print('  {:26}  ${:.4f}'.format('Avg loss:', avg_l))
    print('  {:26}  {:.2f}'.format('Profit factor:', pf))
    print()

    # By symbol
    by_sym = defaultdict(list)
    for t in closed_trades:
        by_sym[t['symbol']].append(t)

    hdr = '  {:<8} {:>7} {:>6} {:>8} {:>11} {:>11} {:>7}'.format(
        'Symbol', 'Trades', 'Wins', 'WR%', 'P&L $', 'AvgWin $', 'AvgLoss')
    print(hdr)
    print('  ' + SEP)
    for sym in sorted(by_sym):
        ts  = by_sym[sym]
        w   = [t for t in ts if t['won']]
        l   = [t for t in ts if not t['won']]
        wr_ = len(w) / len(ts) * 100
        pnl = sum(t['pnl'] for t in ts)
        aw  = sum(t['pnl'] for t in w) / len(w) if w else 0
        al  = sum(t['pnl'] for t in l) / len(l) if l else 0
        wr_col = color(wr_, 40, 25)
        pnl_col = (GRN if pnl >= 0 else RED) + '{:+.4f}'.format(pnl) + RESET
        print('  {:<8} {:>7} {:>6} {:>8} {:>11} {:>11.4f} {:>7.4f}'.format(
            sym, len(ts), len(w), wr_col + '%', pnl_col, aw, al))
    print()

    # Last 20 trades
    print('  {:<12} {:<6} {:<5} {:>10} {:>10} {:>9} {}'.format(
        'Date', 'Sym', 'Side', 'Entry', 'Exit', 'PNL $', 'W/L'))
    print('  ' + SEP)
    for t in closed_trades[-20:]:
        pnl_col = (GRN if t['pnl'] >= 0 else RED) + '{:+.4f}'.format(t['pnl']) + RESET
        print('  {:<12} {:<6} {:<5} {:>10.4f} {:>10.4f} {:>9} {}'.format(
            t['ts_out'][:10], t['symbol'], t['side'][:4],
            t['entry'], t['exit'], pnl_col,
            (GRN + 'WIN' + RESET) if t['won'] else (RED + 'LOSS' + RESET)))


def print_backtest_table(results: dict):
    """Print backtest results as a 2D table: strategies × symbols + combined."""
    print()
    print(BOLD + SEP2 + RESET)
    print(BOLD + '  SECTION 2 — WALK-FORWARD BACKTEST (~1000 bars)' + RESET)
    print(BOLD + SEP2 + RESET)
    print()

    all_syms = sorted(set(sym for key in results if isinstance(key, tuple) for _, sym in [key]))

    # Header row
    col_w = 14
    sym_w = 10
    hdr_parts = ['  {:<12}'.format('Strategy')]
    for sym in all_syms:
        hdr_parts.append('{:^{w}}'.format(sym, w=sym_w))
    hdr_parts.append('{:^{w}}'.format('COMBINED', w=col_w))
    print(''.join(hdr_parts))

    sub = ['  {:<12}'.format('SL%/TP%')]
    strat_configs = {s['name']: s for s in STRATEGIES}
    for strat_name, s in strat_configs.items():
        sub.append('')
    for sym in all_syms:
        sub.append('{:^{w}}'.format('WR% | PF', w=sym_w))
    sub.append('{:^{w}}'.format('WR% | Exp%', w=col_w))
    print(''.join(sub))
    print('  ' + '─' * (12 + sym_w * len(all_syms) + col_w + 2))

    for strat in STRATEGIES:
        sname = strat['name']
        sl_tp = '{:.0f}/{:.0f}%'.format(strat['sl'] * 100, strat['tp'] * 100)
        row = ['  {:<12}'.format('{} {}'.format(sname, sl_tp))]
        all_trades = []

        for sym in all_syms:
            stats = results.get((sname, sym))
            if stats and stats['n'] >= 3:
                cell = '{} | {:.2f}'.format(color(stats['wr'], 40, 30), stats['pf'])
                all_trades.extend(results.get('_trades_' + sname + '_' + sym, []))
            elif stats and stats['n'] > 0:
                cell = '{} n={}'.format(color(stats['wr'], 40, 30), stats['n'])
            else:
                cell = '   —   '
            row.append('{:^{w}}'.format('', w=sym_w))
            # Inline override since ANSI codes confuse width
            row[-1] = cell.center(sym_w) if not cell.startswith('\033') else cell + ' ' * max(0, sym_w - 12)

        # Combined stats across all symbols
        all_t = []
        for sym in all_syms:
            all_t.extend(results.get('_trades_' + sname + '_' + sym, []))
        if all_t:
            cstats = compute_stats(all_t, strat['sl'], strat['tp'])
            combined = '{} | {:+.1f}%'.format(color(cstats['wr'], 40, 30), cstats['exp'])
        else:
            combined = '   —   '
        row.append(combined)
        print(''.join(row))

    print()


def print_summary_verdict(results: dict):
    """Rank strategies by combined expected value."""
    print(BOLD + SEP2 + RESET)
    print(BOLD + '  SECTION 3 — STRATEGY RANKING BY EXPECTED VALUE (backtest)' + RESET)
    print(BOLD + SEP2 + RESET)
    print()
    print('  {:<12} {:>6} {:>8} {:>8} {:>8} {:>10}'.format(
        'Strategy', 'Trades', 'WR%', 'PF', 'Exp%', 'Total%'))
    print('  ' + '─' * 60)

    ranked = []
    for strat in STRATEGIES:
        sname = strat['name']
        all_t = []
        for sym in ['BTC', 'ETH', 'SOL', 'XAU', 'AVAX', 'DOGE']:
            all_t.extend(results.get('_trades_' + sname + '_' + sym, []))
        if not all_t:
            continue
        s = compute_stats(all_t, strat['sl'], strat['tp'])
        ranked.append((sname, s, strat))

    ranked.sort(key=lambda x: x[1]['exp'], reverse=True)

    for sname, s, strat in ranked:
        exp_col = (GRN if s['exp'] > 0 else RED) + '{:+.2f}%'.format(s['exp']) + RESET
        tot_col = (GRN if s['total'] > 0 else RED) + '{:+.1f}%'.format(s['total']) + RESET
        print('  {:<12} {:>6} {:>8} {:>8.2f} {:>8} {:>10}'.format(
            sname, s['n'], color(s['wr'], 40, 30) + '%', s['pf'], exp_col, tot_col))

    print()
    print('  Exp% = expected value per trade = WR × TP − (1−WR) × SL')
    print('  PF   = profit factor (avg_win / avg_loss, ideally > 1.5)')
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print(BOLD + '\n' + SEP2 + RESET)
    print(BOLD + '  LIGHTER.XYZ STRATEGY ANALYSIS' + RESET)
    print(BOLD + '  Generated: {}'.format(
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')) + RESET)
    print(BOLD + SEP2 + RESET)

    # ── 1. Fetch broker data ────────────────────────────────────────────────
    print('\n[1/3] Fetching broker fill history...')
    try:
        orders = await fetch_all_orders()
        print('      {} raw orders fetched'.format(len(orders)))
        closed_trades = simulate_broker_trades(orders)
        print('      {} closed trades matched'.format(len(closed_trades)))
    except Exception as e:
        print('      FAILED: {}'.format(e))
        closed_trades = []

    print_broker_table(closed_trades)

    # ── 2. Fetch candles ────────────────────────────────────────────────────
    print('[2/3] Fetching historical candles from Binance...')
    candles_15m = {}
    candles_1h  = {}

    all_bt_syms = sorted(set(CVD_PAIRS + MOM_PAIRS))
    for sym in all_bt_syms:
        if sym not in LIGHTER_TO_BINANCE:
            continue
        print('      {} 15m...'.format(sym), end=' ', flush=True)
        df = fetch_binance_klines(sym, '15m', CANDLES_15M)
        if not df.empty:
            candles_15m[sym] = df
            print('{} bars'.format(len(df)), end='   ')
        else:
            print('FAILED', end='   ')
        print('1h...', end=' ', flush=True)
        df1 = fetch_binance_klines(sym, '1h', CANDLES_1H)
        if not df1.empty:
            candles_1h[sym] = df1
            print('{} bars'.format(len(df1)))
        else:
            print('FAILED')
        _time.sleep(0.15)   # be kind to Binance rate limits

    # ── 3. Run backtests ────────────────────────────────────────────────────
    print('\n[3/3] Running walk-forward backtests...')
    results = {}

    for strat in STRATEGIES:
        sname    = strat['name']
        cvd_type = strat['cvd_type']
        sl, tp   = strat['sl'], strat['tp']
        tf       = strat['tf']
        pairs    = MOM_PAIRS if cvd_type == 'ema_momentum' else CVD_PAIRS
        cdict    = candles_1h if tf == '1h' else candles_15m

        print('      {}  ({}, SL={:.0f}% TP={:.0f}%)'.format(
            sname, tf, sl * 100, tp * 100))

        for sym in pairs:
            df = cdict.get(sym)
            if df is None or df.empty:
                results[(sname, sym)] = {'n': 0}
                continue

            trades = backtest_strategy(df, cvd_type, sl, tp)
            stats  = compute_stats(trades, sl, tp)
            results[(sname, sym)] = stats
            results['_trades_' + sname + '_' + sym] = trades

            verdict = '{} trades, {:.0f}% WR, PF={:.2f}, exp={:+.1f}%'.format(
                stats['n'], stats['wr'], stats['pf'], stats['exp'])
            print('        {:6} → {}'.format(sym, verdict))

    print_backtest_table(results)
    print_summary_verdict(results)


if __name__ == '__main__':
    asyncio.run(main())

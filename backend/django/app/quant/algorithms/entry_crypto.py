"""
entry_crypto.py — Multi-timeframe Crypto Entry (Lighter.xyz DEX)

Timeframes:
  H4  — trend bias   (ADX + MACD direction)
  H1  — structure    (market structure: HH/HL or LH/LL)
  H1  — CVD signal   (Lack of Participants or Absorption)

Real-time OB filter (BTC/ETH/SOL only, via ws_streamer):
  If DOM is strongly one-sided against direction → skip entry.
  Thresholds: imbalance < 0.35 blocks buys, > 0.65 blocks sells.

Entry fires when:
  H4 trend confirmed (ADX > 20, MACD direction)
  AND (H1 structure agrees OR CVD setup fires)
  AND OB not strongly against

Execution: Lighter.xyz signer proxy (macOS port 5555)
Sizing:    30% of account balance per trade

PAUSED by default — enable when account is funded.
"""

from __future__ import annotations

import json
import logging
import os

from django.core.cache import cache

from app.quant.algorithms.lighter.client import (
    get_candles,
    get_best_bid_ask,
    get_account_info,
    place_market_order_usd,
    place_oco_sltp,
)
from app.quant.algorithms.lighter.config import LIGHTER_MARKETS
from app.quant.engine import indicators as ind
from app.quant.engine.bar_builder import Bar

logger = logging.getLogger('lighter')

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS           = ['BTC', 'ETH', 'SOL', 'AVAX', 'XAG']

SL_ATR_MULT       = 1.5
TP_ATR_MULT       = 3.0

POSITION_SIZE_PCT = 0.30
MIN_TRADE_USD     = 10.0

MAX_OPEN          = 3
COOLDOWN_TTL      = 600

ADX_MIN           = 20

_CB_KEY           = 'crypto_entry:circuit_breaker'
_LOSS_KEY         = 'crypto_entry:consecutive_losses'
_CB_LOSSES        = 4
_CB_TTL           = 3600

# Symbols tracked by ws_streamer (those with real-time OB data in Redis)
_WS_SYMBOLS       = frozenset(['BTC', 'ETH', 'SOL', 'XAU'])

# OB imbalance block thresholds — only block at extremes
OB_BLOCK_BUY      = 0.35   # block buy if DOM shows strong ask pressure
OB_BLOCK_SELL     = 0.65   # block sell if DOM shows strong bid pressure

_REDIS_DB2_URL    = os.getenv('TICK_REDIS_URL', 'redis://redis:6379/2')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def entry_crypto_algorithm():
    """Multi-timeframe crypto scan: H4 trend + H1 structure/CVD + OB filter."""
    if cache.get('crypto_bot_paused') or cache.get('lighter:disabled'):
        return

    if _circuit_broken():
        return

    if _count_open() >= MAX_OPEN:
        return

    balance = _get_balance()
    if not balance or balance < MIN_TRADE_USD:
        logger.warning('[entry_crypto] Balance too low: $%s', balance)
        return

    trade_usd = max(MIN_TRADE_USD, balance * POSITION_SIZE_PCT)

    for symbol in SYMBOLS:
        if cache.get(f'crypto_cooldown:{symbol}'):
            continue
        if cache.get(f'crypto_open:{symbol}'):
            continue

        # Fetch two timeframes from Lighter
        h4_candles = _fetch(symbol, '4h', 60)
        h1_candles = _fetch(symbol, '1h', 60)

        if not h4_candles or len(h4_candles) < 35:
            continue
        if not h1_candles or len(h1_candles) < 20:
            continue

        h4_bars = _to_bars(h4_candles)
        h1_bars = _to_bars(h1_candles)

        # ── H4 trend bias (required) ──────────────────────────────────
        h4_adx  = ind.adx(h4_bars)
        h4_macd = ind.macd(h4_bars)
        h4_rsi  = ind.rsi(h4_bars)

        if not h4_adx or h4_adx < ADX_MIN:
            continue
        if not h4_macd or h4_rsi is None:
            continue

        macd_line, sig_line = h4_macd
        h4_bull = macd_line > sig_line and h4_rsi < 65
        h4_bear = macd_line < sig_line and h4_rsi > 35

        if not h4_bull and not h4_bear:
            continue

        direction = 'buy' if h4_bull else 'sell'

        atr_val = ind.atr(h1_bars) or ind.atr(h4_bars)
        if not atr_val:
            continue

        # ── H1: structure agrees OR CVD setup fires ───────────────────
        structure = ind.market_structure(h1_bars)
        struct_ok = (direction == 'buy'  and structure == 'bullish') or \
                    (direction == 'sell' and structure == 'bearish')

        cvd_signal = _cvd_setup(h1_candles, direction)

        if not struct_ok and not cvd_signal:
            continue

        # ── Real-time OB filter (BTC/ETH/SOL only) ───────────────────
        imbalance, trade_cvd = _read_realtime_data(symbol)

        if imbalance is not None:
            if direction == 'buy' and imbalance < OB_BLOCK_BUY:
                logger.debug(
                    '[entry_crypto] %s BUY skipped — DOM sell pressure (imbalance=%.2f)',
                    symbol, imbalance,
                )
                continue
            if direction == 'sell' and imbalance > OB_BLOCK_SELL:
                logger.debug(
                    '[entry_crypto] %s SELL skipped — DOM buy pressure (imbalance=%.2f)',
                    symbol, imbalance,
                )
                continue

        reason = []
        if struct_ok:   reason.append('structure')
        if cvd_signal:  reason.append(cvd_signal)

        ob_str  = f'{imbalance:.2f}' if imbalance  is not None else 'n/a'
        cvd_str = f'{trade_cvd:+.0f}' if trade_cvd is not None else 'n/a'

        logger.info(
            '[entry_crypto] %s %s | adx=%.1f macd=%+.4f h1=%s atr=%.4f ob=%s cvd5m=%s',
            symbol, direction.upper(),
            h4_adx, macd_line - sig_line,
            '+'.join(reason), atr_val, ob_str, cvd_str,
        )
        _execute(symbol, direction, atr_val, trade_usd)


# ---------------------------------------------------------------------------
# Real-time data from ws_streamer (Redis DB2)
# ---------------------------------------------------------------------------

def _read_realtime_data(symbol: str) -> tuple[float | None, float | None]:
    """Return (ob_imbalance, 5min_trade_cvd) from ws_streamer Redis keys.

    Returns (None, None) if the symbol has no WS coverage or data is stale.
    """
    if symbol not in _WS_SYMBOLS:
        return None, None
    try:
        import redis
        r = redis.Redis.from_url(_REDIS_DB2_URL, decode_responses=True, socket_timeout=1)
        ob_raw    = r.get(f'lighter:ob:{symbol}')
        trade_raw = r.get(f'lighter:trades:{symbol}')
        imbalance = float(json.loads(ob_raw)['imbalance']) if ob_raw else None
        trade_cvd = float(json.loads(trade_raw)['cvd'])    if trade_raw else None
        return imbalance, trade_cvd
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# CVD helpers
# ---------------------------------------------------------------------------

def _cvd_setup(candles: list[dict], direction: str) -> str | None:
    """Return CVD setup name if it agrees with direction, else None."""
    cvd = _compute_cvd(candles)
    recent_price = candles[-20:]
    recent_cvd   = cvd[-20:]

    if direction == 'sell':
        # Lack of participants: price HH + CVD LH
        ph1, ph2 = _last_two_highs([c['h'] for c in recent_price])
        ch1, ch2 = _last_two_highs(recent_cvd)
        if all(x is not None for x in [ph1, ph2, ch1, ch2]):
            if recent_price[ph2]['h'] > recent_price[ph1]['h'] and recent_cvd[ch2] < recent_cvd[ch1]:
                return 'lack_of_participants'
        # Absorption: CVD HH + price fails
        ch1, ch2 = _last_two_highs(recent_cvd)
        ph1, ph2 = _last_two_highs([c['h'] for c in recent_price])
        if all(x is not None for x in [ch1, ch2, ph1, ph2]):
            if recent_cvd[ch2] > recent_cvd[ch1] and recent_price[ph2]['h'] <= recent_price[ph1]['h']:
                return 'absorption'

    else:  # buy
        # Lack of participants: price LL + CVD HL
        pl1, pl2 = _last_two_lows([c['l'] for c in recent_price])
        cl1, cl2 = _last_two_lows(recent_cvd)
        if all(x is not None for x in [pl1, pl2, cl1, cl2]):
            if recent_price[pl2]['l'] < recent_price[pl1]['l'] and recent_cvd[cl2] > recent_cvd[cl1]:
                return 'lack_of_participants'
        # Absorption: CVD LL + price holds
        cl1, cl2 = _last_two_lows(recent_cvd)
        pl1, pl2 = _last_two_lows([c['l'] for c in recent_price])
        if all(x is not None for x in [cl1, cl2, pl1, pl2]):
            if recent_cvd[cl2] < recent_cvd[cl1] and recent_price[pl2]['l'] >= recent_price[pl1]['l']:
                return 'absorption'

    return None


def _compute_cvd(candles: list[dict]) -> list[float]:
    running = 0.0
    result  = []
    for c in candles:
        h, l, cl, v = float(c['h']), float(c['l']), float(c['c']), float(c.get('v', 0))
        rng   = h - l
        delta = v * (2 * cl - h - l) / rng if rng > 0 else 0.0
        running += delta
        result.append(running)
    return result


def _last_two_highs(values: list[float]) -> tuple:
    highs = [i for i in range(1, len(values) - 1) if values[i] > values[i-1] and values[i] > values[i+1]]
    return (highs[-2], highs[-1]) if len(highs) >= 2 else (None, None)


def _last_two_lows(values: list[float]) -> tuple:
    lows = [i for i in range(1, len(values) - 1) if values[i] < values[i-1] and values[i] < values[i+1]]
    return (lows[-2], lows[-1]) if len(lows) >= 2 else (None, None)


# ---------------------------------------------------------------------------
# Bar conversion (Lighter candles → Bar objects for indicator functions)
# ---------------------------------------------------------------------------

def _to_bars(candles: list[dict]) -> list[Bar]:
    return [
        Bar(
            ts=int(c.get('t', 0)),
            o=float(c['o']), h=float(c['h']),
            l=float(c['l']), c=float(c['c']),
            v=float(c.get('v', 0)),
        )
        for c in candles
    ]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _execute(symbol: str, direction: str, atr_val: float, trade_usd: float):
    is_buy = direction == 'buy'
    try:
        tick = get_best_bid_ask(symbol)
        if not tick or not tick.get('mid'):
            logger.warning('[entry_crypto] No price for %s', symbol)
            return

        entry_price = (tick['ask'] if is_buy else tick['bid']) or tick['mid']
        sl_price = entry_price - SL_ATR_MULT * atr_val if is_buy else entry_price + SL_ATR_MULT * atr_val
        tp_price = entry_price + TP_ATR_MULT * atr_val if is_buy else entry_price - TP_ATR_MULT * atr_val

        if sl_price <= 0 or tp_price <= 0:
            return

        result = place_market_order_usd(symbol, is_buy, trade_usd)
        if result.get('error'):
            logger.warning('[entry_crypto] Order failed %s: %s', symbol, result['error'])
            return

        meta       = LIGHTER_MARKETS.get(symbol, {})
        base_amount = max(trade_usd / entry_price, meta.get('min_base', 0.001))

        place_oco_sltp(
            symbol=symbol,
            is_long=is_buy,
            base_amount=round(base_amount, meta.get('size_dec', 4)),
            stop_loss_price=round(sl_price, meta.get('price_dec', 2)),
            take_profit_price=round(tp_price, meta.get('price_dec', 2)),
        )

        cache.set(f'crypto_cooldown:{symbol}', True, timeout=COOLDOWN_TTL)
        cache.set(f'crypto_open:{symbol}', True, timeout=86400)
        _reset_losses()

        logger.info(
            '[entry_crypto] ✓ %s %s $%.2f entry=%.4f sl=%.4f tp=%.4f',
            symbol, 'BUY' if is_buy else 'SELL',
            trade_usd, entry_price, sl_price, tp_price,
        )
    except Exception as e:
        logger.error('[entry_crypto] Error %s: %s', symbol, e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch(symbol: str, resolution: str, count: int) -> list[dict] | None:
    try:
        return get_candles(symbol, resolution, count)
    except Exception as e:
        logger.warning('[entry_crypto] Candle fetch failed %s %s: %s', symbol, resolution, e)
        return None


def _get_balance() -> float | None:
    try:
        info = get_account_info()
        if hasattr(info, 'accounts') and info.accounts:
            return float(getattr(info.accounts[0], 'total_collateral', 0) or 0)
        return None
    except Exception as e:
        logger.warning('[entry_crypto] Balance fetch failed: %s', e)
        return None


def _count_open() -> int:
    return sum(1 for s in SYMBOLS if cache.get(f'crypto_open:{s}'))


def _circuit_broken() -> bool:
    if cache.get(_CB_KEY):
        logger.debug('[entry_crypto] Circuit breaker active')
        return True
    return False


def _reset_losses():
    cache.set(_LOSS_KEY, 0, timeout=86400)


def on_trade_closed(won: bool):
    if won:
        cache.set(_LOSS_KEY, 0, timeout=86400)
        return
    losses = (cache.get(_LOSS_KEY) or 0) + 1
    cache.set(_LOSS_KEY, losses, timeout=86400)
    if losses >= _CB_LOSSES:
        cache.set(_CB_KEY, True, timeout=_CB_TTL)
        logger.warning('[entry_crypto] Circuit breaker tripped — %d losses', losses)

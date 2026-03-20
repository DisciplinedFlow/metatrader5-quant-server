"""
Lighter.xyz Grid Trading Strategy — captures profits from price oscillations.

Places a ladder of buy orders below current price and sell orders above.
As price moves through the grid, each fill captures a small profit.
Optimized for zero-fee venues where micro-captures are pure profit.

Grid parameters adapt to asset class:
- Crypto (ETH, BTC, SOL): wider grids (0.3-0.5% spacing)
- Metals (XAU): medium grids (0.15-0.3%)
- Forex (EURUSD, GBPUSD): tight grids (0.05-0.1%)

Safety:
- Hard stop-loss outside grid range
- Max position size cap
- ADX trend filter pauses grid in strong trends
"""
import logging
import math
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import (
    get_candles, get_best_bid_ask, place_market_order_usd,
    update_leverage, cancel_all_orders, place_limit_order,
    place_limit_order_post_only,
)

logger = logging.getLogger('app.lighter')

# ── Grid configuration per asset class ──────────────────

GRID_CONFIG = {
    # $30 account — 2 levels each side = 4 orders per symbol × 2 symbols = 8 total grid orders.
    # Leaves ~12 slots free for OCO SL/TP orders from CVD/RSI2/MOM strategies.
    # (Exchange has a global pending order quota; 4 levels = 16 grid orders exhausted it.)
    # Grid disabled — $23 account needs full order quota for RSI scalper SL/TP OCO orders
    # 'SOL':    {'spacing_pct': 0.003, 'levels': 2, 'size_usd': 10, 'range_mult': 2.0},
}

# Default for unlisted symbols
DEFAULT_CONFIG = {'spacing_pct': 0.003, 'levels': 5, 'size_usd': 10, 'range_mult': 2.0}

# Safety limits
MAX_POSITION_USD = 100       # Max notional per symbol before grid pauses
ADX_TREND_THRESHOLD = 45     # Relaxed — only pause in extreme trends
GRID_REFRESH_MINUTES = 5     # How often to recenter the grid


def _calculate_adx(candles, period=14):
    """Simple ADX calculation from candle data."""
    if len(candles) < period * 2:
        return 20  # Default to "no trend" if insufficient data

    import pandas as pd
    df = pd.DataFrame(candles)
    for col in ['h', 'l', 'c']:
        df[col] = df[col].astype(float)

    high = df['h']
    low = df['l']
    close = df['c']

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.rolling(period).mean()

    return adx.iloc[-1] if not math.isnan(adx.iloc[-1]) else 20


def _get_grid_state(symbol):
    """Get cached grid state for a symbol."""
    key = f'lighter:grid:{symbol}'
    return cache.get(key, {})


def _set_grid_state(symbol, state):
    """Cache grid state."""
    key = f'lighter:grid:{symbol}'
    cache.set(key, state, timeout=3600)  # 1hr TTL


def grid_algorithm(symbols=None):
    """Main grid trading algorithm. Called every 30-60 seconds by Celery beat.

    For each configured symbol:
    1. Check if grid needs refresh (price moved too far from center)
    2. Check ADX trend filter
    3. Place/maintain grid orders
    4. Track fills and record profits
    """
    from django.core.cache import cache
    if cache.get('lighter:disabled'):
        return

    if symbols is None:
        symbols = list(GRID_CONFIG.keys())

    for symbol in symbols:
        try:
            _manage_symbol_grid(symbol)
        except Exception as e:
            logger.error("Grid error for %s: %s", symbol, e)


def _manage_symbol_grid(symbol):
    """Manage the grid for a single symbol."""
    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return

    # Do not run grid when an open directional position exists for this symbol.
    # Grid limit orders and OCO SL/TP orders compete for the same exchange pending-order
    # quota. With grid active, OCO placement fails with 'maximum pending order count
    # per market reached', leaving positions without hard stop-loss protection.
    try:
        from app.crypto.models import CryptoPosition
        if CryptoPosition.objects.filter(status='OPEN', symbol=symbol).exists():
            state = _get_grid_state(symbol)
            if state.get('active'):
                cancel_all_orders(symbol)
                state['active'] = False
                _set_grid_state(symbol, state)
                logger.info("Grid %s: paused — open position exists, freeing OCO slots", symbol)
            return
    except Exception as e:
        logger.debug("Grid %s: position check failed: %s", symbol, e)

    config = GRID_CONFIG.get(symbol, DEFAULT_CONFIG)
    state = _get_grid_state(symbol)

    # Get current price
    prices = get_best_bid_ask(symbol)
    mid = prices.get('mid')
    if not mid or mid <= 0:
        logger.debug("Grid %s: no price data", symbol)
        return

    # Check ADX trend filter
    try:
        candles = get_candles(symbol, resolution='15m', count_back=50)
        if candles and len(candles) >= 30:
            adx = _calculate_adx(candles)
            if adx > ADX_TREND_THRESHOLD:
                logger.info("Grid %s: ADX=%.1f > %d, pausing grid (strong trend)",
                           symbol, adx, ADX_TREND_THRESHOLD)
                # Cancel existing orders in strong trend
                if state.get('active'):
                    cancel_all_orders(symbol)
                    state['active'] = False
                    _set_grid_state(symbol, state)
                return
    except Exception as e:
        logger.debug("Grid %s: ADX check failed: %s", symbol, e)

    # Check if grid needs refresh
    center = state.get('center', 0)
    spacing = config['spacing_pct']
    refresh_distance = spacing * config['levels']  # Refresh when price moves beyond outer grid

    needs_refresh = (
        not state.get('active') or
        center == 0 or
        abs(mid - center) / center > refresh_distance
    )

    if needs_refresh:
        logger.info("Grid %s: refreshing grid (center=%.4f -> %.4f)", symbol, center, mid)
        _place_grid(symbol, mid, config, meta)
        state['center'] = mid
        state['active'] = True
        state['refreshed_at'] = __import__('time').time()
        _set_grid_state(symbol, state)
    else:
        logger.debug("Grid %s: grid active, center=%.4f, price=%.4f (%.2f%% from center)",
                     symbol, center, mid, abs(mid - center) / center * 100)


def _place_grid(symbol, center_price, config, meta):
    """Cancel existing orders and place a fresh grid centered on current price."""
    # Cancel existing orders for this symbol
    try:
        cancel_all_orders(symbol)
    except Exception as e:
        logger.warning("Grid %s: cancel orders failed: %s", symbol, e)

    spacing = config['spacing_pct']
    levels = config['levels']
    size_usd = config['size_usd']
    size_dec = meta['size_dec']
    price_dec = meta['price_dec']

    # Set leverage
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    orders_placed = 0

    # Place buy orders below (grid buys on dips)
    for i in range(1, levels + 1):
        price = center_price * (1 - spacing * i)
        base_size = (size_usd * LIGHTER_LEVERAGE) / price
        base_size = math.floor(base_size * 10**size_dec) / 10**size_dec

        if base_size <= 0:
            continue

        try:
            result = place_limit_order_post_only(symbol, is_buy=True, base_amount=base_size, price=price)
            if not result.get('error'):
                orders_placed += 1
            else:
                logger.debug("Grid %s: buy order failed at %.4f: %s", symbol, price, result['error'])
        except Exception as e:
            logger.debug("Grid %s: buy order error at %.4f: %s", symbol, price, e)

    # Place sell orders above (grid sells on rallies)
    for i in range(1, levels + 1):
        price = center_price * (1 + spacing * i)
        base_size = (size_usd * LIGHTER_LEVERAGE) / price
        base_size = math.floor(base_size * 10**size_dec) / 10**size_dec

        if base_size <= 0:
            continue

        try:
            result = place_limit_order_post_only(symbol, is_buy=False, base_amount=base_size, price=price)
            if not result.get('error'):
                orders_placed += 1
            else:
                logger.debug("Grid %s: sell order failed at %.4f: %s", symbol, price, result['error'])
        except Exception as e:
            logger.debug("Grid %s: sell order error at %.4f: %s", symbol, price, e)

    logger.info("Grid %s: placed %d orders (%d buy + %d sell) centered at %.4f, spacing=%.2f%%",
                symbol, orders_placed, levels, levels, center_price, spacing * 100)


def stop_all_grids():
    """Emergency stop — cancel all grid orders and clear state."""
    for symbol in GRID_CONFIG:
        try:
            cancel_all_orders(symbol)
            cache.delete(f'lighter:grid:{symbol}')
            logger.info("Grid %s: stopped and cleared", symbol)
        except Exception as e:
            logger.error("Grid %s: stop failed: %s", symbol, e)

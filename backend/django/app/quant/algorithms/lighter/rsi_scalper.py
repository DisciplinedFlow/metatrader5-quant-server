"""
Lighter.xyz RSI(2) Ultra-Fast Scalper — highest documented win rate strategy.

Based on Larry Connors' RSI(2) mean reversion (91% WR on stocks).
Adapted for 5-minute crypto scalping on zero-fee venue.

Rules:
- RSI(2) < 15 → BUY (deeply oversold on ultra-fast RSI)
- RSI(2) > 85 → SELL (deeply overbought)
- EMA(50) trend filter: only longs above EMA, only shorts below
- TP: 0.3-0.5% (mean reversion target)
- SL: 0.5-1.0% (tight, cut losses fast)
- Cooldown: 30 seconds per symbol (zero fees = trade often)
- Max 3 positions at a time

Asset-class aware SL/TP:
- Crypto: SL 1.0%, TP 0.5%
- Metals: SL 0.8%, TP 0.4%
- Forex: SL 0.3%, TP 0.15%

Targets 20-50 trades/day. Each trade captures 0.2-0.5%.
"""
import logging
import pandas as pd
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage, place_oco_sltp

logger = logging.getLogger('app.lighter')

PLATFORM_PREFIX = 'lighter:'

# ── Asset-class classification ────────────────────────────

FOREX_SYMBOLS = {'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD'}
METALS_SYMBOLS = {'XAU', 'XAG', 'PAXG', 'WTI'}

# ── RSI(2) scalper configs per asset class ────────────────

RSI2_CONFIG = {
    'crypto': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.010,   # 1.0% SL
        'tp_pct': 0.005,   # 0.5% TP
        'size_usd': 8,
    },
    'metals': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.008,   # 0.8% SL
        'tp_pct': 0.004,   # 0.4% TP
        'size_usd': 8,
    },
    'forex': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.003,   # 0.3% SL
        'tp_pct': 0.0015,  # 0.15% TP
        'size_usd': 8,
    },
}

# Symbols to scan every 10 seconds
RSI2_SYMBOLS = ['ETH', 'BTC', 'SOL', 'XAU', 'EURUSD', 'GBPUSD']

# Cooldown between trades on same symbol (seconds)
RSI2_COOLDOWN_SECONDS = 30  # Ultra-aggressive — zero fees make rapid trades viable

# Max simultaneous RSI2 positions
RSI2_MAX_POSITIONS = 3


def _get_config(symbol):
    """Get asset-class config for a symbol."""
    if symbol in FOREX_SYMBOLS:
        return RSI2_CONFIG['forex']
    elif symbol in METALS_SYMBOLS:
        return RSI2_CONFIG['metals']
    return RSI2_CONFIG['crypto']


def _calculate_rsi(closes, period=2):
    """Calculate RSI with configurable period. Uses SMA smoothing for RSI(2)."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calculate_ema(closes, period=50):
    """Calculate EMA for trend filter."""
    return closes.ewm(span=period, adjust=False).mean()


def _check_cooldown(symbol):
    """Check if symbol is in post-trade cooldown."""
    key = f'lighter:rsi2_cooldown:{symbol}'
    return not cache.get(key)


def _set_cooldown(symbol):
    """Set post-trade cooldown for symbol."""
    key = f'lighter:rsi2_cooldown:{symbol}'
    cache.set(key, True, timeout=RSI2_COOLDOWN_SECONDS)


def rsi_scalper_algorithm(symbols=None):
    """RSI(2) ultra-fast scalper entry algorithm. Called every 10s by Celery.

    For each symbol:
    1. Fetch 5m candles (60 bars for EMA(50) calculation)
    2. Calculate RSI(2) — ultra-fast 2-period RSI
    3. Calculate EMA(50) — trend filter
    4. BUY: RSI(2) < 15 AND price > EMA(50) — oversold in uptrend
    5. SELL: RSI(2) > 85 AND price < EMA(50) — overbought in downtrend
    """
    if cache.get('lighter:disabled'):
        return

    # Circuit breaker check
    if cache.get('lighter:circuit_breaker'):
        logger.debug("RSI2: circuit breaker active, skipping")
        return

    if symbols is None:
        symbols = RSI2_SYMBOLS

    from app.crypto.models import CryptoPosition

    # Count open RSI2 positions
    rsi2_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=f'{PLATFORM_PREFIX}rsi2_',
    ).count()

    if rsi2_open >= RSI2_MAX_POSITIONS:
        logger.debug("RSI2: max positions reached (%d/%d)", rsi2_open, RSI2_MAX_POSITIONS)
        return

    for symbol in symbols:
        try:
            # Re-check position count inside loop — may have opened one this iteration
            if rsi2_open >= RSI2_MAX_POSITIONS:
                break
            opened = _scan_symbol(symbol)
            if opened:
                rsi2_open += 1
        except Exception as e:
            logger.error("RSI2 error for %s: %s", symbol, e)


def _scan_symbol(symbol):
    """Scan a single symbol for RSI(2) scalp entry. Returns True if position opened."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return False

    # Check if already in position on this symbol (any lighter strategy)
    if CryptoPosition.objects.filter(symbol=symbol, status='OPEN',
                                      entry_signal__startswith=PLATFORM_PREFIX).exists():
        return False

    # Check cooldown
    if not _check_cooldown(symbol):
        return False

    config = _get_config(symbol)

    # Fetch 5m candles — need 60 bars for EMA(50) + buffer
    candles = get_candles(symbol, resolution='5m', count_back=60)
    if not candles or len(candles) < config['ema_period'] + 5:
        return False

    df = pd.DataFrame(candles)
    for col in ['o', 'h', 'l', 'c']:
        df[col] = df[col].astype(float)

    closes = df['c']

    # Calculate indicators
    rsi = _calculate_rsi(closes, config['rsi_period'])
    ema = _calculate_ema(closes, config['ema_period'])

    # Get latest values
    current_price = closes.iloc[-1]
    current_rsi = rsi.iloc[-1]
    current_ema = ema.iloc[-1]

    if pd.isna(current_rsi) or pd.isna(current_ema):
        return False

    # ── Entry logic ──
    # BUY: RSI(2) deeply oversold AND price above EMA(50) — dip in uptrend
    # SELL: RSI(2) deeply overbought AND price below EMA(50) — pop in downtrend
    signal = 0
    trend = 'up' if current_price > current_ema else 'down'

    if current_rsi < config['rsi_oversold'] and current_price > current_ema:
        signal = 1  # BUY
    elif current_rsi > config['rsi_overbought'] and current_price < current_ema:
        signal = -1  # SELL
    else:
        return False

    # ── Execute entry ──
    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    position_usd = config['size_usd'] * LIGHTER_LEVERAGE

    # Get live price
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return False

    signal_type = f"rsi2_{'buy' if is_buy else 'sell'}_rsi{current_rsi:.0f}_ema{trend}"

    logger.info("RSI2 ENTRY: %s %s $%.2f (price=%.4f, RSI(2)=%.1f, EMA50=%.4f, trend=%s)",
                symbol, side, position_usd, live_price, current_rsi, current_ema, trend)

    # Set leverage
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # Place order
    result = place_market_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("RSI2 %s: order failed: %s", symbol, result['error'])
        return False

    # Calculate SL/TP
    if is_buy:
        take_profit = live_price * (1 + config['tp_pct'])
        stop_loss = live_price * (1 - config['sl_pct'])
    else:
        take_profit = live_price * (1 - config['tp_pct'])
        stop_loss = live_price * (1 + config['sl_pct'])

    # Record position
    base_size = position_usd / live_price
    position = CryptoPosition.objects.create(
        symbol=symbol,
        side=side,
        entry_price=live_price,
        size=base_size,
        leverage=LIGHTER_LEVERAGE,
        entry_signal=f"{PLATFORM_PREFIX}{signal_type}",
        stop_loss=stop_loss,
        take_profit=take_profit,
        status='OPEN',
        venue='LIGHTER',
    )

    CryptoTrade.objects.create(
        position=position,
        order_id=result.get('tx_hash', ''),
        side='BUY' if is_buy else 'SELL',
        price=live_price,
        size=base_size,
        fee=0.0,
        status='FILLED',
    )

    # Place native on-chain SL/TP as OCO group (one-cancels-other)
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("RSI2 OCO SL/TP failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("RSI2 OCO SL/TP placed: %s SL=%.4f TP=%.4f tx=%s",
                        symbol, stop_loss, take_profit, oco_result.get('tx_hash', '?'))
    except Exception as e:
        logger.warning("RSI2 OCO SL/TP exception for %s: %s", symbol, e)

    _set_cooldown(symbol)

    logger.info("RSI2 position opened: %s %s size=%.6f TP=%.4f SL=%.4f signal=%s",
                symbol, side, base_size, take_profit, stop_loss, signal_type)
    return True

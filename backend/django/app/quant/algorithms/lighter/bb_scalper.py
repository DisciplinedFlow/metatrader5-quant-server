"""
Lighter.xyz Bollinger Band Mean Reversion Scalper — WTI oil specialist.

WTI crude oil trades in ranges between supply/demand shocks.
Bollinger Bands catch the extremes where price snaps back.

Rules:
- Price touches lower band → BUY (oversold, expect reversion to mean)
- Price touches upper band → SELL (overbought, expect reversion to mean)
- BB(20, 2.0σ) on 15m candles
- SL: 1.5% — room for oil's wider swings
- TP: 2.0% — capture the mean reversion move
- Cooldown: 600s between entries per symbol

Backtest: 13T 9W 69.2% WR, PF 2.81, +11.3% total (with fees)
"""
import logging
import pandas as pd
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE, PLATFORM_PREFIX
from .client import get_candles, get_best_bid_ask, place_maker_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd

logger = logging.getLogger('app.lighter')

# ── Configuration ─────────────────────────────────────────

BB_SYMBOLS = ['WTI']

BB_CONFIG = {
    'bb_period': 20,
    'bb_std': 2.0,
    'sl_pct': 0.015,       # 1.5% SL
    'tp_pct': 0.020,       # 2.0% TP
    'cooldown_seconds': 600,
}

BB_MAX_POSITIONS = 1


# ── Indicators ────────────────────────────────────────────

def _calculate_bb(closes, period=20, std=2.0):
    """Calculate Bollinger Bands."""
    sma = closes.rolling(period).mean()
    std_dev = closes.rolling(period).std()
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    return upper, sma, lower


# ── Entry Algorithm ───────────────────────────────────────

def bb_scalper_algorithm(symbols=None):
    """BB mean reversion entry. Called every 30s by Celery."""
    if cache.get('lighter:disabled'):
        return

    if symbols is None:
        symbols = BB_SYMBOLS

    from app.crypto.models import CryptoPosition

    bb_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=f'{PLATFORM_PREFIX}bb_',
    ).count()

    if bb_open >= BB_MAX_POSITIONS:
        return

    from .config import is_global_position_limit_reached
    if is_global_position_limit_reached():
        return

    for symbol in symbols:
        try:
            if bb_open >= BB_MAX_POSITIONS:
                break
            opened = _scan_symbol(symbol)
            if opened:
                bb_open += 1
        except Exception as e:
            logger.error("BB error for %s: %s", symbol, e)


def _scan_symbol(symbol):
    """Scan a single symbol for BB mean reversion entry."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return False

    # Cooldown
    cooldown_key = f'lighter:bb_cooldown:{symbol}'
    if cache.get(cooldown_key):
        return False

    # Vanish cooldown
    if cache.get(f'lighter:vanish_cooldown:{symbol}'):
        return False

    cfg = BB_CONFIG

    # Fetch 15m candles (40 bars = 10h, enough for BB(20) + buffer)
    candles = get_candles(symbol, resolution='15m', count_back=40)
    if not candles or len(candles) < cfg['bb_period'] + 5:
        return False

    df = pd.DataFrame(candles)
    for col in ['o', 'h', 'l', 'c']:
        df[col] = df[col].astype(float)

    closes = df['c']
    upper, sma, lower = _calculate_bb(closes, cfg['bb_period'], cfg['bb_std'])

    current_price = closes.iloc[-1]
    curr_upper = upper.iloc[-1]
    curr_lower = lower.iloc[-1]
    curr_sma = sma.iloc[-1]

    if pd.isna(curr_upper) or pd.isna(curr_lower):
        return False

    # ── Entry logic ──
    # Price at or below lower band → BUY (oversold)
    # Price at or above upper band → SELL (overbought)
    signal = 0
    if current_price <= curr_lower:
        signal = 1  # BUY
    elif current_price >= curr_upper:
        signal = -1  # SELL
    else:
        return False

    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    signal_type = f"bb_{'buy' if is_buy else 'sell'}_bb{cfg['bb_std']}"

    # Get live price
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return False

    position_usd = calculate_position_usd(symbol, cfg['sl_pct'])

    # Calculate SL/TP
    if is_buy:
        stop_loss = live_price * (1 - cfg['sl_pct'])
        take_profit = live_price * (1 + cfg['tp_pct'])
    else:
        stop_loss = live_price * (1 + cfg['sl_pct'])
        take_profit = live_price * (1 - cfg['tp_pct'])

    logger.info(
        "BB ENTRY: %s %s $%.2f (price=%.4f, upper=%.4f, lower=%.4f, sma=%.4f)",
        symbol, side, position_usd, live_price, curr_upper, curr_lower, curr_sma,
    )

    # Set leverage
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # Guard: re-check DB right before order (prevents ghost orders on duplicate key)
    from app.crypto.models import CryptoPosition
    if CryptoPosition.objects.filter(symbol=symbol, venue='LIGHTER', status='OPEN').exists():
        return False

    result = place_maker_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("BB %s: order failed: %s", symbol, result['error'])
        return False

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
        fee=0.0,  # maker order = zero fee
        status='FILLED',
    )

    # Place on-chain SL/TP
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("BB OCO failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("BB OCO placed: %s SL=%.4f TP=%.4f", symbol, stop_loss, take_profit)
    except Exception as e:
        logger.warning("BB OCO exception for %s: %s", symbol, e)

    cache.set(cooldown_key, True, timeout=cfg['cooldown_seconds'])

    logger.info("BB position opened: %s %s size=%.6f TP=%.4f SL=%.4f",
                symbol, side, base_size, take_profit, stop_loss)
    return True

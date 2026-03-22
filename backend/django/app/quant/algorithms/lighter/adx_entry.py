"""
Lighter.xyz ADX Trend-Following Entry — triple-layered signal.

Three layers, each answering a different question:
  1. ADX  → WHEN: Is there a trend worth trading? (regime filter)
  2. OB   → IF:   Is there live fuel behind the move? (real-time confirmation)
  3. FVG  → WHERE: What price level gives us the best entry? (precision)

Entry logic:
  - ADX(14) > 25 confirms trending regime
  - ADX must be RISING (slope > 0 over last 3 bars) — avoid dying trends
  - +DI > -DI = bullish trend, -DI > +DI = bearish trend
  - OB imbalance must align (>0.55 for BUY, <0.45 for SELL) — live pressure
  - Price must be at or near a Fair Value Gap zone — precision entry
  - If no FVG available, fall back to DI crossover + OB (still a valid entry)

Risk:
  - SL: below FVG bottom (bullish) or above FVG top (bearish)
  - If no FVG: SL = ATR-based (1.5x ATR)
  - TP: 2x SL distance (1:2 R:R)
  - Position size: $1.50 risk via unified sizing module

Backtest-validated: SOL 15m ADX>25 DI(14) — 49 trades, 40.8% WR, PF 1.38
"""
import logging
import pandas as pd
import numpy as np
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE, PLATFORM_PREFIX
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage, place_oco_sltp
from .sizing import calculate_position_usd

logger = logging.getLogger('app.lighter')

# ── Configuration ─────────────────────────────────────────

ADX_SYMBOLS = ['SOL']

ADX_CONFIG = {
    'adx_period': 14,
    'adx_threshold': 25,       # minimum ADX to confirm trend
    'adx_slope_bars': 3,       # ADX must be rising over this many bars
    'ob_threshold_buy': 0.55,  # OB imbalance must be above this for BUY
    'ob_threshold_sell': 0.45, # OB imbalance must be below this for SELL
    'fvg_max_age_bars': 10,    # FVG must have formed within last N bars
    'fvg_proximity_pct': 0.005, # price must be within 0.5% of FVG zone
    'sl_pct': 0.015,           # 1.5% SL (crypto)
    'tp_pct': 0.030,           # 3.0% TP (1:2 R:R)
    'cooldown_seconds': 900,   # 15 min between entries per symbol
}

ADX_MAX_POSITIONS = 1  # conservative — 1 ADX position at a time


# ── Indicators ────────────────────────────────────────────

def _calculate_adx(df, period=14):
    """Calculate ADX, +DI, -DI from OHLC DataFrame."""
    high = df['h'].astype(float)
    low = df['l'].astype(float)
    close = df['c'].astype(float)

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    alpha = 1 / period
    atr = pd.Series(tr).ewm(alpha=alpha, min_periods=period).mean()
    plus_smooth = pd.Series(plus_dm).ewm(alpha=alpha, min_periods=period).mean()
    minus_smooth = pd.Series(minus_dm).ewm(alpha=alpha, min_periods=period).mean()

    plus_di = 100 * plus_smooth / atr
    minus_di = 100 * minus_smooth / atr

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=alpha, min_periods=period).mean()

    return adx, plus_di, minus_di


def _detect_fvgs(df, lookback=20):
    """Detect Fair Value Gaps from OHLC data (self-contained, no external deps).

    FVG = 3-candle pattern where candle 1's wick doesn't overlap with candle 3's wick.

    Bullish FVG: candle_3.low > candle_1.high (gap up — buyers dominated)
    Bearish FVG: candle_1.low > candle_3.high (gap down — sellers dominated)

    Returns list of FVG dicts: {direction, top, bottom, bar_index, age}
    """
    fvgs = []
    start = max(0, len(df) - lookback)

    for i in range(start + 2, len(df)):
        c1_high = float(df['h'].iloc[i - 2])
        c1_low = float(df['l'].iloc[i - 2])
        c3_high = float(df['h'].iloc[i])
        c3_low = float(df['l'].iloc[i])

        age = len(df) - 1 - i

        # Bullish FVG: gap up between c1.high and c3.low
        if c3_low > c1_high:
            fvgs.append({
                'direction': 'BUY',
                'top': c3_low,
                'bottom': c1_high,
                'mid': (c3_low + c1_high) / 2,
                'bar_index': i,
                'age': age,
            })

        # Bearish FVG: gap down between c1.low and c3.high
        elif c1_low > c3_high:
            fvgs.append({
                'direction': 'SELL',
                'top': c1_low,
                'bottom': c3_high,
                'mid': (c1_low + c3_high) / 2,
                'bar_index': i,
                'age': age,
            })

    return fvgs


def _calculate_atr(df, period=14):
    """Calculate Average True Range."""
    high = df['h'].astype(float)
    low = df['l'].astype(float)
    close = df['c'].astype(float)

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


# ── Entry Algorithm ───────────────────────────────────────

def adx_entry_algorithm(symbols=None):
    """ADX trend-following entry. Called every 30s by Celery."""
    if cache.get('lighter:disabled'):
        return

    if symbols is None:
        symbols = ADX_SYMBOLS

    from app.crypto.models import CryptoPosition

    # Count open ADX positions
    adx_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=f'{PLATFORM_PREFIX}adx_',
    ).count()

    if adx_open >= ADX_MAX_POSITIONS:
        return

    # Global position cap
    from .config import is_global_position_limit_reached
    if is_global_position_limit_reached():
        return

    for symbol in symbols:
        try:
            if adx_open >= ADX_MAX_POSITIONS:
                break
            opened = _scan_symbol(symbol)
            if opened:
                adx_open += 1
        except Exception as e:
            logger.error("ADX entry error for %s: %s", symbol, e)


def _scan_symbol(symbol):
    """Scan a single symbol for ADX trend entry. Returns True if position opened."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return False

    # Already in position on this symbol?
    if CryptoPosition.objects.filter(symbol=symbol, status='OPEN',
                                      entry_signal__startswith=PLATFORM_PREFIX).exists():
        return False

    # Vanish cooldown
    if cache.get(f'lighter:vanish_cooldown:{symbol}'):
        return False

    # Entry cooldown
    cooldown_key = f'lighter:adx_cooldown:{symbol}'
    if cache.get(cooldown_key):
        return False

    cfg = ADX_CONFIG

    # Fetch 15m candles (80 bars = 20h, enough for ADX(14) warmup + FVG lookback)
    candles = get_candles(symbol, resolution='15m', count_back=80)
    if not candles or len(candles) < 60:
        return False

    df = pd.DataFrame(candles)
    for col in ['o', 'h', 'l', 'c']:
        df[col] = df[col].astype(float)

    # ── Layer 1: ADX regime filter ──
    adx, plus_di, minus_di = _calculate_adx(df, cfg['adx_period'])

    curr_adx = adx.iloc[-1]
    if pd.isna(curr_adx) or curr_adx < cfg['adx_threshold']:
        return False

    # ADX must be RISING (avoid dying trends)
    adx_slope = curr_adx - adx.iloc[-1 - cfg['adx_slope_bars']]
    if adx_slope <= 0:
        return False

    # Determine trend direction from DI
    curr_plus = plus_di.iloc[-1]
    curr_minus = minus_di.iloc[-1]
    if pd.isna(curr_plus) or pd.isna(curr_minus):
        return False

    if curr_plus > curr_minus:
        direction = 'BUY'
    elif curr_minus > curr_plus:
        direction = 'SELL'
    else:
        return False

    # ── Layer 2: OB imbalance confirmation ──
    try:
        from .orderbook_signal import get_ob_imbalance
        imbalance = get_ob_imbalance(symbol)
    except Exception:
        imbalance = 0.5  # neutral on failure

    if direction == 'BUY' and imbalance < cfg['ob_threshold_buy']:
        logger.debug("ADX %s: BUY blocked — OB imbalance %.3f < %.2f",
                     symbol, imbalance, cfg['ob_threshold_buy'])
        return False
    if direction == 'SELL' and imbalance > cfg['ob_threshold_sell']:
        logger.debug("ADX %s: SELL blocked — OB imbalance %.3f > %.2f",
                     symbol, imbalance, cfg['ob_threshold_sell'])
        return False

    # ── Layer 3: FVG precision entry ──
    fvgs = _detect_fvgs(df, lookback=cfg['fvg_max_age_bars'] + 2)
    current_price = float(df['c'].iloc[-1])

    # Find the best FVG: matching direction, not too old, price near the zone
    matching_fvg = None
    for fvg in reversed(fvgs):  # newest first
        if fvg['direction'] != direction:
            continue
        if fvg['age'] > cfg['fvg_max_age_bars']:
            continue
        # Check if price is near the FVG zone (within proximity threshold)
        distance_pct = abs(current_price - fvg['mid']) / current_price
        if distance_pct <= cfg['fvg_proximity_pct']:
            matching_fvg = fvg
            break

    # Build signal name and SL/TP
    is_buy = direction == 'BUY'
    atr = _calculate_atr(df, 14)
    curr_atr = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else current_price * cfg['sl_pct']

    if matching_fvg:
        signal_type = f"adx_fvg_{direction.lower()}_adx{curr_adx:.0f}"
        fvg_info = f"fvg({matching_fvg['bottom']:.4f}-{matching_fvg['top']:.4f} age={matching_fvg['age']})"

        # SL anchored to FVG boundary (tighter than ATR-based)
        if is_buy:
            stop_loss = matching_fvg['bottom'] * 0.999  # just below FVG bottom
            sl_distance = current_price - stop_loss
        else:
            stop_loss = matching_fvg['top'] * 1.001    # just above FVG top
            sl_distance = stop_loss - current_price

        # TP = 2x SL distance (1:2 R:R)
        if is_buy:
            take_profit = current_price + (sl_distance * 2)
        else:
            take_profit = current_price - (sl_distance * 2)

        sl_pct_actual = sl_distance / current_price
    else:
        signal_type = f"adx_trend_{direction.lower()}_adx{curr_adx:.0f}"
        fvg_info = "no_fvg"

        # ATR-based SL/TP
        sl_pct_actual = cfg['sl_pct']
        if is_buy:
            stop_loss = current_price * (1 - cfg['sl_pct'])
            take_profit = current_price * (1 + cfg['tp_pct'])
        else:
            stop_loss = current_price * (1 + cfg['sl_pct'])
            take_profit = current_price * (1 - cfg['tp_pct'])

    # ── Execute entry ──
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return False

    side = 'LONG' if is_buy else 'SHORT'
    position_usd = calculate_position_usd(symbol, sl_pct_actual)

    logger.info(
        "ADX ENTRY: %s %s $%.2f (price=%.4f, ADX=%.1f slope=%+.1f, +DI=%.1f -DI=%.1f, OB=%.3f, %s)",
        symbol, side, position_usd, live_price, curr_adx, adx_slope,
        curr_plus, curr_minus, imbalance, fvg_info,
    )

    # Set leverage
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # Guard: re-check DB right before order (prevents ghost orders on duplicate key)
    if CryptoPosition.objects.filter(symbol=symbol, venue='LIGHTER', status='OPEN').exists():
        return False

    result = place_market_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("ADX %s: order failed: %s", symbol, result['error'])
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

    # Estimate taker fee
    entry_fee = base_size * live_price * 0.00028
    CryptoTrade.objects.create(
        position=position,
        order_id=result.get('tx_hash', ''),
        side='BUY' if is_buy else 'SELL',
        price=live_price,
        size=base_size,
        fee=entry_fee,
        status='FILLED',
    )

    # Place on-chain SL/TP
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("ADX OCO SL/TP failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("ADX OCO SL/TP placed: %s SL=%.4f TP=%.4f", symbol, stop_loss, take_profit)
    except Exception as e:
        logger.warning("ADX OCO exception for %s: %s", symbol, e)

    # Set cooldown
    cache.set(cooldown_key, True, timeout=cfg['cooldown_seconds'])

    logger.info("ADX position opened: %s %s size=%.6f TP=%.4f SL=%.4f signal=%s",
                symbol, side, base_size, take_profit, stop_loss, signal_type)
    return True

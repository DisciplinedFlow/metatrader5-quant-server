"""
Lighter.xyz entry algorithm — multi-timeframe momentum with adaptive sizing.

Signal generation uses two timeframes for confirmation:
- 1h EMA crossover provides trend direction
- 15m RSI provides entry timing (pullback in trend direction)

Additional signal mode: Trend-following pullback
- EMAs aligned (fast > slow for bullish) on 1h
- 15m RSI pulls back to oversold zone → enter with the trend

Symbol performance filter prevents trading symbols with poor recent results.
"""
import logging
import pandas as pd
import numpy as np

from .config import (
    LIGHTER_PAIRS, LIGHTER_CAPITAL_USD, LIGHTER_MAX_POSITIONS,
    LIGHTER_LEVERAGE, LIGHTER_POSITION_SIZE_PCT, LIGHTER_MARKETS,
)
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage

logger = logging.getLogger('app.lighter')

PLATFORM_PREFIX = 'lighter:'
EMA_FAST = 8
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 65
RSI_PULLBACK_BUY = 40    # For trend-following: buy when RSI dips below this in uptrend
RSI_PULLBACK_SELL = 60   # For trend-following: sell when RSI rises above this in downtrend
CANDLE_COUNT = 100

# Symbol performance filter thresholds
SYMBOL_FILTER_LOOKBACK = 10
SYMBOL_FILTER_MIN_WR = 0.30


def _calculate_ema(prices: pd.Series, span: int) -> pd.Series:
    return prices.ewm(span=span, adjust=False).mean()


def _calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _generate_signal_multitf(candles_1h: list, candles_15m: list) -> tuple:
    """Multi-timeframe signal generation.

    Returns (signal: int, signal_type: str) where signal is 1/-1/0
    and signal_type describes the trigger for logging.
    """
    if len(candles_1h) < EMA_SLOW + 5:
        return 0, ''

    closes_1h = pd.Series([float(c['c']) for c in candles_1h])
    ema_fast_1h = _calculate_ema(closes_1h, EMA_FAST)
    ema_slow_1h = _calculate_ema(closes_1h, EMA_SLOW)
    rsi_1h = _calculate_rsi(closes_1h, RSI_PERIOD)

    if pd.isna(ema_fast_1h.iloc[-1]) or pd.isna(ema_slow_1h.iloc[-1]) or pd.isna(rsi_1h.iloc[-1]):
        return 0, ''

    # 1h trend state
    ema_cross_up = ema_fast_1h.iloc[-1] > ema_slow_1h.iloc[-1] and ema_fast_1h.iloc[-2] <= ema_slow_1h.iloc[-2]
    ema_cross_down = ema_fast_1h.iloc[-1] < ema_slow_1h.iloc[-1] and ema_fast_1h.iloc[-2] >= ema_slow_1h.iloc[-2]
    ema_trending_up = ema_fast_1h.iloc[-1] > ema_slow_1h.iloc[-1]
    ema_trending_down = ema_fast_1h.iloc[-1] < ema_slow_1h.iloc[-1]

    # 15m confirmation (if available)
    has_15m = candles_15m and len(candles_15m) >= RSI_PERIOD + 5
    if has_15m:
        closes_15m = pd.Series([float(c['c']) for c in candles_15m])
        rsi_15m = _calculate_rsi(closes_15m, RSI_PERIOD)
        current_rsi_15m = rsi_15m.iloc[-1] if not pd.isna(rsi_15m.iloc[-1]) else None
    else:
        current_rsi_15m = None

    current_rsi_1h = rsi_1h.iloc[-1]

    # --- Signal Mode 1: EMA Crossover with 15m RSI confirmation ---
    if ema_cross_up and current_rsi_1h < RSI_OVERBOUGHT:
        if current_rsi_15m is not None:
            # 15m RSI should not be overbought (confirms momentum has room)
            if current_rsi_15m < RSI_OVERBOUGHT:
                return 1, 'crossover_confirmed'
            else:
                logger.debug("Lighter: 1h cross up but 15m RSI overbought (%.1f), skipping", current_rsi_15m)
                return 0, ''
        return 1, 'crossover_1h_only'

    if ema_cross_down and current_rsi_1h > RSI_OVERSOLD:
        if current_rsi_15m is not None:
            if current_rsi_15m > RSI_OVERSOLD:
                return -1, 'crossover_confirmed'
            else:
                logger.debug("Lighter: 1h cross down but 15m RSI oversold (%.1f), skipping", current_rsi_15m)
                return 0, ''
        return -1, 'crossover_1h_only'

    # --- Signal Mode 2: Trend-following pullback (new) ---
    # EMAs aligned on 1h + RSI pullback on 15m = enter with the trend
    if ema_trending_up and current_rsi_15m is not None:
        if current_rsi_15m < RSI_PULLBACK_BUY:
            return 1, 'trend_pullback_15m'

    if ema_trending_down and current_rsi_15m is not None:
        if current_rsi_15m > RSI_PULLBACK_SELL:
            return -1, 'trend_pullback_15m'

    # --- Signal Mode 3: Original extreme pullback (1h only, fallback) ---
    if ema_trending_up and current_rsi_1h < RSI_OVERSOLD:
        return 1, 'extreme_pullback_1h'
    if ema_trending_down and current_rsi_1h > RSI_OVERBOUGHT:
        return -1, 'extreme_pullback_1h'

    return 0, ''


def _check_symbol_performance(symbol):
    """Check if a Lighter symbol should be traded based on recent results.

    Returns (allowed: bool, size_multiplier: float).
    """
    try:
        from app.crypto.models import CryptoPosition

        recent = CryptoPosition.objects.filter(
            symbol=symbol,
            status='CLOSED',
            entry_signal__startswith=PLATFORM_PREFIX,
            pnl_usd__isnull=False,
        ).order_by('-closed_at')[:SYMBOL_FILTER_LOOKBACK]

        pnls = [p.pnl_usd for p in recent]
        if len(pnls) < 5:
            return True, 1.0

        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls)
        total_pnl = sum(pnls)

        # Hard block for very poor performance
        if win_rate < SYMBOL_FILTER_MIN_WR and total_pnl < 0:
            logger.info("Lighter: %s blocked by performance filter (WR=%.0f%%, PnL=$%.2f)",
                         symbol, win_rate * 100, total_pnl)
            return False, 0.0

        # Scale sizing
        if win_rate >= 0.60:
            return True, 1.0
        elif win_rate >= 0.45:
            return True, 0.75
        else:
            return True, 0.50

    except Exception as e:
        logger.error("Lighter: symbol performance check failed for %s: %s", symbol, e)
        return True, 1.0


def _get_open_positions():
    """Get all open Lighter positions."""
    from app.crypto.models import CryptoPosition
    return CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=PLATFORM_PREFIX,
    )


def entry_algorithm():
    """Check signals on Lighter markets and enter positions.

    Uses multi-timeframe analysis (1h trend + 15m timing) and
    per-symbol performance filtering for adaptive risk management.
    """
    from app.crypto.models import CryptoPosition, CryptoTrade

    open_positions = _get_open_positions()
    open_count = open_positions.count()
    open_symbols = set(open_positions.values_list('symbol', flat=True))

    if open_count >= LIGHTER_MAX_POSITIONS:
        logger.debug("Lighter: max positions reached (%d/%d)", open_count, LIGHTER_MAX_POSITIONS)
        return

    for symbol in LIGHTER_PAIRS:
        if symbol in open_symbols:
            continue
        if open_count >= LIGHTER_MAX_POSITIONS:
            break

        meta = LIGHTER_MARKETS.get(symbol)
        if meta is None:
            logger.warning("Lighter: unknown symbol %s, skipping", symbol)
            continue

        try:
            # Fetch both timeframes
            candles_1h = get_candles(symbol, resolution='1h', count_back=CANDLE_COUNT)
            if not candles_1h or len(candles_1h) < EMA_SLOW + 5:
                logger.debug("Lighter: not enough 1h data for %s (%d bars)",
                             symbol, len(candles_1h) if candles_1h else 0)
                continue

            # 15m candles for timing confirmation
            candles_15m = None
            try:
                candles_15m = get_candles(symbol, resolution='15m', count_back=CANDLE_COUNT)
            except Exception as e:
                logger.debug("Lighter: 15m candles unavailable for %s: %s", symbol, e)

            signal, signal_type = _generate_signal_multitf(candles_1h, candles_15m)
            if signal == 0:
                logger.debug("Lighter: no signal for %s", symbol)
                continue

            # Symbol performance filter
            sym_ok, sym_mult = _check_symbol_performance(symbol)
            if not sym_ok:
                continue

            # Get current price
            prices = get_best_bid_ask(symbol)
            current_price = prices.get('mid')
            if not current_price or current_price <= 0:
                logger.warning("Lighter: no price data for %s", symbol)
                continue

            # Calculate position size in USD (with performance-based scaling)
            position_usd = LIGHTER_CAPITAL_USD * LIGHTER_POSITION_SIZE_PCT * LIGHTER_LEVERAGE * sym_mult
            if position_usd < meta['min_quote']:
                logger.warning("Lighter: position size $%.2f below minimum $%.2f for %s",
                               position_usd, meta['min_quote'], symbol)
                continue

            is_buy = signal > 0
            side = 'LONG' if is_buy else 'SHORT'

            logger.info("Lighter ENTRY: %s %s $%.2f (price=%.4f, leverage=%dx, signal=%s, size_mult=%.2f)",
                         symbol, side, position_usd, current_price, LIGHTER_LEVERAGE,
                         signal_type, sym_mult)

            # Set leverage first
            lev_result = update_leverage(symbol, LIGHTER_LEVERAGE)
            if lev_result.get('error'):
                logger.error("Lighter: leverage update failed for %s: %s", symbol, lev_result['error'])
                continue

            # Place market order
            result = place_market_order_usd(symbol, is_buy, position_usd)
            if result.get('error'):
                continue

            # Calculate SL/TP levels
            sl_pct = 0.03  # 3% stop loss
            tp_pct = 0.06  # 6% take profit (2:1 RR)
            if is_buy:
                stop_loss = current_price * (1 - sl_pct)
                take_profit = current_price * (1 + tp_pct)
            else:
                stop_loss = current_price * (1 + sl_pct)
                take_profit = current_price * (1 - tp_pct)

            # Record position
            base_size = position_usd / current_price
            position = CryptoPosition.objects.create(
                symbol=symbol,
                side=side,
                entry_price=current_price,
                size=base_size,
                leverage=LIGHTER_LEVERAGE,
                entry_signal=f"{PLATFORM_PREFIX}{signal_type}_ema_{EMA_FAST}_{EMA_SLOW}",
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

            CryptoTrade.objects.create(
                position=position,
                order_id=result.get('tx_hash', ''),
                side='BUY' if is_buy else 'SELL',
                price=current_price,
                size=base_size,
                fee=0.0,  # Lighter has zero fees
                status='FILLED',
            )

            open_count += 1
            logger.info("Lighter position opened: %s %s size=%.6f signal=%s tx=%s",
                         symbol, side, base_size, signal_type, result.get('tx_hash', '?'))

        except Exception as e:
            logger.error("Lighter entry error for %s: %s", symbol, e)

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
from datetime import datetime, timezone
import pandas as pd

from .config import (
    LIGHTER_PAIRS, LIGHTER_MAX_POSITIONS,
    LIGHTER_LEVERAGE, LIGHTER_MARKETS, PLATFORM_PREFIX,
)
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage, place_oco_sltp, get_position_fill
from .sizing import calculate_position_usd

logger = logging.getLogger('app.lighter')

# Per-symbol EMA parameters — backtest-validated (2026-03-20)
# XAU 1h: EMA(5/100), 61.5% WR, PF 2.88
# AVAX 1h: EMA(8/21), 57.1% WR, PF 2.53
EMA_PARAMS = {
    'XAU': {'fast': 5, 'slow': 100},
    'AVAX': {'fast': 8, 'slow': 21},
}
DEFAULT_EMA = {'fast': 8, 'slow': 21}

# Per-symbol SL/TP as fractions — backtest-validated (2026-03-20)
SL_TP_PARAMS = {
    'XAU': (0.015, 0.03),   # 1.5% SL, 3% TP
    'AVAX': (0.03, 0.06),   # 3% SL, 6% TP
}
DEFAULT_SL_TP = (0.03, 0.06)  # Default: 3% SL, 6% TP

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 65
RSI_PULLBACK_BUY = 40    # For trend-following: buy when RSI dips below this in uptrend
RSI_PULLBACK_SELL = 60   # For trend-following: sell when RSI rises above this in downtrend
CANDLE_COUNT = 150  # Enough for EMA(100) + warmup

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


def _generate_signal_multitf(candles_1h: list, candles_15m: list, symbol: str = '') -> tuple:
    """Multi-timeframe signal generation.

    Returns (signal: int, signal_type: str) where signal is 1/-1/0
    and signal_type describes the trigger for logging.
    """
    ema_cfg = EMA_PARAMS.get(symbol, DEFAULT_EMA)
    ema_fast_period = ema_cfg['fast']
    ema_slow_period = ema_cfg['slow']

    if len(candles_1h) < ema_slow_period + 5:
        return 0, ''

    closes_1h = pd.Series([float(c['c']) for c in candles_1h])
    ema_fast_1h = _calculate_ema(closes_1h, ema_fast_period)
    ema_slow_1h = _calculate_ema(closes_1h, ema_slow_period)
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

    # --- Signal Mode 2: Trend-following pullback ---
    # trend_pullback_15m disabled — 36% WR losing strategy (2026-03-17 review)
    # if ema_trending_up and current_rsi_15m is not None:
    #     if current_rsi_15m < RSI_PULLBACK_BUY:
    #         return 1, 'trend_pullback_15m'
    #
    # if ema_trending_down and current_rsi_15m is not None:
    #     if current_rsi_15m > RSI_PULLBACK_SELL:
    #         return -1, 'trend_pullback_15m'

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
    """Get open Lighter EMA positions (excludes RSI2 — they have their own limit)."""
    from app.crypto.models import CryptoPosition
    return CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=PLATFORM_PREFIX,
    ).exclude(entry_signal__startswith=f'{PLATFORM_PREFIX}rsi2_')


def entry_algorithm():
    """Check signals on Lighter markets and enter positions.

    Uses multi-timeframe analysis (1h trend + 15m timing) and
    per-symbol performance filtering for adaptive risk management.

    Quality gates (lightweight — let the bot trade freely):
    1. Dashboard toggle
    2. Losing streak cooldown (5 consecutive losses → 5 min pause, then back to trading)
    3. Per-symbol performance filter
    """
    from django.core.cache import cache
    if cache.get('lighter:disabled'):
        logger.debug("Lighter: trading disabled via dashboard toggle")
        return

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
        # Vanish cooldown — position recently disappeared from exchange, don't re-enter
        if cache.get(f'lighter:vanish_cooldown:{symbol}'):
            logger.debug("Lighter: %s in vanish cooldown, skipping", symbol)
            continue

        meta = LIGHTER_MARKETS.get(symbol)
        if meta is None:
            logger.warning("Lighter: unknown symbol %s, skipping", symbol)
            continue

        try:
            # Fetch both timeframes (with Redis caching to avoid repeat API calls)
            ema_cfg = EMA_PARAMS.get(symbol, DEFAULT_EMA)
            ema_slow_period = ema_cfg['slow']

            cache_key_1h = f'lighter:candles:1h:{symbol}'
            candles_1h = cache.get(cache_key_1h)
            if candles_1h is None:
                candles_1h = get_candles(symbol, resolution='1h', count_back=CANDLE_COUNT)
                if candles_1h:
                    cache.set(cache_key_1h, candles_1h, timeout=60)
            if not candles_1h or len(candles_1h) < ema_slow_period + 5:
                logger.debug("Lighter: not enough 1h data for %s (%d bars)",
                             symbol, len(candles_1h) if candles_1h else 0)
                continue

            # 15m candles for timing confirmation
            candles_15m = None
            try:
                cache_key_15m = f'lighter:candles:15m:{symbol}'
                candles_15m = cache.get(cache_key_15m)
                if candles_15m is None:
                    candles_15m = get_candles(symbol, resolution='15m', count_back=CANDLE_COUNT)
                    if candles_15m:
                        cache.set(cache_key_15m, candles_15m, timeout=15)
            except Exception as e:
                logger.debug("Lighter: 15m candles unavailable for %s: %s", symbol, e)

            signal, signal_type = _generate_signal_multitf(candles_1h, candles_15m, symbol)
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

            # Per-symbol SL/TP from backtest-validated params
            sl_pct, tp_pct = SL_TP_PARAMS.get(symbol, DEFAULT_SL_TP)

            # Calculate position size in USD — risk-normalised via unified sizing
            position_usd = calculate_position_usd(symbol, sl_pct) * sym_mult
            if position_usd < meta['min_quote']:
                logger.warning("Lighter: position size $%.2f below minimum $%.2f for %s",
                               position_usd, meta['min_quote'], symbol)
                continue

            is_buy = signal > 0
            side = 'LONG' if is_buy else 'SHORT'
            if is_buy:
                stop_loss = current_price * (1 - sl_pct)
                take_profit = current_price * (1 + tp_pct)
            else:
                stop_loss = current_price * (1 + sl_pct)
                take_profit = current_price * (1 - tp_pct)

            base_size = position_usd / current_price

            # Reserve position in DB BEFORE placing exchange order — prevents duplicates
            position = CryptoPosition.objects.create(
                symbol=symbol,
                side=side,
                entry_price=current_price,
                size=base_size,
                leverage=LIGHTER_LEVERAGE,
                entry_signal=f"{PLATFORM_PREFIX}{signal_type}_ema_{ema_cfg['fast']}_{ema_cfg['slow']}",
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

            logger.info("Lighter ENTRY: %s %s $%.2f (price=%.4f, leverage=%dx, signal=%s, sym_mult=%.2f)",
                         symbol, side, position_usd, current_price, LIGHTER_LEVERAGE,
                         signal_type, sym_mult)

            # Set leverage (non-blocking)
            try:
                lev_result = update_leverage(symbol, LIGHTER_LEVERAGE)
                if lev_result.get('error'):
                    logger.warning("Lighter: leverage update failed for %s: %s — proceeding with current leverage", symbol, lev_result['error'])
            except Exception as e:
                logger.warning("Lighter: leverage exception for %s: %s — proceeding", symbol, e)

            # Place market order
            result = place_market_order_usd(symbol, is_buy, position_usd)
            if result.get('error'):
                # Order failed — clean up the reserved DB record
                position.delete()
                logger.error("Lighter: order failed for %s, cleaned up DB reservation: %s", symbol, result['error'])
                continue

            # Capture real fill price from exchange (post-settlement)
            fill = get_position_fill(symbol)
            fill_price = fill.get('entry_price', current_price)
            fill_size = fill.get('size', base_size)
            if fill:
                position.entry_price = fill_price
                position.size = fill_size
                position.save(update_fields=['entry_price', 'size'])
                logger.info("Lighter fill captured: %s entry=%.4f size=%.6f (quote=%.4f)",
                            symbol, fill_price, fill_size, current_price)

            CryptoTrade.objects.create(
                position=position,
                order_id=result.get('tx_hash', ''),
                side='BUY' if is_buy else 'SELL',
                price=fill_price,
                size=fill_size,
                fee=0.0,
                status='FILLED',
            )

            # Place native on-chain SL/TP as OCO group (one-cancels-other)
            try:
                oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
                if oco_result.get('error'):
                    logger.warning("Lighter OCO SL/TP failed for %s: %s", symbol, oco_result['error'])
                else:
                    logger.info("Lighter OCO SL/TP placed: %s SL=%.4f TP=%.4f tx=%s",
                                symbol, stop_loss, take_profit, oco_result.get('tx_hash', '?'))
            except Exception as e:
                logger.warning("Lighter OCO SL/TP exception for %s: %s", symbol, e)

            open_count += 1
            logger.info("Lighter position opened: %s %s size=%.6f signal=%s tx=%s",
                         symbol, side, base_size, signal_type, result.get('tx_hash', '?'))

        except Exception as e:
            logger.error("Lighter entry error for %s: %s", symbol, e)

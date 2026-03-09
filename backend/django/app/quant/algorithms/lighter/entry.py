"""
Lighter.xyz entry algorithm — momentum + RSI confirmation on perp markets.

Uses EMA crossover for trend direction and RSI for overbought/oversold
confirmation. Positions are tracked in CryptoPosition with platform prefix.
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
CANDLE_COUNT = 100


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


def _generate_signal(candles: list) -> int:
    """Generate signal from candle data. Returns 1 (buy), -1 (sell), 0 (neutral)."""
    if len(candles) < EMA_SLOW + 5:
        return 0

    closes = pd.Series([float(c['c']) for c in candles])

    ema_fast = _calculate_ema(closes, EMA_FAST)
    ema_slow = _calculate_ema(closes, EMA_SLOW)
    rsi = _calculate_rsi(closes, RSI_PERIOD)

    if pd.isna(ema_fast.iloc[-1]) or pd.isna(ema_slow.iloc[-1]) or pd.isna(rsi.iloc[-1]):
        return 0

    current_rsi = rsi.iloc[-1]
    ema_cross_up = ema_fast.iloc[-1] > ema_slow.iloc[-1] and ema_fast.iloc[-2] <= ema_slow.iloc[-2]
    ema_cross_down = ema_fast.iloc[-1] < ema_slow.iloc[-1] and ema_fast.iloc[-2] >= ema_slow.iloc[-2]
    ema_trending_up = ema_fast.iloc[-1] > ema_slow.iloc[-1]
    ema_trending_down = ema_fast.iloc[-1] < ema_slow.iloc[-1]

    # Buy: EMA cross up, or strong uptrend with RSI pullback
    if ema_cross_up and current_rsi < RSI_OVERBOUGHT:
        return 1
    if ema_trending_up and current_rsi < RSI_OVERSOLD:
        return 1

    # Sell: EMA cross down, or strong downtrend with RSI bounce
    if ema_cross_down and current_rsi > RSI_OVERSOLD:
        return -1
    if ema_trending_down and current_rsi > RSI_OVERBOUGHT:
        return -1

    return 0


def _get_open_positions():
    """Get all open Lighter positions."""
    from app.crypto.models import CryptoPosition
    return CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=PLATFORM_PREFIX,
    )


def entry_algorithm():
    """Check signals on Lighter markets and enter positions."""
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
            candles = get_candles(symbol, resolution='1h', count_back=CANDLE_COUNT)
            if not candles or len(candles) < EMA_SLOW + 5:
                logger.debug("Lighter: not enough candle data for %s (%d bars)", symbol, len(candles) if candles else 0)
                continue

            signal = _generate_signal(candles)
            if signal == 0:
                logger.debug("Lighter: no signal for %s", symbol)
                continue

            # Get current price
            prices = get_best_bid_ask(symbol)
            current_price = prices.get('mid')
            if not current_price or current_price <= 0:
                logger.warning("Lighter: no price data for %s", symbol)
                continue

            # Calculate position size in USD
            position_usd = LIGHTER_CAPITAL_USD * LIGHTER_POSITION_SIZE_PCT * LIGHTER_LEVERAGE
            if position_usd < meta['min_quote']:
                logger.warning("Lighter: position size $%.2f below minimum $%.2f for %s",
                               position_usd, meta['min_quote'], symbol)
                continue

            is_buy = signal > 0
            side = 'LONG' if is_buy else 'SHORT'

            logger.info("Lighter ENTRY: %s %s $%.2f (price=%.4f, leverage=%dx)",
                         symbol, side, position_usd, current_price, LIGHTER_LEVERAGE)

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
                entry_signal=f"{PLATFORM_PREFIX}momentum_ema_{EMA_FAST}_{EMA_SLOW}",
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
            logger.info("Lighter position opened: %s %s size=%.6f tx=%s",
                         symbol, side, base_size, result.get('tx_hash', '?'))

        except Exception as e:
            logger.error("Lighter entry error for %s: %s", symbol, e)

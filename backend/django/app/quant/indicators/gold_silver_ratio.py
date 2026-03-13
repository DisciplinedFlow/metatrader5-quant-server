"""Gold-Silver Ratio and momentum-trend indicators for metals/energy.

The Gold-Silver Ratio (XAUUSD / XAGUSD) is a classic inter-market gauge.
Extremes signal relative over- or under-valuation of silver vs gold.

Indicators:
    gold_silver_ratio - relative-value signal based on the XAU/XAG ratio
    momentum_trend    - MACD + EMA alignment trend-following signal
"""

import numpy as np
import pandas as pd


def gold_silver_ratio(data, params=None):
    """Gold-Silver ratio relative-value signal.

    Since the standard indicator interface receives a single DataFrame,
    the current XAUUSD price must be passed explicitly via params so the
    ratio can be computed against the XAGUSD close in ``data``.

    Params:
        gold_price  (float): current XAUUSD price (required)
        ratio_high  (float): threshold above which silver is undervalued (default 80)
        ratio_low   (float): threshold below which silver is overvalued  (default 65)

    Returns:
        str signal:
            'silver_undervalued' - ratio > ratio_high  (bullish silver)
            'silver_overvalued'  - ratio < ratio_low   (bearish silver)
            'neutral'            - ratio in normal range
    """
    params = params or {}
    gold_price = params.get('gold_price')
    ratio_high = params.get('ratio_high', 80)
    ratio_low = params.get('ratio_low', 65)

    if gold_price is None or len(data) == 0:
        return 'neutral'

    silver_price = data['close'].iloc[-1]

    if pd.isna(silver_price) or silver_price <= 0:
        return 'neutral'

    ratio = gold_price / silver_price

    if ratio > ratio_high:
        return 'silver_undervalued'
    if ratio < ratio_low:
        return 'silver_overvalued'

    return 'neutral'


def momentum_trend(data, params=None):
    """MACD + EMA alignment trend-following indicator.

    Combines MACD momentum (line vs signal, histogram direction) with a
    longer-term EMA to classify trend strength.  Works well on metals
    (XAUUSD, XAGUSD), energy, and indices.

    Params:
        fast       (int): MACD fast EMA period   (default 12)
        slow       (int): MACD slow EMA period   (default 26)
        signal     (int): MACD signal line period (default 9)
        ema_period (int): trend EMA period        (default 50)

    Returns:
        str signal:
            'strong_bullish' - MACD > signal, histogram growing, close > EMA
            'bullish'        - MACD > signal, close > EMA
            'strong_bearish' - MACD < signal, histogram shrinking, close < EMA
            'bearish'        - MACD < signal, close < EMA
            'neutral'        - mixed / insufficient data
    """
    params = params or {}
    fast = params.get('fast', 12)
    slow = params.get('slow', 26)
    signal_period = params.get('signal', 9)
    ema_period = params.get('ema_period', 50)

    df = data.copy()
    min_bars = max(slow, ema_period) + signal_period + 2

    if len(df) < min_bars:
        return 'neutral'

    # MACD computation
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    # Trend EMA
    ema_trend = df['close'].ewm(span=ema_period, adjust=False).mean()

    close = df['close'].iloc[-1]
    macd_val = macd_line.iloc[-1]
    signal_val = signal_line.iloc[-1]
    hist_curr = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2]
    ema_val = ema_trend.iloc[-1]

    if any(pd.isna(v) for v in [macd_val, signal_val, hist_curr, hist_prev, ema_val]):
        return 'neutral'

    macd_above_signal = macd_val > signal_val
    macd_below_signal = macd_val < signal_val
    close_above_ema = close > ema_val
    close_below_ema = close < ema_val
    histogram_growing = hist_curr > hist_prev      # histogram expanding bullishly
    histogram_shrinking = hist_curr < hist_prev     # histogram expanding bearishly

    # Strong bullish: all three aligned upward
    if macd_above_signal and histogram_growing and close_above_ema:
        return 'strong_bullish'

    # Bullish: MACD crossover with trend confirmation
    if macd_above_signal and close_above_ema:
        return 'bullish'

    # Strong bearish: all three aligned downward
    if macd_below_signal and histogram_shrinking and close_below_ema:
        return 'strong_bearish'

    # Bearish: MACD crossunder with trend confirmation
    if macd_below_signal and close_below_ema:
        return 'bearish'

    return 'neutral'

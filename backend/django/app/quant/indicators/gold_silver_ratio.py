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
        pd.Series of signal strings per bar:
            'silver_undervalued' - ratio > ratio_high  (bullish silver)
            'silver_overvalued'  - ratio < ratio_low   (bearish silver)
            'neutral'            - ratio in normal range
    """
    params = params or {}
    gold_price = params.get('gold_price')
    ratio_high = params.get('ratio_high', 80)
    ratio_low = params.get('ratio_low', 65)

    result = pd.Series('neutral', index=data.index, dtype=object)

    if gold_price is None or len(data) == 0:
        return result

    silver_close = data['close']
    valid = silver_close.notna() & (silver_close > 0)

    ratio = pd.Series(np.nan, index=data.index)
    ratio[valid] = gold_price / silver_close[valid]

    result[(ratio > ratio_high) & valid] = 'silver_undervalued'
    result[(ratio < ratio_low) & valid] = 'silver_overvalued'

    return result


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
        pd.Series of signal strings per bar:
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
    result = pd.Series('neutral', index=df.index, dtype=object)
    min_bars = max(slow, ema_period) + signal_period + 2

    if len(df) < min_bars:
        return result

    # MACD computation
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    hist_prev = histogram.shift(1)

    # Trend EMA
    ema_trend = df['close'].ewm(span=ema_period, adjust=False).mean()

    close = df['close']
    valid = macd_line.notna() & signal_line.notna() & histogram.notna() & hist_prev.notna() & ema_trend.notna()

    macd_above = (macd_line > signal_line) & valid
    macd_below = (macd_line < signal_line) & valid
    close_above = (close > ema_trend) & valid
    close_below = (close < ema_trend) & valid
    hist_growing = (histogram > hist_prev) & valid
    hist_shrinking = (histogram < hist_prev) & valid

    # Strong bullish: all three aligned upward
    result[macd_above & hist_growing & close_above] = 'strong_bullish'
    # Bullish: MACD crossover with trend confirmation
    result[macd_above & close_above & (result == 'neutral')] = 'bullish'
    # Strong bearish: all three aligned downward
    result[macd_below & hist_shrinking & close_below] = 'strong_bearish'
    # Bearish: MACD crossunder with trend confirmation
    result[macd_below & close_below & (result == 'neutral')] = 'bearish'

    return result

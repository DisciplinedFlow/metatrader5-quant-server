"""Donchian Channel indicators for trend-following strategies.

The Donchian Channel (Richard Donchian's "Turtle" breakout) marks the highest
high and lowest low over N periods.  A close beyond the channel signals a
breakout; a close back inside a shorter exit channel signals the exit.

Indicators:
    donchian_channel   - breakout / exit signals
    donchian_trend_filter - breakout filtered by EMA trend direction
    donchian_width     - channel width (volatility / squeeze gauge)

Designed for XAGUSD but works on any instrument.
"""

import numpy as np
import pandas as pd


def donchian_channel(data, params=None):
    """Donchian Channel breakout and exit signals.

    Params:
        entry_period (int): lookback for the entry channel (default 20)
        exit_period  (int): lookback for the exit channel  (default 10)

    Returns:
        pd.Series of signal strings per bar:
            'bullish_breakout' - close > entry-period highest high
            'bearish_breakout' - close < entry-period lowest low
            'exit_long'        - close < exit-period lowest low
            'exit_short'       - close > exit-period highest high
            'neutral'          - inside both channels
    """
    params = params or {}
    entry_period = params.get('entry_period', 20)
    exit_period = params.get('exit_period', 10)

    df = data.copy()
    result = pd.Series('neutral', index=df.index, dtype=object)

    if len(df) < max(entry_period, exit_period) + 1:
        return result

    # Entry channel: computed on the *previous* N bars (exclude current bar)
    entry_upper = df['high'].shift(1).rolling(window=entry_period).max()
    entry_lower = df['low'].shift(1).rolling(window=entry_period).min()

    # Exit channel: same logic, shorter period
    exit_upper = df['high'].shift(1).rolling(window=exit_period).max()
    exit_lower = df['low'].shift(1).rolling(window=exit_period).min()

    close = df['close']

    # Mask where all channel values are valid
    valid = entry_upper.notna() & entry_lower.notna() & exit_upper.notna() & exit_lower.notna()

    # Entry breakouts take priority over exit signals
    result[(close > entry_upper) & valid] = 'bullish_breakout'
    result[(close < entry_lower) & valid & (result == 'neutral')] = 'bearish_breakout'
    result[(close < exit_lower) & valid & (result == 'neutral')] = 'exit_long'
    result[(close > exit_upper) & valid & (result == 'neutral')] = 'exit_short'

    return result


def donchian_trend_filter(data, params=None):
    """Donchian breakout filtered by EMA trend direction.

    Only confirms a breakout when it aligns with the prevailing trend
    (close on the correct side of the EMA).  Breakouts against the trend
    are returned as 'filtered' so the caller can still see them.

    Params:
        entry_period (int): Donchian lookback (default 20)
        ema_period   (int): EMA trend filter  (default 50)

    Returns:
        pd.Series of signal strings per bar:
            'long_confirmed'  - bullish breakout AND close > EMA
            'short_confirmed' - bearish breakout AND close < EMA
            'filtered'        - breakout exists but against the EMA trend
            'neutral'         - no breakout
    """
    params = params or {}
    entry_period = params.get('entry_period', 20)
    ema_period = params.get('ema_period', 50)

    df = data.copy()
    result = pd.Series('neutral', index=df.index, dtype=object)

    if len(df) < max(entry_period, ema_period) + 1:
        return result

    # Donchian entry channel (exclude current bar)
    entry_upper = df['high'].shift(1).rolling(window=entry_period).max()
    entry_lower = df['low'].shift(1).rolling(window=entry_period).min()

    ema = df['close'].ewm(span=ema_period, adjust=False).mean()

    close = df['close']
    valid = entry_upper.notna() & entry_lower.notna() & ema.notna()

    bullish_breakout = (close > entry_upper) & valid
    bearish_breakout = (close < entry_lower) & valid

    result[bullish_breakout & (close > ema)] = 'long_confirmed'
    result[bullish_breakout & (close <= ema)] = 'filtered'
    result[bearish_breakout & (close < ema)] = 'short_confirmed'
    result[bearish_breakout & (close >= ema)] = 'filtered'

    return result


def donchian_width(data, params=None):
    """Donchian channel width — a measure of realised volatility / squeeze.

    Params:
        period (int): lookback window (default 20)

    Returns:
        pd.Series of float: upper - lower of the Donchian channel per bar.
               Returns 0.0 for bars with insufficient data.
    """
    params = params or {}
    period = params.get('period', 20)

    df = data.copy()
    result = pd.Series(0.0, index=df.index)

    if len(df) < period:
        return result

    upper = df['high'].rolling(window=period).max()
    lower = df['low'].rolling(window=period).min()

    width = upper - lower
    valid = upper.notna() & lower.notna()
    result[valid] = width[valid]

    return result

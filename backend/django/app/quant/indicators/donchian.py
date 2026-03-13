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
        str signal for the latest bar:
            'bullish_breakout' - close > 20-period highest high
            'bearish_breakout' - close < 20-period lowest low
            'exit_long'        - close < 10-period lowest low
            'exit_short'       - close > 10-period highest high
            'neutral'          - inside both channels
    """
    params = params or {}
    entry_period = params.get('entry_period', 20)
    exit_period = params.get('exit_period', 10)

    df = data.copy()
    min_bars = max(entry_period, exit_period) + 1

    if len(df) < min_bars:
        return 'neutral'

    # Entry channel: computed on the *previous* N bars (exclude current bar)
    entry_upper = df['high'].shift(1).rolling(window=entry_period).max()
    entry_lower = df['low'].shift(1).rolling(window=entry_period).min()

    # Exit channel: same logic, shorter period
    exit_upper = df['high'].shift(1).rolling(window=exit_period).max()
    exit_lower = df['low'].shift(1).rolling(window=exit_period).min()

    close = df['close'].iloc[-1]
    upper = entry_upper.iloc[-1]
    lower = entry_lower.iloc[-1]
    exit_hi = exit_upper.iloc[-1]
    exit_lo = exit_lower.iloc[-1]

    if pd.isna(upper) or pd.isna(lower) or pd.isna(exit_hi) or pd.isna(exit_lo):
        return 'neutral'

    # Entry breakouts take priority over exit signals
    if close > upper:
        return 'bullish_breakout'
    if close < lower:
        return 'bearish_breakout'
    if close < exit_lo:
        return 'exit_long'
    if close > exit_hi:
        return 'exit_short'

    return 'neutral'


def donchian_trend_filter(data, params=None):
    """Donchian breakout filtered by EMA trend direction.

    Only confirms a breakout when it aligns with the prevailing trend
    (close on the correct side of the EMA).  Breakouts against the trend
    are returned as 'filtered' so the caller can still see them.

    Params:
        entry_period (int): Donchian lookback (default 20)
        ema_period   (int): EMA trend filter  (default 50)

    Returns:
        str signal for the latest bar:
            'long_confirmed'  - bullish breakout AND close > EMA
            'short_confirmed' - bearish breakout AND close < EMA
            'filtered'        - breakout exists but against the EMA trend
            'neutral'         - no breakout
    """
    params = params or {}
    entry_period = params.get('entry_period', 20)
    ema_period = params.get('ema_period', 50)

    df = data.copy()
    min_bars = max(entry_period, ema_period) + 1

    if len(df) < min_bars:
        return 'neutral'

    # Donchian entry channel (exclude current bar)
    entry_upper = df['high'].shift(1).rolling(window=entry_period).max()
    entry_lower = df['low'].shift(1).rolling(window=entry_period).min()

    ema = df['close'].ewm(span=ema_period, adjust=False).mean()

    close = df['close'].iloc[-1]
    upper = entry_upper.iloc[-1]
    lower = entry_lower.iloc[-1]
    ema_val = ema.iloc[-1]

    if pd.isna(upper) or pd.isna(lower) or pd.isna(ema_val):
        return 'neutral'

    bullish_breakout = close > upper
    bearish_breakout = close < lower

    if bullish_breakout:
        return 'long_confirmed' if close > ema_val else 'filtered'
    if bearish_breakout:
        return 'short_confirmed' if close < ema_val else 'filtered'

    return 'neutral'


def donchian_width(data, params=None):
    """Donchian channel width — a measure of realised volatility / squeeze.

    Params:
        period (int): lookback window (default 20)

    Returns:
        float: upper - lower of the current Donchian channel.
               Returns 0.0 when there is insufficient data.
    """
    params = params or {}
    period = params.get('period', 20)

    df = data.copy()

    if len(df) < period:
        return 0.0

    upper = df['high'].rolling(window=period).max().iloc[-1]
    lower = df['low'].rolling(window=period).min().iloc[-1]

    if pd.isna(upper) or pd.isna(lower):
        return 0.0

    return float(upper - lower)

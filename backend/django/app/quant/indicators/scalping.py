import pandas as pd
import numpy as np


def ema_crossover(data, fast=9, slow=21):
    """
    Calculate EMA crossover signal.

    Returns a Series with 'bull_cross', 'bear_cross', or 0 for each row.
    A bull_cross occurs when the fast EMA crosses above the slow EMA.
    A bear_cross occurs when the fast EMA crosses below the slow EMA.
    """
    ema_fast = data['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = data['close'].ewm(span=slow, adjust=False).mean()

    signal = pd.Series(0, index=data.index, dtype=object)

    for i in range(1, len(data)):
        prev_fast = ema_fast.iloc[i - 1]
        prev_slow = ema_slow.iloc[i - 1]
        curr_fast = ema_fast.iloc[i]
        curr_slow = ema_slow.iloc[i]

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            signal.iloc[i] = 'bull_cross'
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            signal.iloc[i] = 'bear_cross'

    return signal


def rsi(data, period=14):
    """
    Calculate the Relative Strength Index (RSI).

    Returns a Series of RSI values.
    """
    delta = data['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))

    return rsi_values


def atr(data, period=14):
    """
    Calculate the Average True Range (ATR).

    Returns a Series of ATR values.
    """
    high = data['high']
    low = data['low']
    close = data['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_values = true_range.ewm(span=period, adjust=False).mean()

    return atr_values

"""EMA Ribbon Pullback momentum indicator.

Trend continuation strategy using 4-EMA ribbon alignment with pullback entries.
When all EMAs are properly stacked in a strong trend (ADX confirms), and price
pulls back to the inner EMAs then closes back in the trend direction, generate
a signal. Filters out ranging markets and weak pullbacks.
"""

import numpy as np
import pandas as pd


def ema_ribbon_pullback(data, params=None):
    """
    Detect EMA ribbon alignment + confirmed pullback entry in strong trends.

    Filters:
    - ADX > threshold confirms a real trend exists (eliminates ranging markets)
    - EMA ribbon must be properly stacked (8 > 13 > 21 > 34 or reversed)
    - Minimum spread between fastest/slowest EMA as % of price
    - Price must pull back to touch EMA13 or EMA21
    - Candle must close back in trend direction (above EMA8 for bull, below for bear)
    - RSI must be in neutral zone (not overbought/oversold)

    Returns Series of signal strings or 0.
    """
    params = params or {}
    ema_periods = params.get('ema_periods', [8, 13, 21, 34])
    rsi_period = params.get('rsi_period', 14)
    rsi_low = params.get('rsi_low', 35)
    rsi_high = params.get('rsi_high', 65)
    adx_period = params.get('adx_period', 14)
    adx_threshold = params.get('adx_threshold', 25)
    min_spread_pct = params.get('min_spread_pct', 0.001)  # 0.1% min EMA spread

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)

    if len(ema_periods) < 4:
        return result

    min_bars = max(ema_periods) + max(rsi_period, adx_period) + 5
    if len(df) < min_bars:
        return result

    # Compute EMAs
    emas = {}
    for period in ema_periods:
        emas[period] = df['close'].ewm(span=period, adjust=False).mean()

    # Compute RSI
    price_delta = df['close'].diff()
    gain = price_delta.where(price_delta > 0, 0.0)
    loss = (-price_delta).where(price_delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / rsi_period, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_period, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Compute ADX
    adx = _compute_adx(df, adx_period)

    # Check conditions for each bar
    start_idx = min_bars
    for i in range(start_idx, len(df)):
        e8 = emas[ema_periods[0]].iloc[i]
        e13 = emas[ema_periods[1]].iloc[i]
        e21 = emas[ema_periods[2]].iloc[i]
        e34 = emas[ema_periods[3]].iloc[i]

        rsi_val = rsi.iloc[i]
        adx_val = adx.iloc[i]
        close = df['close'].iloc[i]
        low = df['low'].iloc[i]
        high = df['high'].iloc[i]

        # Skip NaN values
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e21) or pd.isna(e34):
            continue
        if pd.isna(rsi_val) or pd.isna(adx_val):
            continue

        # ADX filter: must be in a real trend
        if adx_val < adx_threshold:
            continue

        # RSI filter: neutral zone
        if not (rsi_low <= rsi_val <= rsi_high):
            continue

        # EMA spread filter: ribbon must have meaningful separation
        spread = abs(e8 - e34) / close
        if spread < min_spread_pct:
            continue

        # Bullish: EMA8 > EMA13 > EMA21 > EMA34
        if e8 > e13 > e21 > e34:
            # Price pulled back to touch EMA13 or EMA21
            pullback = low <= e13 or low <= e21
            # But candle closed back above EMA8 (trend resumes)
            confirmed = close > e8
            if pullback and confirmed:
                result.iloc[i] = 'bullish_ribbon_pullback'

        # Bearish: EMA8 < EMA13 < EMA21 < EMA34
        elif e8 < e13 < e21 < e34:
            pullback = high >= e13 or high >= e21
            confirmed = close < e8
            if pullback and confirmed:
                result.iloc[i] = 'bearish_ribbon_pullback'

    return result


def _compute_adx(df, period=14):
    """Compute Average Directional Index (ADX)."""
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smoothed averages
    atr = pd.Series(tr, index=df.index).ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period).mean() / atr

    # ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return adx

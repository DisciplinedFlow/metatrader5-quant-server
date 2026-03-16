"""Volume Weighted Average Price (VWAP) indicator.

Institutional benchmark price — traders watch for price above/below VWAP
to determine intraday bias. Resets at session start (00:00 UTC for forex).

Used in confluence scoring: price above VWAP = bullish bias, below = bearish.
"""
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger('quant')


def calculate_vwap(df: pd.DataFrame, session_reset: bool = True) -> pd.Series:
    """Calculate VWAP from OHLCV data.

    Args:
        df: DataFrame with 'high', 'low', 'close', 'tick_volume' columns and datetime index
        session_reset: If True, reset VWAP at each new trading day (00:00 UTC)

    Returns:
        Series with VWAP values
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    volume = df['tick_volume'].replace(0, np.nan).fillna(1)  # Avoid div by zero

    if session_reset and hasattr(df.index, 'date'):
        # Group by trading day and calculate cumulative VWAP per session
        vwap = pd.Series(index=df.index, dtype=float)
        for date, group in df.groupby(df.index.date):
            tp = typical_price.loc[group.index]
            vol = volume.loc[group.index]
            cum_tp_vol = (tp * vol).cumsum()
            cum_vol = vol.cumsum()
            vwap.loc[group.index] = cum_tp_vol / cum_vol
        return vwap
    else:
        cum_tp_vol = (typical_price * volume).cumsum()
        cum_vol = volume.cumsum()
        return cum_tp_vol / cum_vol


def get_vwap_bias(df: pd.DataFrame) -> dict:
    """Get current VWAP bias for confluence scoring.

    Returns:
        dict with keys: 'vwap', 'price', 'bias' ('BULLISH'/'BEARISH'/'NEUTRAL'),
        'distance_pct' (% distance from VWAP)
    """
    try:
        if len(df) < 10:
            return {'vwap': 0, 'price': 0, 'bias': 'NEUTRAL', 'distance_pct': 0}

        vwap = calculate_vwap(df)
        current_vwap = vwap.iloc[-1]
        current_price = df['close'].iloc[-1]

        if pd.isna(current_vwap) or current_vwap <= 0:
            return {'vwap': 0, 'price': current_price, 'bias': 'NEUTRAL', 'distance_pct': 0}

        distance_pct = ((current_price - current_vwap) / current_vwap) * 100

        # Threshold: 0.05% from VWAP = neutral zone
        if abs(distance_pct) < 0.05:
            bias = 'NEUTRAL'
        elif current_price > current_vwap:
            bias = 'BULLISH'
        else:
            bias = 'BEARISH'

        return {
            'vwap': round(current_vwap, 5),
            'price': round(current_price, 5),
            'bias': bias,
            'distance_pct': round(distance_pct, 3),
        }
    except Exception as e:
        logger.debug(f"VWAP calculation error: {e}")
        return {'vwap': 0, 'price': 0, 'bias': 'NEUTRAL', 'distance_pct': 0}

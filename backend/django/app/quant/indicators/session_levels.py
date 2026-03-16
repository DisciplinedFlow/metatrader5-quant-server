"""Session OHLC Levels — key institutional reference prices.

Tracks previous day high/low, Asian session high/low, and current session open.
These are the levels where institutional stop hunts and liquidity sweeps occur.

Used in confluence scoring: price near prev day high/low = potential sweep setup.
"""
import pandas as pd
import logging
from datetime import time

logger = logging.getLogger('quant')

# Session times in UTC
ASIAN_SESSION = (time(0, 0), time(7, 0))     # 00:00 - 07:00 UTC
LONDON_SESSION = (time(7, 0), time(15, 0))   # 07:00 - 15:00 UTC
NY_SESSION = (time(12, 0), time(21, 0))      # 12:00 - 21:00 UTC


def get_session_levels(df: pd.DataFrame) -> dict:
    """Calculate key session reference levels.

    Args:
        df: DataFrame with OHLCV data and datetime index (at least 2 days of data)

    Returns:
        dict with prev_day_high, prev_day_low, asian_high, asian_low,
        session_open, and proximity flags
    """
    try:
        if len(df) < 20 or not hasattr(df.index, 'date'):
            return _empty_levels()

        now = df.index[-1]
        today = now.date()

        # Previous day levels
        prev_day = df[df.index.date < today]
        if len(prev_day) < 5:
            return _empty_levels()

        last_day = prev_day.index.date[-1]
        prev_day_bars = prev_day[prev_day.index.date == last_day]
        prev_day_high = prev_day_bars['high'].max()
        prev_day_low = prev_day_bars['low'].min()

        # Asian session levels (today)
        today_bars = df[df.index.date == today]
        if len(today_bars) > 0:
            asian_bars = today_bars[today_bars.index.time < ASIAN_SESSION[1]]
            asian_high = asian_bars['high'].max() if len(asian_bars) > 0 else 0
            asian_low = asian_bars['low'].min() if len(asian_bars) > 0 else 0
            session_open = today_bars['open'].iloc[0]
        else:
            asian_high = 0
            asian_low = 0
            session_open = 0

        current_price = df['close'].iloc[-1]
        atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1] if len(df) >= 14 else 0

        # Proximity checks (within 0.5 ATR of level)
        proximity_threshold = atr * 0.5 if atr > 0 else 0

        near_prev_high = abs(current_price - prev_day_high) < proximity_threshold if proximity_threshold > 0 else False
        near_prev_low = abs(current_price - prev_day_low) < proximity_threshold if proximity_threshold > 0 else False
        near_asian_high = abs(current_price - asian_high) < proximity_threshold if proximity_threshold > 0 and asian_high > 0 else False
        near_asian_low = abs(current_price - asian_low) < proximity_threshold if proximity_threshold > 0 and asian_low > 0 else False

        return {
            'prev_day_high': round(prev_day_high, 5),
            'prev_day_low': round(prev_day_low, 5),
            'asian_high': round(asian_high, 5),
            'asian_low': round(asian_low, 5),
            'session_open': round(session_open, 5),
            'current_price': round(current_price, 5),
            'near_prev_high': bool(near_prev_high),
            'near_prev_low': bool(near_prev_low),
            'near_asian_high': bool(near_asian_high),
            'near_asian_low': bool(near_asian_low),
            'sweep_setup': bool(near_prev_high or near_prev_low or near_asian_high or near_asian_low),
        }
    except Exception as e:
        logger.debug(f"Session levels error: {e}")
        return _empty_levels()


def _empty_levels():
    return {
        'prev_day_high': 0, 'prev_day_low': 0,
        'asian_high': 0, 'asian_low': 0,
        'session_open': 0, 'current_price': 0,
        'near_prev_high': False, 'near_prev_low': False,
        'near_asian_high': False, 'near_asian_low': False,
        'sweep_setup': False,
    }

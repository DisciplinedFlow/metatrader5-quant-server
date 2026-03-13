"""AUDUSD Session-Based Hybrid Strategy Indicators.

Combines mean reversion during Asian session with breakout during London,
tailored for AUDUSD's unique behavior as a commodity-linked currency.

Session definitions (UTC):
- Asian (22:00-06:00): Low volatility, range-bound → mean reversion via BB+RSI
- London (06:00-10:00): Volatility expansion → breakout of Asian range
- London/NY overlap (10:00-14:00): Trend continuation
- US afternoon (14:00-22:00): Wind down, no new entries

AUDUSD correlation context:
- Positively correlated with risk-on (equities, iron ore, gold)
- Asian session range is tighter than major pairs → reliable reversion levels
- London open frequently sweeps Asian liquidity → classic breakout setup
"""

import logging
from datetime import time, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger('session_hybrid')


# ---------------------------------------------------------------------------
# Session boundaries (UTC)
# ---------------------------------------------------------------------------

ASIAN_START = time(22, 0)   # 22:00 UTC (previous day)
ASIAN_END = time(6, 0)      # 06:00 UTC
LONDON_START = time(6, 0)   # 06:00 UTC
LONDON_END = time(10, 0)    # 10:00 UTC
TREND_START = time(10, 0)   # 10:00 UTC
TREND_END = time(14, 0)     # 14:00 UTC
CLOSE_START = time(14, 0)   # 14:00 UTC
CLOSE_END = time(22, 0)     # 22:00 UTC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_utc_time(df):
    """Extract the UTC time from the last candle's index.

    Handles both timezone-aware and naive DatetimeIndex (naive assumed UTC).

    Returns:
        datetime.time in UTC, or None if the index is not a DatetimeIndex.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        logger.warning("DataFrame index is not DatetimeIndex — cannot detect session")
        return None

    last_ts = df.index[-1]
    if last_ts.tzinfo is not None:
        last_ts = last_ts.tz_convert('UTC')

    return last_ts.time()


def _time_in_range(t, start, end):
    """Check if time t is in [start, end). Handles overnight wrap (start > end)."""
    if start <= end:
        return start <= t < end
    else:
        # Overnight range: e.g. 22:00 -> 06:00
        return t >= start or t < end


def _calculate_rsi(close, period):
    """Calculate RSI using exponential weighted moving average."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calculate_bollinger_bands(close, period, num_std):
    """Calculate Bollinger Bands.

    Returns:
        (middle, upper, lower) — each a pd.Series.
    """
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    return middle, upper, lower


def _get_asian_range(df):
    """Extract the Asian session high and low from the DataFrame.

    Looks for candles with timestamps between 22:00 (previous day) and 06:00 UTC.
    Works with the available data in the DataFrame rather than requiring a
    specific date.

    Returns:
        (asian_high, asian_low) or (None, None) if no Asian candles found.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        return None, None

    # Work with UTC times
    idx = df.index
    if idx.tz is not None:
        idx = idx.tz_convert('UTC')
    else:
        idx = idx.tz_localize('UTC')

    # Get the date of the last candle to anchor our search
    last_ts = idx[-1]

    # Asian session spans 22:00 previous day to 06:00 current day
    # Build the two windows that form the Asian session
    asian_date = last_ts.date()

    # Part 1: 22:00 on the day before last_ts's date to midnight
    from datetime import datetime, timedelta
    prev_day = asian_date - timedelta(days=1)
    part1_start = pd.Timestamp(datetime.combine(prev_day, ASIAN_START), tz='UTC')
    part1_end = pd.Timestamp(datetime.combine(asian_date, time(0, 0)), tz='UTC')

    # Part 2: midnight to 06:00 on last_ts's date
    part2_start = pd.Timestamp(datetime.combine(asian_date, time(0, 0)), tz='UTC')
    part2_end = pd.Timestamp(datetime.combine(asian_date, ASIAN_END), tz='UTC')

    # Localize the df index for comparison
    df_utc = df.copy()
    if df.index.tz is None:
        df_utc.index = df.index.tz_localize('UTC')
    else:
        df_utc.index = df.index.tz_convert('UTC')

    # Select candles in the Asian session
    mask_part1 = (df_utc.index >= part1_start) & (df_utc.index < part1_end)
    mask_part2 = (df_utc.index >= part2_start) & (df_utc.index < part2_end)
    asian_candles = df_utc[mask_part1 | mask_part2]

    if asian_candles.empty:
        logger.debug("No Asian session candles found in DataFrame")
        return None, None

    asian_high = asian_candles['high'].max()
    asian_low = asian_candles['low'].min()

    return asian_high, asian_low


# ---------------------------------------------------------------------------
# Indicator 1: Asian Mean Reversion
# ---------------------------------------------------------------------------

def asian_mean_reversion(df, params=None):
    """Mean reversion signal for Asian session (22:00-06:00 UTC).

    Uses Bollinger Bands + RSI to identify overstretched price at band
    extremes during the low-volatility Asian session, where mean reversion
    has a higher probability.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.
            Index must be DatetimeIndex.
        params: dict with optional keys:
            - bb_period (int): Bollinger Band lookback, default 20
            - bb_std (float): Bollinger Band std dev multiplier, default 2.0
            - rsi_period (int): RSI lookback, default 14
            - rsi_oversold (float): RSI oversold threshold, default 30
            - rsi_overbought (float): RSI overbought threshold, default 70

    Returns:
        str: 'bullish_reversion', 'bearish_reversion', 'neutral', or 'off_session'
    """
    if params is None:
        params = {}

    bb_period = params.get('bb_period', 20)
    bb_std = params.get('bb_std', 2.0)
    rsi_period = params.get('rsi_period', 14)
    rsi_oversold = params.get('rsi_oversold', 30)
    rsi_overbought = params.get('rsi_overbought', 70)

    # --- Session check ---
    utc_time = _get_utc_time(df)
    if utc_time is None:
        return 'off_session'

    if not _time_in_range(utc_time, ASIAN_START, ASIAN_END):
        return 'off_session'

    # --- Guard: enough data ---
    min_bars = max(bb_period, rsi_period) + 1
    if len(df) < min_bars:
        logger.debug(f"asian_mean_reversion: need {min_bars} bars, got {len(df)}")
        return 'neutral'

    # --- Indicators ---
    close = df['close']
    middle, upper, lower = _calculate_bollinger_bands(close, bb_period, bb_std)
    rsi_values = _calculate_rsi(close, rsi_period)

    current_close = close.iloc[-1]
    current_upper = upper.iloc[-1]
    current_lower = lower.iloc[-1]
    current_rsi = rsi_values.iloc[-1]

    # --- NaN check ---
    if np.isnan(current_upper) or np.isnan(current_lower) or np.isnan(current_rsi):
        return 'neutral'

    # --- Signal logic ---
    if current_close <= current_lower and current_rsi < rsi_oversold:
        return 'bullish_reversion'
    elif current_close >= current_upper and current_rsi > rsi_overbought:
        return 'bearish_reversion'
    else:
        return 'neutral'


# ---------------------------------------------------------------------------
# Indicator 2: London Breakout
# ---------------------------------------------------------------------------

def london_breakout(df, params=None):
    """Breakout signal for London session (06:00-10:00 UTC).

    Identifies when price breaks out of the prior Asian session's range,
    confirmed by EMA trend direction. Unconfirmed breakouts (against the
    EMA trend) are flagged separately for discretionary use.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.
            Index must be DatetimeIndex.
        params: dict with optional keys:
            - breakout_buffer_pips (float): Pips above/below Asian range
              for confirmed breakout, default 5
            - pip_size (float): Value of one pip, default 0.0001
            - ema_period (int): EMA period for trend filter, default 20

    Returns:
        str: 'bullish_breakout', 'bearish_breakout',
             'unconfirmed_bullish', 'unconfirmed_bearish',
             'neutral', or 'off_session'
    """
    if params is None:
        params = {}

    breakout_buffer_pips = params.get('breakout_buffer_pips', 5)
    pip_size = params.get('pip_size', 0.0001)
    ema_period = params.get('ema_period', 20)

    # --- Session check ---
    utc_time = _get_utc_time(df)
    if utc_time is None:
        return 'off_session'

    if not _time_in_range(utc_time, LONDON_START, LONDON_END):
        return 'off_session'

    # --- Asian range ---
    asian_high, asian_low = _get_asian_range(df)
    if asian_high is None or asian_low is None:
        logger.debug("london_breakout: no Asian range available")
        return 'neutral'

    # --- Guard: enough data for EMA ---
    if len(df) < ema_period:
        logger.debug(f"london_breakout: need {ema_period} bars, got {len(df)}")
        return 'neutral'

    # --- Indicators ---
    close = df['close']
    ema = close.ewm(span=ema_period, adjust=False).mean()

    current_close = close.iloc[-1]
    current_ema = ema.iloc[-1]

    if np.isnan(current_ema):
        return 'neutral'

    buffer = breakout_buffer_pips * pip_size
    breakout_high = asian_high + buffer
    breakout_low = asian_low - buffer

    # --- Signal logic ---
    if current_close > breakout_high:
        if current_close > current_ema:
            return 'bullish_breakout'
        else:
            return 'unconfirmed_bullish'
    elif current_close < breakout_low:
        if current_close < current_ema:
            return 'bearish_breakout'
        else:
            return 'unconfirmed_bearish'
    else:
        return 'neutral'


# ---------------------------------------------------------------------------
# Indicator 3: Session Strategy Router
# ---------------------------------------------------------------------------

def session_strategy_router(df, params=None):
    """Meta-indicator: returns which strategy mode to use for the current session.

    This routes the entry algorithm to the correct strategy based on time-of-day,
    reflecting the structural behavior of AUDUSD across sessions.

    Args:
        df: DataFrame with DatetimeIndex. Only the last candle timestamp is used.
        params: dict (unused, included for consistent signature)

    Returns:
        str: 'mean_reversion' (22:00-06:00 UTC)
             'breakout' (06:00-10:00 UTC)
             'trend_follow' (10:00-14:00 UTC)
             'close_all' (14:00-22:00 UTC)
    """
    utc_time = _get_utc_time(df)
    if utc_time is None:
        # Cannot determine session — default to safe mode
        return 'close_all'

    if _time_in_range(utc_time, ASIAN_START, ASIAN_END):
        return 'mean_reversion'
    elif _time_in_range(utc_time, LONDON_START, LONDON_END):
        return 'breakout'
    elif _time_in_range(utc_time, TREND_START, TREND_END):
        return 'trend_follow'
    else:
        return 'close_all'


# ---------------------------------------------------------------------------
# Indicator 4: Commodity Correlation Filter
# ---------------------------------------------------------------------------

def commodity_correlation_filter(df, params=None):
    """Pre-trade filter based on commodity/risk-on correlation proxy.

    AUDUSD is positively correlated with risk-on assets (gold, iron ore,
    equities). This simplified version uses the EMA slope of the close
    price as a proxy for broad risk sentiment.

    In production, the entry algorithm can pass gold or iron ore data
    via params['external_close'] for real cross-asset correlation.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.
        params: dict with optional keys:
            - correlation_period (int): Lookback for trend assessment, default 20
            - gold_trend_ema (int): EMA period for slope calculation, default 50
            - external_close (pd.Series): Optional external asset close prices
              (e.g., XAUUSD) for real correlation. If not provided, uses
              the AUDUSD close as a self-trend proxy.

    Returns:
        str: 'favor_long', 'favor_short', or 'neutral'
    """
    if params is None:
        params = {}

    correlation_period = params.get('correlation_period', 20)
    gold_trend_ema = params.get('gold_trend_ema', 50)

    # Use external close data if provided (e.g., gold prices), otherwise self-proxy
    external_close = params.get('external_close', None)
    if external_close is not None and isinstance(external_close, pd.Series):
        close = external_close
    else:
        close = df['close']

    # --- Guard: enough data ---
    min_bars = gold_trend_ema + correlation_period
    if len(close) < min_bars:
        logger.debug(
            f"commodity_correlation_filter: need {min_bars} bars, got {len(close)}"
        )
        return 'neutral'

    # --- EMA slope as trend proxy ---
    ema = close.ewm(span=gold_trend_ema, adjust=False).mean()

    if ema.iloc[-1] is None or np.isnan(ema.iloc[-1]):
        return 'neutral'

    # Calculate slope: change in EMA over the correlation period
    # Positive slope → risk-on → favor longs
    # Negative slope → risk-off → favor shorts
    ema_now = ema.iloc[-1]
    ema_past = ema.iloc[-correlation_period]

    if np.isnan(ema_past):
        return 'neutral'

    slope = ema_now - ema_past

    # Normalize slope relative to price level to handle different instruments
    price_level = close.iloc[-1]
    if price_level == 0:
        return 'neutral'

    normalized_slope = slope / price_level

    # Threshold: slope must be at least 0.1% over the period to be meaningful
    threshold = 0.001

    if normalized_slope > threshold:
        return 'favor_long'
    elif normalized_slope < -threshold:
        return 'favor_short'
    else:
        return 'neutral'

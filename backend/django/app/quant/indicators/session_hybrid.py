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
    """Extract the UTC time from the last candle's index or 'time' column.

    Handles DatetimeIndex (tz-aware or naive), RangeIndex with 'time' column
    (typical MT5 API response), and epoch timestamps.

    Returns:
        datetime.time in UTC, or None if no timestamp source found.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        last_ts = df.index[-1]
        if last_ts.tzinfo is not None:
            last_ts = last_ts.tz_convert('UTC')
        return last_ts.time()

    # Fallback: 'time' column (MT5 API returns RangeIndex + 'time' col)
    if 'time' in df.columns:
        try:
            last_ts = pd.Timestamp(df['time'].iloc[-1])
            if last_ts.tzinfo is not None:
                last_ts = last_ts.tz_convert('UTC')
            return last_ts.time()
        except Exception:
            pass

    logger.debug("No timestamp source found in DataFrame — cannot detect session")
    return None


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

    result = pd.Series('neutral', index=df.index, dtype=object)

    # --- Guard: enough data ---
    min_bars = max(bb_period, rsi_period) + 1
    if len(df) < min_bars:
        logger.debug(f"asian_mean_reversion: need {min_bars} bars, got {len(df)}")
        return result

    # --- Session mask ---
    # Determine which bars fall in the Asian session
    if isinstance(df.index, pd.DatetimeIndex):
        hours_series = df.index.hour
        minutes_series = df.index.minute
        bar_times = [t.time() for t in df.index]
    elif 'time' in df.columns:
        try:
            timestamps = pd.to_datetime(df['time'])
            hours_series = timestamps.dt.hour
            minutes_series = timestamps.dt.minute
            bar_times = [t.time() for t in timestamps]
        except Exception:
            result[:] = 'off_session'
            return result
    else:
        result[:] = 'off_session'
        return result

    in_asian = pd.Series(False, index=df.index)
    for i in range(len(df)):
        in_asian.iloc[i] = _time_in_range(bar_times[i], ASIAN_START, ASIAN_END)

    result[~in_asian] = 'off_session'

    # --- Indicators ---
    close = df['close']
    middle, upper, lower = _calculate_bollinger_bands(close, bb_period, bb_std)
    rsi_values = _calculate_rsi(close, rsi_period)

    valid = upper.notna() & lower.notna() & rsi_values.notna() & in_asian

    result[(close <= lower) & (rsi_values < rsi_oversold) & valid] = 'bullish_reversion'
    result[(close >= upper) & (rsi_values > rsi_overbought) & valid] = 'bearish_reversion'

    return result


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

    result = pd.Series('neutral', index=df.index, dtype=object)

    # --- Guard: enough data for EMA ---
    if len(df) < ema_period:
        logger.debug(f"london_breakout: need {ema_period} bars, got {len(df)}")
        return result

    # --- Session mask ---
    if isinstance(df.index, pd.DatetimeIndex):
        bar_times = [t.time() for t in df.index]
    elif 'time' in df.columns:
        try:
            timestamps = pd.to_datetime(df['time'])
            bar_times = [t.time() for t in timestamps]
        except Exception:
            result[:] = 'off_session'
            return result
    else:
        result[:] = 'off_session'
        return result

    in_london = pd.Series(False, index=df.index)
    for i in range(len(df)):
        in_london.iloc[i] = _time_in_range(bar_times[i], LONDON_START, LONDON_END)

    result[~in_london] = 'off_session'

    # --- Asian range (single value used for all London bars) ---
    asian_high, asian_low = _get_asian_range(df)
    if asian_high is None or asian_low is None:
        logger.debug("london_breakout: no Asian range available")
        return result

    # --- Indicators ---
    close = df['close']
    ema = close.ewm(span=ema_period, adjust=False).mean()

    buffer = breakout_buffer_pips * pip_size
    breakout_high = asian_high + buffer
    breakout_low = asian_low - buffer

    valid = ema.notna() & in_london

    result[(close > breakout_high) & (close > ema) & valid] = 'bullish_breakout'
    result[(close > breakout_high) & (close <= ema) & valid] = 'unconfirmed_bullish'
    result[(close < breakout_low) & (close < ema) & valid] = 'bearish_breakout'
    result[(close < breakout_low) & (close >= ema) & valid] = 'unconfirmed_bearish'

    return result


# ---------------------------------------------------------------------------
# Indicator 3: Session Strategy Router
# ---------------------------------------------------------------------------

def session_strategy_router(df, params=None):
    """Meta-indicator: returns which strategy mode to use for each bar's session.

    This routes the entry algorithm to the correct strategy based on time-of-day,
    reflecting the structural behavior of AUDUSD across sessions.

    Args:
        df: DataFrame with DatetimeIndex or 'time' column.
        params: dict (unused, included for consistent signature)

    Returns:
        pd.Series of strategy mode strings per bar:
             'mean_reversion' (22:00-06:00 UTC)
             'breakout' (06:00-10:00 UTC)
             'trend_follow' (10:00-14:00 UTC)
             'close_all' (14:00-22:00 UTC)
    """
    result = pd.Series('close_all', index=df.index, dtype=object)

    if len(df) == 0:
        return result

    # Extract time objects for each bar
    if isinstance(df.index, pd.DatetimeIndex):
        bar_times = [t.time() for t in df.index]
    elif 'time' in df.columns:
        try:
            timestamps = pd.to_datetime(df['time'])
            bar_times = [t.time() for t in timestamps]
        except Exception:
            return result
    else:
        return result

    for i in range(len(df)):
        t = bar_times[i]
        if _time_in_range(t, ASIAN_START, ASIAN_END):
            result.iloc[i] = 'mean_reversion'
        elif _time_in_range(t, LONDON_START, LONDON_END):
            result.iloc[i] = 'breakout'
        elif _time_in_range(t, TREND_START, TREND_END):
            result.iloc[i] = 'trend_follow'
        # else: stays 'close_all'

    return result


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

    result = pd.Series('neutral', index=df.index, dtype=object)

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
        return result

    # --- EMA slope as trend proxy ---
    ema = close.ewm(span=gold_trend_ema, adjust=False).mean()
    ema_past = ema.shift(correlation_period)

    slope = ema - ema_past

    # Normalize slope relative to price level to handle different instruments
    normalized_slope = slope / close.replace(0, np.nan)

    # Threshold: slope must be at least 0.1% over the period to be meaningful
    threshold = 0.001

    valid = ema.notna() & ema_past.notna() & normalized_slope.notna()

    result[(normalized_slope > threshold) & valid] = 'favor_long'
    result[(normalized_slope < -threshold) & valid] = 'favor_short'

    return result

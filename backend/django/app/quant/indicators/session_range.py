"""Asian Range Liquidity Sweep Fade indicators for GBPUSD.

Strategy premise: Institutions build positions during the low-volatility
Asian session (22:00-06:00 UTC), creating a defined range. During the
London open, price sweeps beyond this range to trigger stop-losses and
grab liquidity, then reverses back inside — the "sweep fade".

Optimal execution window is the London Kill Zone (07:00-10:00 UTC).

Indicators:
    asian_range        — Asian session high/low/width
    sweep_fade_signal  — Detects sweep-and-fade reversal setups
    session_filter     — Current trading session identifier
    london_killzone_active — London Kill Zone gate
"""

import numpy as np
import pandas as pd


def _extract_hour(df):
    """Extract the hour of the last bar, handling both DatetimeIndex and RangeIndex.

    MT5 API returns DataFrames with RangeIndex + 'time' column (epoch seconds).
    Returns the hour (int) or None if no timestamp source found.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        last_ts = df.index[-1]
        if last_ts.tzinfo is not None:
            last_ts = last_ts.tz_convert('UTC')
        return last_ts.hour

    if 'time' in df.columns:
        try:
            return pd.Timestamp(df['time'].iloc[-1]).hour
        except Exception:
            pass

    return None


def _extract_hours_series(index, df=None):
    """Extract hour series from index, falling back to 'time' column.

    Returns a numpy array of hours, or None if no timestamp source found.
    """
    if isinstance(index, pd.DatetimeIndex):
        return index.hour

    if df is not None and 'time' in df.columns:
        try:
            return pd.to_datetime(df['time']).dt.hour
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Indicator 1: Asian Range
# ---------------------------------------------------------------------------

def asian_range(df, params):
    """Calculate the Asian session high and low for each bar in the DataFrame.

    For each bar, the most recent completed Asian session range (high/low/width)
    is computed. Bars inside the Asian session or before any completed session
    receive ``'neutral'``.

    The Asian session spans from ``asian_start_hour`` (default 22:00 UTC)
    to ``asian_end_hour`` (default 06:00 UTC).  Because 22:00 > 06:00 the
    range wraps across midnight.

    Args:
        df: DataFrame with DatetimeIndex (UTC) and OHLCV columns.
        params: dict with optional keys ``asian_start_hour``, ``asian_end_hour``.

    Returns:
        pd.Series of pipe-delimited strings
        ``"range_high=X.XXXXX|range_low=X.XXXXX|range_width=X.XXXXX"``
        or ``"neutral"`` per bar.
    """
    asian_start = params.get('asian_start_hour', 22)
    asian_end = params.get('asian_end_hour', 6)

    if df.empty or len(df) < 2:
        return pd.Series('neutral', index=df.index)

    mask = np.asarray(
        _asian_session_mask(df.index, asian_start, asian_end, df=df)
    )

    if not mask.any():
        return pd.Series('neutral', index=df.index)

    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    result = ['neutral'] * n

    # Pre-compute completed Asian session ranges by scanning once.
    # Track session boundaries: each contiguous block of Asian bars
    # is a session. A session is "completed" once a non-Asian bar appears
    # after it.
    current_range_high = None
    current_range_low = None
    in_session = False
    session_high = None
    session_low = None

    for i in range(n):
        if mask[i]:
            # Inside Asian session — accumulate session range
            if not in_session:
                in_session = True
                session_high = highs[i]
                session_low = lows[i]
            else:
                if highs[i] > session_high:
                    session_high = highs[i]
                if lows[i] < session_low:
                    session_low = lows[i]
            # Bars inside the Asian session get the previous completed range
            if current_range_high is not None:
                rw = current_range_high - current_range_low
                result[i] = (
                    f"range_high={current_range_high:.5f}"
                    f"|range_low={current_range_low:.5f}"
                    f"|range_width={rw:.5f}"
                )
            # else stays 'neutral'
        else:
            # Outside Asian session
            if in_session:
                # Session just completed — lock in the range
                current_range_high = session_high
                current_range_low = session_low
                in_session = False
            if current_range_high is not None:
                rw = current_range_high - current_range_low
                result[i] = (
                    f"range_high={current_range_high:.5f}"
                    f"|range_low={current_range_low:.5f}"
                    f"|range_width={rw:.5f}"
                )
            # else stays 'neutral'

    return pd.Series(result, index=df.index)


# ---------------------------------------------------------------------------
# Indicator 2: Sweep Fade Signal
# ---------------------------------------------------------------------------

def sweep_fade_signal(df, params):
    """Detect liquidity sweeps beyond the Asian range with a reversal back inside.

    For each bar the function:
        1. Finds the most recent completed Asian session's high/low
           before that bar.
        2. Checks if any of the previous ``confirmation_candles`` bars
           wicked beyond the range by at least ``sweep_pips``.
        3. Checks if the current bar closed back inside the range.

    Args:
        df: DataFrame with DatetimeIndex (UTC) and OHLCV columns.
        params: dict with optional keys ``sweep_pips`` (default 3),
                ``confirmation_candles`` (default 3), ``pip_size``
                (default 0.0001), ``asian_start_hour``, ``asian_end_hour``.

    Returns:
        pd.Series of ``'bullish_sweep'``, ``'bearish_sweep'``, or
        ``'neutral'`` per bar.
    """
    sweep_pips = params.get('sweep_pips', 3)
    confirmation_candles = params.get('confirmation_candles', 3)
    pip_size = params.get('pip_size', 0.0001)
    asian_start = params.get('asian_start_hour', 22)
    asian_end = params.get('asian_end_hour', 6)

    sweep_distance = sweep_pips * pip_size

    if df.empty or len(df) < confirmation_candles + 1:
        return pd.Series('neutral', index=df.index)

    mask = np.asarray(
        _asian_session_mask(df.index, asian_start, asian_end, df=df)
    )

    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    n = len(df)
    signals = ['neutral'] * n

    # Track the completed Asian range as we scan forward.
    current_range_high = None
    current_range_low = None
    in_session = False
    session_high = None
    session_low = None

    for i in range(n):
        if mask[i]:
            # Inside Asian session — accumulate range
            if not in_session:
                in_session = True
                session_high = highs[i]
                session_low = lows[i]
            else:
                if highs[i] > session_high:
                    session_high = highs[i]
                if lows[i] < session_low:
                    session_low = lows[i]
            # Bars inside the Asian session stay 'neutral' (range still forming)
            continue

        # Outside Asian session
        if in_session:
            # Session just completed — lock in the range
            current_range_high = session_high
            current_range_low = session_low
            in_session = False

        if current_range_high is None:
            continue

        # Not enough preceding bars for the confirmation window
        if i < confirmation_candles:
            continue

        # Check the look-back window of confirmation_candles bars BEFORE bar i
        window_start = i - confirmation_candles
        window_highs = highs[window_start:i]
        window_lows = lows[window_start:i]

        swept_high = float(window_highs.max()) > current_range_high + sweep_distance
        swept_low = float(window_lows.min()) < current_range_low - sweep_distance

        closed_inside = current_range_low <= closes[i] <= current_range_high

        if not closed_inside:
            continue

        if swept_high and not swept_low:
            signals[i] = 'bearish_sweep'
        elif swept_low and not swept_high:
            signals[i] = 'bullish_sweep'
        # Both sides swept (whipsaw) — ambiguous, stays 'neutral'

    return pd.Series(signals, index=df.index)


# ---------------------------------------------------------------------------
# Indicator 3: Session Filter
# ---------------------------------------------------------------------------

def session_filter(df, params):
    """Return the trading session for each bar based on its timestamp.

    Sessions (UTC):
        asian       22:00 - 06:00  (wraps midnight)
        london      07:00 - 12:00
        new_york    12:00 - 17:00
        off_hours   17:00 - 22:00

    Args:
        df: DataFrame with DatetimeIndex (UTC).
        params: dict (unused, kept for interface consistency).

    Returns:
        pd.Series of ``'asian'``, ``'london'``, ``'new_york'``, or
        ``'off_hours'`` per bar.
    """
    if df.empty:
        return pd.Series('off_hours', index=df.index)

    hours = _extract_hours_series(df.index, df=df)
    if hours is None:
        return pd.Series('off_hours', index=df.index)

    result = pd.Series('off_hours', index=df.index)
    result[(hours >= 22) | (hours < 6)] = 'asian'
    result[(hours >= 7) & (hours < 12)] = 'london'
    result[(hours >= 12) & (hours < 17)] = 'new_york'
    return result


# ---------------------------------------------------------------------------
# Indicator 4: London Kill Zone Gate
# ---------------------------------------------------------------------------

def london_killzone_active(df, params):
    """Check whether each bar falls inside the London Kill Zone.

    The London Kill Zone (07:00-10:00 UTC) is the highest-probability
    window for GBPUSD sweep-fade setups.

    Args:
        df: DataFrame with DatetimeIndex (UTC).
        params: dict (unused).

    Returns:
        pd.Series of ``'active'`` or ``'inactive'`` per bar.
    """
    if df.empty:
        return pd.Series('inactive', index=df.index)

    hours = _extract_hours_series(df.index, df=df)
    if hours is None:
        return pd.Series('inactive', index=df.index)

    result = pd.Series('inactive', index=df.index)
    result[(hours >= 7) & (hours < 10)] = 'active'
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _asian_session_mask(index, start_hour, end_hour, df=None):
    """Return a boolean mask for bars that fall within the Asian session.

    Handles the overnight wrap (start_hour > end_hour, e.g. 22 > 6).
    Supports both DatetimeIndex and RangeIndex (with 'time' column fallback).
    """
    hours = _extract_hours_series(index, df=df)
    if hours is None:
        return np.zeros(len(index), dtype=bool)
    if start_hour > end_hour:
        # Overnight wrap — e.g. 22:00 to 06:00
        return (hours >= start_hour) | (hours < end_hour)
    return (hours >= start_hour) & (hours < end_hour)


def _last_completed_asian_range(df, start_hour, end_hour):
    """Find the high and low of the most recent *completed* Asian session.

    A session is considered complete once the first non-Asian bar appears
    after a run of Asian bars.  This prevents using an in-progress session
    whose range is still forming.

    Returns:
        (range_high, range_low) or (None, None) if no completed session
        exists in the data.
    """
    mask = np.asarray(_asian_session_mask(df.index, start_hour, end_hour, df=df))

    if not mask.any():
        return None, None

    # Walk backwards to find the end of the last completed Asian session.
    # The latest bar might still be inside the Asian session (session in
    # progress).  Skip those and look for the previous completed one.
    last_idx = len(mask) - 1

    # If the latest bar is Asian, skip the current (in-progress) session
    if mask[last_idx]:
        # Move backwards past the current Asian block
        i = last_idx
        while i >= 0 and mask[i]:
            i -= 1
        # Now i points to the first non-Asian bar before the current session.
        # Continue backward to find the previous completed Asian block.
        while i >= 0 and not mask[i]:
            i -= 1
        if i < 0:
            # No completed session found — fall back to current (partial)
            asian_bars = df.loc[mask]
            return float(asian_bars['high'].max()), float(asian_bars['low'].min())
        # i now points to the last bar of the previous completed Asian session
        end_pos = i
    else:
        # Latest bar is NOT Asian — walk back to find the last Asian bar
        i = last_idx
        while i >= 0 and not mask[i]:
            i -= 1
        if i < 0:
            return None, None
        end_pos = i

    # Collect all consecutive Asian bars ending at end_pos
    start_pos = end_pos
    while start_pos > 0 and mask[start_pos - 1]:
        start_pos -= 1

    session_bars = df.iloc[start_pos:end_pos + 1]
    if session_bars.empty:
        return None, None

    return float(session_bars['high'].max()), float(session_bars['low'].min())


def _rsi(close, period=14):
    """Compute RSI as a pandas Series (Wilder smoothing)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _bearish_rsi_divergence(df, rsi_vals, lookback):
    """Check for bearish RSI divergence in the look-back window.

    Bearish divergence: price made a higher high but RSI made a lower high.
    """
    if len(df) < lookback + 2 or len(rsi_vals) < lookback + 2:
        return False

    window = df.iloc[-lookback:]
    rsi_window = rsi_vals.iloc[-lookback:]
    prior = df.iloc[-(lookback + 1)]
    rsi_prior = rsi_vals.iloc[-(lookback + 1)]

    price_higher_high = float(window['high'].max()) > float(prior['high'])
    rsi_lower_high = float(rsi_window.max()) < float(rsi_prior)

    return price_higher_high and rsi_lower_high


def _bullish_rsi_divergence(df, rsi_vals, lookback):
    """Check for bullish RSI divergence in the look-back window.

    Bullish divergence: price made a lower low but RSI made a higher low.
    """
    if len(df) < lookback + 2 or len(rsi_vals) < lookback + 2:
        return False

    window = df.iloc[-lookback:]
    rsi_window = rsi_vals.iloc[-lookback:]
    prior = df.iloc[-(lookback + 1)]
    rsi_prior = rsi_vals.iloc[-(lookback + 1)]

    price_lower_low = float(window['low'].min()) < float(prior['low'])
    rsi_higher_low = float(rsi_window.min()) > float(rsi_prior)

    return price_lower_low and rsi_higher_low

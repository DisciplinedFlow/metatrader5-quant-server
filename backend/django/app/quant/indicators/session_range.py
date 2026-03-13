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
    """Calculate the Asian session high and low from the DataFrame.

    The Asian session spans from ``asian_start_hour`` (default 22:00 UTC)
    to ``asian_end_hour`` (default 06:00 UTC).  Because 22:00 > 06:00 the
    range wraps across midnight.

    Args:
        df: DataFrame with DatetimeIndex (UTC) and OHLCV columns.
        params: dict with optional keys ``asian_start_hour``, ``asian_end_hour``.

    Returns:
        Pipe-delimited string:
        ``"range_high=X.XXXXX|range_low=X.XXXXX|range_width=X.XXXXX"``
        or ``"neutral"`` when no Asian session data is available.
    """
    asian_start = params.get('asian_start_hour', 22)
    asian_end = params.get('asian_end_hour', 6)

    if df.empty or len(df) < 2:
        return 'neutral'

    asian_mask = _asian_session_mask(df.index, asian_start, asian_end, df=df)
    asian_bars = df.loc[asian_mask]

    if asian_bars.empty:
        return 'neutral'

    range_high = float(asian_bars['high'].max())
    range_low = float(asian_bars['low'].min())
    range_width = range_high - range_low

    return (
        f"range_high={range_high:.5f}"
        f"|range_low={range_low:.5f}"
        f"|range_width={range_width:.5f}"
    )


# ---------------------------------------------------------------------------
# Indicator 2: Sweep Fade Signal
# ---------------------------------------------------------------------------

def sweep_fade_signal(df, params):
    """Detect liquidity sweeps beyond the Asian range with a reversal back inside.

    Logic:
        1. Identify the most recent completed Asian session's high/low.
        2. Check if any of the last ``confirmation_candles`` wicked beyond
           the range by at least ``sweep_pips``.
        3. Check if the latest candle closed back inside the range.
        4. Optionally confirm with RSI divergence (higher-high price but
           lower-high RSI for bearish, or lower-low price but higher-low
           RSI for bullish).

    Args:
        df: DataFrame with DatetimeIndex (UTC) and OHLCV columns.
        params: dict with optional keys ``sweep_pips`` (default 3),
                ``confirmation_candles`` (default 3), ``pip_size``
                (default 0.0001), ``asian_start_hour``, ``asian_end_hour``,
                ``rsi_period`` (default 14).

    Returns:
        ``'bullish_sweep'``, ``'bearish_sweep'``, or ``'neutral'``.
    """
    sweep_pips = params.get('sweep_pips', 3)
    confirmation_candles = params.get('confirmation_candles', 3)
    pip_size = params.get('pip_size', 0.0001)
    asian_start = params.get('asian_start_hour', 22)
    asian_end = params.get('asian_end_hour', 6)
    rsi_period = params.get('rsi_period', 14)

    sweep_distance = sweep_pips * pip_size

    if df.empty or len(df) < confirmation_candles + 1:
        return 'neutral'

    # --- Resolve the most recent *completed* Asian session ----------------
    range_high, range_low = _last_completed_asian_range(
        df, asian_start, asian_end,
    )
    if range_high is None or range_low is None:
        return 'neutral'

    # --- Check sweep & close-back within the look-back window -------------
    window = df.iloc[-confirmation_candles:]
    latest = df.iloc[-1]

    swept_high = float(window['high'].max()) > range_high + sweep_distance
    swept_low = float(window['low'].min()) < range_low - sweep_distance

    closed_inside = range_low <= float(latest['close']) <= range_high

    if not closed_inside:
        return 'neutral'

    # --- Determine direction and apply RSI divergence filter ---------------
    rsi_vals = _rsi(df['close'], rsi_period)

    if swept_high and not swept_low:
        # Bearish sweep fade — price took the high then reversed
        if _bearish_rsi_divergence(df, rsi_vals, confirmation_candles):
            return 'bearish_sweep'
        # Even without divergence the structure is valid
        return 'bearish_sweep'

    if swept_low and not swept_high:
        # Bullish sweep fade — price took the low then reversed
        if _bullish_rsi_divergence(df, rsi_vals, confirmation_candles):
            return 'bullish_sweep'
        return 'bullish_sweep'

    # Both sides swept (whipsaw) — ambiguous, stay flat
    return 'neutral'


# ---------------------------------------------------------------------------
# Indicator 3: Session Filter
# ---------------------------------------------------------------------------

def session_filter(df, params):
    """Return the current trading session based on the last candle's timestamp.

    Sessions (UTC):
        asian       22:00 - 06:00  (wraps midnight)
        london      07:00 - 12:00
        new_york    12:00 - 17:00
        off_hours   17:00 - 22:00

    Args:
        df: DataFrame with DatetimeIndex (UTC).
        params: dict (unused, kept for interface consistency).

    Returns:
        ``'asian'``, ``'london'``, ``'new_york'``, or ``'off_hours'``.
    """
    if df.empty:
        return 'off_hours'

    hour = _extract_hour(df)
    if hour is None:
        return 'off_hours'

    if hour >= 22 or hour < 6:
        return 'asian'
    if 7 <= hour < 12:
        return 'london'
    if 12 <= hour < 17:
        return 'new_york'
    return 'off_hours'


# ---------------------------------------------------------------------------
# Indicator 4: London Kill Zone Gate
# ---------------------------------------------------------------------------

def london_killzone_active(df, params):
    """Check whether the latest candle falls inside the London Kill Zone.

    The London Kill Zone (07:00-10:00 UTC) is the highest-probability
    window for GBPUSD sweep-fade setups.

    Args:
        df: DataFrame with DatetimeIndex (UTC).
        params: dict (unused).

    Returns:
        ``'active'`` or ``'inactive'``.
    """
    if df.empty:
        return 'inactive'

    hour = _extract_hour(df)
    if hour is None:
        return 'inactive'
    if 7 <= hour < 10:
        return 'active'
    return 'inactive'


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

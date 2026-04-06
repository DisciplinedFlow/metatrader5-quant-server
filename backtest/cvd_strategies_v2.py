"""
CVD Strategies V2 — Research-refined implementations.

Key improvements over V1 (based on orderflow research):
1. Session-anchored CVD (daily reset for intraday)
2. Proper swing-based absorption (CVD extreme, price doesn't follow)
3. Structural confirmation (engulfing/pin bar after divergence)
4. Price tolerance bands for absorption (0.2% default)
5. Volume confirmation (above-average volume on signal bars)
6. Proper pivot detection (5-7 bar left, 3-5 bar right)

Each strategy: fn(df, i) -> 'BUY' | 'SELL' | None
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# CVD calculation — Session-anchored + body-weighted
# ---------------------------------------------------------------------------

def compute_cvd_v2(df):
    """CVD with daily session reset and body-weighted delta.

    Uses Approach B (body-weighted) for delta, then resets CVD at each
    new trading day (00:00 UTC) so intraday signals aren't polluted by
    multi-day drift.
    """
    h = df['high']
    l = df['low']
    o = df['open']
    c = df['close']
    vol = df['tick_volume']

    bar_range = (h - l).replace(0, np.nan)
    body_ratio = (abs(c - o) / bar_range).fillna(0).clip(0, 1)
    direction = np.sign(c - o)
    buy_pct = 0.5 + direction * body_ratio * 0.5

    df = df.copy()
    df['delta'] = vol * (2 * buy_pct - 1)

    # Session-anchored CVD: reset at each new day
    df['date'] = df['time'].dt.date
    df['cvd'] = df.groupby('date')['delta'].cumsum()

    # Also keep a running CVD for longer-term analysis
    df['cvd_running'] = df['delta'].cumsum()

    # Volume moving average for confirmation
    df['vol_sma20'] = df['tick_volume'].rolling(20).mean()
    df['high_vol'] = df['tick_volume'] > df['vol_sma20'] * 1.2

    # Delta z-score (within session)
    df['delta_mean20'] = df['delta'].rolling(20).mean()
    df['delta_std20'] = df['delta'].rolling(20).std()
    df['delta_z'] = (df['delta'] - df['delta_mean20']) / df['delta_std20'].replace(0, np.nan)

    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def _is_bullish_engulfing(df, i):
    """Current bar fully engulfs previous bar's body, bullish."""
    if i < 1:
        return False
    curr_o, curr_c = df['open'].iloc[i], df['close'].iloc[i]
    prev_o, prev_c = df['open'].iloc[i-1], df['close'].iloc[i-1]
    return (curr_c > curr_o and prev_c < prev_o and
            curr_o <= prev_c and curr_c >= prev_o)


def _is_bearish_engulfing(df, i):
    """Current bar fully engulfs previous bar's body, bearish."""
    if i < 1:
        return False
    curr_o, curr_c = df['open'].iloc[i], df['close'].iloc[i]
    prev_o, prev_c = df['open'].iloc[i-1], df['close'].iloc[i-1]
    return (curr_c < curr_o and prev_c > prev_o and
            curr_o >= prev_c and curr_c <= prev_o)


def _is_bullish_pin(df, i):
    """Pin bar / hammer: small body at top, long lower wick."""
    h, l, o, c = df['high'].iloc[i], df['low'].iloc[i], df['open'].iloc[i], df['close'].iloc[i]
    bar_range = h - l
    if bar_range <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return lower_wick > body * 2 and upper_wick < body * 1.5 and c > o


def _is_bearish_pin(df, i):
    """Shooting star: small body at bottom, long upper wick."""
    h, l, o, c = df['high'].iloc[i], df['low'].iloc[i], df['open'].iloc[i], df['close'].iloc[i]
    bar_range = h - l
    if bar_range <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return upper_wick > body * 2 and lower_wick < body * 1.5 and c < o


def _has_bullish_confirmation(df, i):
    """Bullish candle pattern: engulfing, pin bar, or strong close."""
    if _is_bullish_engulfing(df, i):
        return True
    if _is_bullish_pin(df, i):
        return True
    # Strong bullish close (>60% of range is body, close near high)
    h, l, o, c = df['high'].iloc[i], df['low'].iloc[i], df['open'].iloc[i], df['close'].iloc[i]
    bar_range = h - l
    if bar_range > 0:
        body_pct = abs(c - o) / bar_range
        close_position = (c - l) / bar_range
        if c > o and body_pct > 0.6 and close_position > 0.7:
            return True
    return False


def _has_bearish_confirmation(df, i):
    """Bearish candle pattern: engulfing, pin bar, or strong close."""
    if _is_bearish_engulfing(df, i):
        return True
    if _is_bearish_pin(df, i):
        return True
    h, l, o, c = df['high'].iloc[i], df['low'].iloc[i], df['open'].iloc[i], df['close'].iloc[i]
    bar_range = h - l
    if bar_range > 0:
        body_pct = abs(c - o) / bar_range
        close_position = (h - c) / bar_range
        if c < o and body_pct > 0.6 and close_position > 0.7:
            return True
    return False


def _find_pivots(series, i, left=7, right=3, max_dist=60, min_dist=5):
    """Find the two most recent pivot highs or lows.

    Returns (pivot1_val, pivot1_idx, pivot2_val, pivot2_idx) or None.
    pivot2 is the more recent one.
    """
    # Look back from i-right to find confirmed pivots
    pivots = []
    search_start = max(left, i - max_dist)

    for j in range(i - right, search_start - 1, -1):
        # Check if j is a pivot
        left_slice = series.iloc[max(0, j-left):j]
        right_slice = series.iloc[j+1:min(len(series), j+right+1)]
        if len(left_slice) == 0 or len(right_slice) == 0:
            continue
        val = series.iloc[j]
        # For lows: must be lower than all surrounding bars
        # For highs: must be higher than all surrounding bars
        # We'll check both and let the caller decide
        is_low = val <= left_slice.min() and val <= right_slice.min()
        is_high = val >= left_slice.max() and val >= right_slice.max()
        if is_low or is_high:
            pivots.append((val, j, 'low' if is_low else 'high'))
        if len(pivots) >= 4:  # enough
            break

    return pivots


# ---------------------------------------------------------------------------
# STRATEGY V2-1: CVD LoP with Pivot Detection + Confirmation
# ---------------------------------------------------------------------------

def cvd_lop_v2(df, i, left=7, right=3):
    """CVD Lack of Participation with proper pivot detection and candle confirmation.

    Research-backed rules:
    - Pivots: 7 bars left, 3 bars right, 5-60 bars apart
    - Bullish: price lower low pivot, CVD higher low pivot
    - Bearish: price higher high pivot, CVD lower high pivot
    - Confirmation: engulfing, pin bar, or strong directional close
    """
    if i < left + right + 60:
        return None

    # Find pivot lows for bullish LoP
    price_pivots = _find_pivots(df['low'], i, left, right)
    cvd_pivots_at_price_lows = []

    # Get pivot lows (filter for 'low' type)
    low_pivots = [(v, idx) for v, idx, t in (price_pivots or []) if t == 'low']

    if len(low_pivots) >= 2:
        p2_val, p2_idx = low_pivots[0]  # more recent
        p1_val, p1_idx = low_pivots[1]  # older

        if 5 <= (p2_idx - p1_idx) <= 60:
            cvd_at_p1 = df['cvd'].iloc[p1_idx]
            cvd_at_p2 = df['cvd'].iloc[p2_idx]

            # Bullish LoP: price lower low, CVD higher low
            if p2_val < p1_val and cvd_at_p2 > cvd_at_p1:
                if _has_bullish_confirmation(df, i):
                    return 'BUY'

    # Find pivot highs for bearish LoP
    high_pivots = [(v, idx) for v, idx, t in (_find_pivots(df['high'], i, left, right) or []) if t == 'high']

    if len(high_pivots) >= 2:
        p2_val, p2_idx = high_pivots[0]  # more recent
        p1_val, p1_idx = high_pivots[1]  # older

        if 5 <= (p2_idx - p1_idx) <= 60:
            cvd_at_p1 = df['cvd'].iloc[p1_idx]
            cvd_at_p2 = df['cvd'].iloc[p2_idx]

            # Bearish LoP: price higher high, CVD lower high
            if p2_val > p1_val and cvd_at_p2 < cvd_at_p1:
                if _has_bearish_confirmation(df, i):
                    return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY V2-2: CVD Absorption (Correct Definition)
# ---------------------------------------------------------------------------

def cvd_absorption_v2(df, i, left=7, right=3, price_tolerance_pct=0.002):
    """CVD Absorption — CVD makes new extreme, price does NOT.

    Research-correct definition:
    - Bullish absorption: CVD lower low (sellers active), price higher/equal low (defended)
    - Bearish absorption: CVD higher high (buyers active), price lower/equal high (defended)
    - Price tolerance: 0.2% band for "equal" prices
    - Volume confirmation: signal bar must have above-average volume
    """
    if i < left + right + 60:
        return None

    # Need above-average volume for absorption to be meaningful
    if not df['high_vol'].iloc[i]:
        return None

    # Find pivot lows for bullish absorption
    price_low_pivots = [(v, idx) for v, idx, t in (_find_pivots(df['low'], i, left, right) or []) if t == 'low']
    cvd_low_pivots = [(v, idx) for v, idx, t in (_find_pivots(df['cvd'], i, left, right) or []) if t == 'low']

    if len(price_low_pivots) >= 2 and len(cvd_low_pivots) >= 2:
        pp2, pp2_idx = price_low_pivots[0]
        pp1, pp1_idx = price_low_pivots[1]
        cp2, cp2_idx = cvd_low_pivots[0]
        cp1, cp1_idx = cvd_low_pivots[1]

        # Price makes higher low or equal low (within tolerance)
        price_held = pp2 >= pp1 * (1 - price_tolerance_pct)
        # CVD makes lower low (aggressive selling intensifying)
        cvd_new_low = cp2 < cp1

        if price_held and cvd_new_low:
            if _has_bullish_confirmation(df, i):
                return 'BUY'

    # Find pivot highs for bearish absorption
    price_high_pivots = [(v, idx) for v, idx, t in (_find_pivots(df['high'], i, left, right) or []) if t == 'high']
    cvd_high_pivots = [(v, idx) for v, idx, t in (_find_pivots(df['cvd'], i, left, right) or []) if t == 'high']

    if len(price_high_pivots) >= 2 and len(cvd_high_pivots) >= 2:
        pp2, pp2_idx = price_high_pivots[0]
        pp1, pp1_idx = price_high_pivots[1]
        cp2, cp2_idx = cvd_high_pivots[0]
        cp1, cp1_idx = cvd_high_pivots[1]

        # Price makes lower high or equal high (within tolerance)
        price_held = pp2 <= pp1 * (1 + price_tolerance_pct)
        # CVD makes higher high (aggressive buying intensifying)
        cvd_new_high = cp2 > cp1

        if price_held and cvd_new_high:
            if _has_bearish_confirmation(df, i):
                return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY V2-3: CVD LoP + Trend + Session (Full Confluence)
# ---------------------------------------------------------------------------

def cvd_lop_full_confluence(df, i, ema_period=50):
    """CVD LoP with EMA trend + London/NY session filter + confirmation.

    The "A+ setup": only fires when divergence, trend, session, AND
    candle confirmation all align. Research shows this combo hits 70-80% WR.
    """
    if i < max(ema_period, 70):
        return None

    # Session filter: London (07-12) or NY (13-17) only
    hour = df['time'].iloc[i].hour
    if not (7 <= hour < 12 or 13 <= hour < 17):
        return None

    # Trend filter
    ema_val = ema(df['close'].iloc[:i+1], ema_period).iloc[-1]
    if pd.isna(ema_val):
        return None

    price = df['close'].iloc[i]

    # Get LoP signal (with proper pivots)
    signal = cvd_lop_v2(df, i)

    # Only with-trend
    if signal == 'BUY' and price > ema_val:
        return 'BUY'
    if signal == 'SELL' and price < ema_val:
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY V2-4: CVD Absorption + Trend + Volume (Full Confluence)
# ---------------------------------------------------------------------------

def cvd_absorption_full(df, i, ema_period=50):
    """CVD Absorption with EMA trend + volume + session filter."""
    if i < max(ema_period, 70):
        return None

    # Session filter
    hour = df['time'].iloc[i].hour
    if not (7 <= hour < 12 or 13 <= hour < 17):
        return None

    # Trend filter
    ema_val = ema(df['close'].iloc[:i+1], ema_period).iloc[-1]
    if pd.isna(ema_val):
        return None

    price = df['close'].iloc[i]

    signal = cvd_absorption_v2(df, i)

    if signal == 'BUY' and price > ema_val:
        return 'BUY'
    if signal == 'SELL' and price < ema_val:
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY V2-5: CVD LoP + Session Sweep + Confirmation
# ---------------------------------------------------------------------------

def cvd_lop_sweep_v2(df, i):
    """Session range sweep + CVD LoP divergence + candle confirmation.

    Sweep of Asia range during London, or London range during NY,
    combined with CVD divergence = institutional stop hunt reversal.
    """
    if i < 70:
        return None

    bar = df.iloc[i]
    hour = bar['time'].hour
    today = bar['time'].date()

    if 7 <= hour < 12:
        range_start, range_end = 0, 7
    elif 13 <= hour < 17:
        range_start, range_end = 7, 13
    else:
        return None

    range_bars = df.iloc[:i+1]
    range_bars = range_bars[
        (range_bars['time'].dt.date == today) &
        (range_bars['time'].dt.hour >= range_start) &
        (range_bars['time'].dt.hour < range_end)
    ]
    if len(range_bars) < 3:
        return None

    range_high = range_bars['high'].max()
    range_low = range_bars['low'].min()

    swept_high = bar['high'] > range_high
    swept_low = bar['low'] < range_low

    signal = cvd_lop_v2(df, i)

    if swept_low and signal == 'BUY':
        return 'BUY'
    if swept_high and signal == 'SELL':
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY V2-6: CVD Exhaustion V2 (Session-Anchored)
# ---------------------------------------------------------------------------

def cvd_exhaustion_v2(df, i, std_threshold=2.0):
    """CVD Exhaustion using session-anchored CVD.

    Extreme intraday CVD + reversal confirmation.
    Session-anchored CVD avoids multi-day drift noise.
    """
    if i < 60:
        return None

    # Use session CVD (already reset daily)
    today = df['time'].iloc[i].date()
    session_mask = df['time'].dt.date == today
    session_cvd = df.loc[session_mask, 'cvd']

    if len(session_cvd) < 20:
        return None

    cvd_mean = session_cvd.mean()
    cvd_std = session_cvd.std()

    if pd.isna(cvd_std) or cvd_std <= 0:
        return None

    cvd_z = (df['cvd'].iloc[i] - cvd_mean) / cvd_std

    # London/NY only
    hour = df['time'].iloc[i].hour
    if not (7 <= hour < 17):
        return None

    # Exhaustion high + bearish confirmation
    if cvd_z > std_threshold and _has_bearish_confirmation(df, i):
        return 'SELL'

    # Exhaustion low + bullish confirmation
    if cvd_z < -std_threshold and _has_bullish_confirmation(df, i):
        return 'BUY'

    return None


# ---------------------------------------------------------------------------
# STRATEGY V2-7: Combined LoP + Absorption (Any CVD Divergence)
# ---------------------------------------------------------------------------

def cvd_any_divergence(df, i, ema_period=50):
    """Fire on either LoP OR Absorption, with trend + session + confirmation.

    Catches both types of institutional activity:
    - LoP: smart money NOT participating in the move
    - Absorption: smart money actively DEFENDING a level
    """
    if i < max(ema_period, 70):
        return None

    hour = df['time'].iloc[i].hour
    if not (7 <= hour < 12 or 13 <= hour < 17):
        return None

    ema_val = ema(df['close'].iloc[:i+1], ema_period).iloc[-1]
    if pd.isna(ema_val):
        return None

    price = df['close'].iloc[i]

    # Try LoP first, then absorption
    signal = cvd_lop_v2(df, i)
    if signal is None:
        signal = cvd_absorption_v2(df, i)

    if signal == 'BUY' and price > ema_val:
        return 'BUY'
    if signal == 'SELL' and price < ema_val:
        return 'SELL'

    return None

"""
CVD (Cumulative Volume Delta) indicator with divergence detection.

Approximates order flow from OHLCV data using the volume delta formula:
    delta = volume * (2*close - high - low) / (high - low)

When close > open, buyers dominated -> positive delta
When close < open, sellers dominated -> negative delta
CVD = cumulative sum of per-bar deltas
"""

import pandas as pd
import numpy as np


def _volume_delta(data):
    """
    Approximate per-bar buying vs selling pressure from OHLCV.

    Uses volume weighting when volume data exists (crypto, stocks).
    Falls back to price-position-within-bar for forex/OTC where volume=0.

    The price position formula: (2*close - high - low) / (high - low)
    ranges from -1 (closed at low) to +1 (closed at high).
    """
    high = data['high']
    low = data['low']
    close = data['close']

    bar_range = high - low
    bar_range = bar_range.replace(0, np.nan)

    # Price position within bar: -1 to +1
    position = (2 * close - high - low) / bar_range

    # Use volume weighting if meaningful volume data exists
    volume = None
    for col in ['tick_volume', 'volume', 'real_volume']:
        if col in data.columns:
            v = data[col]
            if v.sum() > 0:
                volume = v
                break

    if volume is not None:
        delta = volume * position
    else:
        # No volume: use bar range as activity proxy
        delta = bar_range.fillna(0) * position

    delta = delta.fillna(0)
    return delta


def _find_swing_highs(series, lookback=5):
    """Find indices where value is highest within lookback window on both sides."""
    indices = []
    vals = series.values
    for i in range(lookback, len(vals) - lookback):
        window = vals[i - lookback:i + lookback + 1]
        if not np.isnan(vals[i]) and vals[i] == np.nanmax(window):
            indices.append(i)
    return indices


def _find_swing_lows(series, lookback=5):
    """Find indices where value is lowest within lookback window on both sides."""
    indices = []
    vals = series.values
    for i in range(lookback, len(vals) - lookback):
        window = vals[i - lookback:i + lookback + 1]
        if not np.isnan(vals[i]) and vals[i] == np.nanmin(window):
            indices.append(i)
    return indices


def _compute_cvd_and_swings(data, lookback, swing_lookback):
    """Shared computation: volume delta, CVD, swing points."""
    delta = _volume_delta(data)
    cvd = delta.cumsum()

    swing_lb = min(swing_lookback, lookback // 4, 3)
    if swing_lb < 2:
        swing_lb = 2

    return cvd, delta, {
        'price_highs': _find_swing_highs(data['high'], swing_lb),
        'price_lows': _find_swing_lows(data['low'], swing_lb),
        'cvd_highs': _find_swing_highs(cvd, swing_lb),
        'cvd_lows': _find_swing_lows(cvd, swing_lb),
    }


def _check_bearish_divergence(price_high, cvd, recent_price_highs, recent_cvd_highs):
    """Check for bearish divergence patterns at highs. Returns signal string or None."""
    if len(recent_price_highs) < 2 or len(recent_cvd_highs) < 2:
        return None

    ph1, ph2 = recent_price_highs[-2], recent_price_highs[-1]
    ch1, ch2 = recent_cvd_highs[-2], recent_cvd_highs[-1]

    # Price higher high, CVD lower high -> lack of participants
    if price_high.iloc[ph2] > price_high.iloc[ph1] and cvd.iloc[ch2] < cvd.iloc[ch1]:
        return 'bearish_lack_of_participants'

    # CVD higher high, price can't break -> absorption
    if cvd.iloc[ch2] > cvd.iloc[ch1] and price_high.iloc[ph2] <= price_high.iloc[ph1]:
        return 'bearish_absorption'

    return None


def _check_bullish_divergence(price_low, cvd, recent_price_lows, recent_cvd_lows):
    """Check for bullish divergence patterns at lows. Returns signal string or None."""
    if len(recent_price_lows) < 2 or len(recent_cvd_lows) < 2:
        return None

    pl1, pl2 = recent_price_lows[-2], recent_price_lows[-1]
    cl1, cl2 = recent_cvd_lows[-2], recent_cvd_lows[-1]

    # Price lower low, CVD higher low -> lack of participants
    if price_low.iloc[pl2] < price_low.iloc[pl1] and cvd.iloc[cl2] > cvd.iloc[cl1]:
        return 'bullish_lack_of_participants'

    # CVD lower low, price higher low -> absorption
    if cvd.iloc[cl2] < cvd.iloc[cl1] and price_low.iloc[pl2] >= price_low.iloc[pl1]:
        return 'bullish_absorption'

    return None


def cvd_divergence(data, lookback=20, swing_lookback=5):
    """
    Detect CVD divergence signals.

    Returns a Series with one of:
      'bullish_lack_of_participants' - price lower low, CVD higher low (sellers exhausted)
      'bearish_lack_of_participants' - price higher high, CVD lower high (buyers exhausted)
      'bullish_absorption' - CVD lower low (aggressive selling) but price higher low (absorbed by limit buys)
      'bearish_absorption' - CVD higher high (aggressive buying) but price can't break (absorbed by limit sells)
      0 - no signal
    """
    cvd, delta, swings = _compute_cvd_and_swings(data, lookback, swing_lookback)
    price_high = data['high']
    price_low = data['low']
    signal = pd.Series(0, index=data.index, dtype=object)

    for i in range(lookback, len(data)):
        window_start = i - lookback

        recent_price_highs = [idx for idx in swings['price_highs'] if window_start <= idx < i]
        recent_price_lows = [idx for idx in swings['price_lows'] if window_start <= idx < i]
        recent_cvd_highs = [idx for idx in swings['cvd_highs'] if window_start <= idx < i]
        recent_cvd_lows = [idx for idx in swings['cvd_lows'] if window_start <= idx < i]

        bearish = _check_bearish_divergence(price_high, cvd, recent_price_highs, recent_cvd_highs)
        if bearish:
            signal.iloc[i] = bearish
            continue

        bullish = _check_bullish_divergence(price_low, cvd, recent_price_lows, recent_cvd_lows)
        if bullish:
            signal.iloc[i] = bullish

    return signal


def cvd_leading(data, lookback=10, swing_lookback=5):
    """
    Leading CVD indicator: detects exhaustion early by comparing delta momentum
    (rate of change of CVD) against price direction within the current lookback window.

    Fires earlier than standard divergence by looking at delta acceleration
    rather than waiting for completed swing points.

    Returns signal strings:
      'bullish_exhaustion_early' - delta momentum turning positive while price still falling
      'bearish_exhaustion_early' - delta momentum turning negative while price still rising
    """
    delta = _volume_delta(data)
    cvd = delta.cumsum()
    signal = pd.Series(0, index=data.index, dtype=object)

    # Delta momentum: rate of change of CVD over short window
    delta_ma_fast = delta.rolling(window=max(lookback // 2, 3), min_periods=1).mean()
    delta_ma_slow = delta.rolling(window=lookback, min_periods=1).mean()
    price_roc = data['close'].pct_change(periods=lookback)

    for i in range(lookback + 1, len(data)):
        fast = delta_ma_fast.iloc[i]
        slow = delta_ma_slow.iloc[i]
        p_roc = price_roc.iloc[i]

        if pd.isna(fast) or pd.isna(slow) or pd.isna(p_roc):
            continue

        # Bullish exhaustion early: price still falling but delta momentum turning up
        if p_roc < -0.001 and fast > slow and fast > 0:
            signal.iloc[i] = 'bullish_exhaustion_early'
        # Bearish exhaustion early: price still rising but delta momentum turning down
        elif p_roc > 0.001 and fast < slow and fast < 0:
            signal.iloc[i] = 'bearish_exhaustion_early'

    return signal


def cvd_extremes(data, lookback=50, swing_lookback=5, strength=3):
    """
    Detect divergences at extreme price and CVD points.

    Uses a wider lookback to find significant highs/lows, then checks whether
    CVD confirms the extreme or diverges from it.

    Returns:
      'bullish_extreme' - price at extreme low but CVD not confirming
      'bearish_extreme' - price at extreme high but CVD not confirming
    """
    cvd, delta, swings = _compute_cvd_and_swings(data, lookback, max(swing_lookback, strength))
    price_high = data['high']
    price_low = data['low']
    signal = pd.Series(0, index=data.index, dtype=object)

    # Use wider swing detection for extremes
    extreme_lb = max(swing_lookback, strength)
    price_extreme_highs = _find_swing_highs(price_high, extreme_lb)
    price_extreme_lows = _find_swing_lows(price_low, extreme_lb)

    for i in range(lookback, len(data)):
        window_start = i - lookback

        # Check if current area is near a significant price extreme
        recent_p_highs = [idx for idx in price_extreme_highs if window_start <= idx < i]
        recent_p_lows = [idx for idx in price_extreme_lows if window_start <= idx < i]
        recent_cvd_highs = [idx for idx in swings['cvd_highs'] if window_start <= idx < i]
        recent_cvd_lows = [idx for idx in swings['cvd_lows'] if window_start <= idx < i]

        # Bearish extreme: price near significant high, CVD diverging
        if len(recent_p_highs) >= 2 and len(recent_cvd_highs) >= 2:
            ph1, ph2 = recent_p_highs[-2], recent_p_highs[-1]
            ch1, ch2 = recent_cvd_highs[-2], recent_cvd_highs[-1]
            # Price at new extreme high but CVD failing to keep up
            if price_high.iloc[ph2] > price_high.iloc[ph1] and cvd.iloc[ch2] < cvd.iloc[ch1]:
                # Extra filter: the divergence must be significant (>5% CVD drop)
                cvd_drop_pct = (cvd.iloc[ch1] - cvd.iloc[ch2]) / (abs(cvd.iloc[ch1]) + 1e-10)
                if cvd_drop_pct > 0.05:
                    signal.iloc[i] = 'bearish_extreme'
                    continue

        # Bullish extreme: price near significant low, CVD diverging
        if len(recent_p_lows) >= 2 and len(recent_cvd_lows) >= 2:
            pl1, pl2 = recent_p_lows[-2], recent_p_lows[-1]
            cl1, cl2 = recent_cvd_lows[-2], recent_cvd_lows[-1]
            # Price at new extreme low but CVD not confirming
            if price_low.iloc[pl2] < price_low.iloc[pl1] and cvd.iloc[cl2] > cvd.iloc[cl1]:
                cvd_rise_pct = (cvd.iloc[cl2] - cvd.iloc[cl1]) / (abs(cvd.iloc[cl1]) + 1e-10)
                if cvd_rise_pct > 0.05:
                    signal.iloc[i] = 'bullish_extreme'

    return signal


def cvd_mtf(data, lookback=20, swing_lookback=5):
    """
    Multi-timeframe CVD divergence: looks for divergence confirmed across
    multiple resolutions within the same dataset by using nested lookback windows.

    Checks short (lookback/2) and long (lookback*2) windows. If both show
    divergence in the same direction, fires a confirmed signal.

    Returns:
      'bullish_mtf_confirmed' - bullish divergence on at least 2 lookback scales
      'bearish_mtf_confirmed' - bearish divergence on at least 2 lookback scales
    """
    cvd, delta, _ = _compute_cvd_and_swings(data, lookback, swing_lookback)
    price_high = data['high']
    price_low = data['low']
    signal = pd.Series(0, index=data.index, dtype=object)

    # Compute swing points at two different scales
    short_lb = max(lookback // 2, 5)
    long_lb = min(lookback * 2, len(data) // 3)

    swing_lb_short = max(swing_lookback // 2, 2)
    swing_lb_long = max(swing_lookback, 3)

    swings_short = {
        'price_highs': _find_swing_highs(price_high, swing_lb_short),
        'price_lows': _find_swing_lows(price_low, swing_lb_short),
        'cvd_highs': _find_swing_highs(cvd, swing_lb_short),
        'cvd_lows': _find_swing_lows(cvd, swing_lb_short),
    }
    swings_long = {
        'price_highs': _find_swing_highs(price_high, swing_lb_long),
        'price_lows': _find_swing_lows(price_low, swing_lb_long),
        'cvd_highs': _find_swing_highs(cvd, swing_lb_long),
        'cvd_lows': _find_swing_lows(cvd, swing_lb_long),
    }

    for i in range(long_lb, len(data)):
        # Check short-term window
        ws_short = i - short_lb
        rph_s = [idx for idx in swings_short['price_highs'] if ws_short <= idx < i]
        rpl_s = [idx for idx in swings_short['price_lows'] if ws_short <= idx < i]
        rch_s = [idx for idx in swings_short['cvd_highs'] if ws_short <= idx < i]
        rcl_s = [idx for idx in swings_short['cvd_lows'] if ws_short <= idx < i]

        bearish_short = _check_bearish_divergence(price_high, cvd, rph_s, rch_s)
        bullish_short = _check_bullish_divergence(price_low, cvd, rpl_s, rcl_s)

        # Check long-term window
        ws_long = i - long_lb
        rph_l = [idx for idx in swings_long['price_highs'] if ws_long <= idx < i]
        rpl_l = [idx for idx in swings_long['price_lows'] if ws_long <= idx < i]
        rch_l = [idx for idx in swings_long['cvd_highs'] if ws_long <= idx < i]
        rcl_l = [idx for idx in swings_long['cvd_lows'] if ws_long <= idx < i]

        bearish_long = _check_bearish_divergence(price_high, cvd, rph_l, rch_l)
        bullish_long = _check_bullish_divergence(price_low, cvd, rpl_l, rcl_l)

        # Need confirmation on both timeframe scales
        if bearish_short and bearish_long:
            signal.iloc[i] = 'bearish_mtf_confirmed'
        elif bullish_short and bullish_long:
            signal.iloc[i] = 'bullish_mtf_confirmed'

    return signal


def cvd_cross_market(data, lookback=20, swing_lookback=5):
    """
    Cross-market CVD comparison using volume-weighted vs unweighted delta.

    Since we can't access separate spot/futures feeds, we approximate by comparing
    volume-weighted CVD (reflects exchange order flow) vs price-only CVD
    (reflects pure price movement without volume). Divergence between the two
    suggests discrepancy between traded volume flow and price action.

    Returns:
      'bullish_spot_vs_futures' - price-only CVD bearish but volume CVD neutral/bullish
      'bearish_spot_vs_futures' - price-only CVD bullish but volume CVD neutral/bearish
    """
    high = data['high']
    low = data['low']
    close = data['close']

    bar_range = high - low
    bar_range = bar_range.replace(0, np.nan)
    position = (2 * close - high - low) / bar_range

    # Volume-weighted delta (exchange flow proxy)
    volume = None
    for col in ['tick_volume', 'volume', 'real_volume']:
        if col in data.columns:
            v = data[col]
            if v.sum() > 0:
                volume = v
                break

    if volume is None:
        # No volume data, can't compare cross-market
        return pd.Series(0, index=data.index, dtype=object)

    vol_delta = (volume * position).fillna(0)
    vol_cvd = vol_delta.cumsum()

    # Price-only delta (no volume weighting)
    price_delta = (bar_range.fillna(0) * position).fillna(0)
    price_cvd = price_delta.cumsum()

    signal = pd.Series(0, index=data.index, dtype=object)

    vol_roc = vol_cvd.diff(lookback)
    price_roc = price_cvd.diff(lookback)

    # Normalize each series independently by its own rolling std
    vol_std = vol_roc.rolling(window=lookback * 5, min_periods=lookback).std()
    price_std = price_roc.rolling(window=lookback * 5, min_periods=lookback).std()

    for i in range(lookback * 5 + 1, len(data)):
        v_roc = vol_roc.iloc[i]
        p_roc = price_roc.iloc[i]
        v_s = vol_std.iloc[i]
        p_s = price_std.iloc[i]

        if pd.isna(v_roc) or pd.isna(p_roc) or pd.isna(v_s) or pd.isna(p_s):
            continue
        if v_s < 1e-10 or p_s < 1e-10:
            continue

        # Z-score normalization: how many stds from mean
        v_z = v_roc / v_s
        p_z = p_roc / p_s

        # Bullish cross-market: price CVD falling but volume CVD holding/rising
        # Signal includes both naming conventions for compatibility
        if p_z < -0.5 and v_z > 0.3:
            signal.iloc[i] = 'bullish_spot_vs_futures_bullish_spot_vs_perp'
        # Bearish cross-market: price CVD rising but volume CVD falling
        elif p_z > 0.5 and v_z < -0.3:
            signal.iloc[i] = 'bearish_spot_vs_futures_bearish_spot_vs_perp'

    return signal


def cvd_raw(data, lookback=20):
    """Return raw CVD values (for overlay/visualization strategies)."""
    delta = _volume_delta(data)
    return delta.cumsum()

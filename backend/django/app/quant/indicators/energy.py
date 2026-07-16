"""Energy / Crude Oil trading indicators.

Optimized for UKOUSDft (Brent), USOUSD (WTI), and NG-C (Natural Gas).
Energy markets exhibit strong trends, high volatility, and nearly 24-hour
trading (23:00-22:00 UTC).  These indicators cover trend following, range
detection, range trading, breakout detection, Keltner Channel positioning,
and the Brent-WTI spread.

Indicators:
    energy_trend_follow  - EMA alignment + MACD confirmation
    energy_range_detect  - ATR compression + Bollinger Band width
    energy_range_trade   - Support/resistance range-bound signals
    energy_breakout      - Keltner Channel breakout with volume confirmation
    keltner_channel      - Normalized position within the Keltner Channel
    brent_wti_spread     - Brent-WTI spread relative value signal
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atr(df, period):
    """Average True Range (Wilder-smoothed via EWM)."""
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Indicator 1: energy_trend_follow
# ---------------------------------------------------------------------------

def energy_trend_follow(df, params=None):
    """Trend following using triple-EMA alignment + MACD histogram confirmation.

    Energy markets often sustain strong directional moves driven by supply /
    demand shifts.  This indicator detects those trends early and grades their
    strength.

    Params:
        fast_ema    (int):   Fast EMA period   (default 8)
        slow_ema    (int):   Medium EMA period  (default 21)
        trend_ema   (int):   Slow EMA period    (default 50)
        macd_fast   (int):   MACD fast EMA      (default 12)
        macd_slow   (int):   MACD slow EMA      (default 26)
        macd_signal (int):   MACD signal EMA    (default 9)

    Returns:
        pd.Series of signal strings per bar:
             'strong_long'  - stacked bullish EMAs + MACD histogram > 0 and growing
             'long'         - stacked bullish EMAs + MACD histogram > 0
             'strong_short' - stacked bearish EMAs + MACD histogram < 0 and shrinking
             'short'        - stacked bearish EMAs + MACD histogram < 0
             'neutral'      - EMAs not aligned or MACD conflicting
    """
    params = params or {}
    fast_ema = params.get('fast_ema', 8)
    slow_ema = params.get('slow_ema', 21)
    trend_ema = params.get('trend_ema', 50)
    macd_fast = params.get('macd_fast', 12)
    macd_slow = params.get('macd_slow', 26)
    macd_signal = params.get('macd_signal', 9)

    result = pd.Series('neutral', index=df.index, dtype=object)

    min_bars = max(trend_ema, macd_slow) + macd_signal + 2
    if len(df) < min_bars:
        return result

    close = df['close']

    # EMAs
    ef = close.ewm(span=fast_ema, adjust=False).mean()
    es = close.ewm(span=slow_ema, adjust=False).mean()
    et = close.ewm(span=trend_ema, adjust=False).mean()

    # MACD
    macd_line = close.ewm(span=macd_fast, adjust=False).mean() - close.ewm(span=macd_slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
    histogram = macd_line - signal_line
    hist_prev = histogram.shift(1)

    valid = ef.notna() & es.notna() & et.notna() & histogram.notna() & hist_prev.notna()

    bullish_stack = (ef > es) & (es > et) & valid
    bearish_stack = (ef < es) & (es < et) & valid

    result[bullish_stack & (histogram > 0) & (histogram > hist_prev)] = 'strong_long'
    result[bullish_stack & (histogram > 0) & (histogram <= hist_prev) & (result == 'neutral')] = 'long'
    result[bearish_stack & (histogram < 0) & (histogram < hist_prev)] = 'strong_short'
    result[bearish_stack & (histogram < 0) & (histogram >= hist_prev) & (result == 'neutral')] = 'short'

    return result


# ---------------------------------------------------------------------------
# Indicator 2: energy_range_detect
# ---------------------------------------------------------------------------

def energy_range_detect(df, params=None):
    """Detect ranging vs. volatile conditions via ATR compression + BB width.

    Useful for deciding whether to apply trend-following, range-trading, or
    breakout strategies on energy instruments.

    Params:
        atr_period         (int):   ATR lookback          (default 14)
        bb_period          (int):   Bollinger Band period  (default 20)
        bb_std             (float): BB standard deviations (default 2.0)
        squeeze_threshold  (float): ATR compression ratio  (default 0.5)

    Returns:
        pd.Series of signal strings per bar:
             'ranging'  - ATR compressed AND BB width contracting (range-trade mode)
             'volatile' - ATR well above average (breakout likely)
             'normal'   - neither extreme
    """
    params = params or {}
    atr_period = params.get('atr_period', 14)
    bb_period = params.get('bb_period', 20)
    bb_std = params.get('bb_std', 2.0)
    squeeze_threshold = params.get('squeeze_threshold', 0.5)

    result = pd.Series('normal', index=df.index, dtype=object)

    atr_ma_period = 50
    min_bars = max(atr_period, bb_period, atr_ma_period) + 2
    if len(df) < min_bars:
        return result

    # ATR and its 50-period moving average
    atr_series = _atr(df, atr_period)
    atr_ma = atr_series.rolling(window=atr_ma_period).mean()

    # Bollinger Band width
    close = df['close']
    bb_mid = close.rolling(window=bb_period).mean()
    bb_rolling_std = close.rolling(window=bb_period).std()
    bb_upper = bb_mid + bb_std * bb_rolling_std
    bb_lower = bb_mid - bb_std * bb_rolling_std
    bb_width = (bb_upper - bb_lower) / bb_mid
    bb_width_prev = bb_width.shift(1)

    valid = atr_series.notna() & atr_ma.notna() & (atr_ma != 0) & bb_width.notna() & bb_width_prev.notna()

    atr_compressed = (atr_series < squeeze_threshold * atr_ma) & valid
    bb_contracting = (bb_width < bb_width_prev) & valid
    atr_expanded = (atr_series > 1.5 * atr_ma) & valid

    result[atr_compressed & bb_contracting] = 'ranging'
    result[atr_expanded & (result == 'normal')] = 'volatile'

    return result


# ---------------------------------------------------------------------------
# Indicator 3: energy_range_trade
# ---------------------------------------------------------------------------

def energy_range_trade(df, params=None):
    """Range-trading signals for energy in sideways markets.

    Identifies support/resistance levels from a lookback window and generates
    buy-at-support / sell-at-resistance signals with candle confirmation.

    Params:
        lookback   (int):   Lookback period for S/R levels   (default 20)
        buffer_pct (float): Buffer as fraction of range       (default 0.002)

    Returns:
        pd.Series of signal strings per bar:
             'buy_support|support=X.XX|resistance=X.XX'
             'sell_resistance|support=X.XX|resistance=X.XX'
             'neutral'
    """
    params = params or {}
    lookback = params.get('lookback', 20)
    buffer_pct = params.get('buffer_pct', 0.002)

    result = pd.Series('neutral', index=df.index, dtype=object)

    if len(df) < lookback + 1:
        return result

    # Compute rolling support/resistance per bar (using previous N bars)
    rolling_support = df['low'].shift(1).rolling(window=lookback).min()
    rolling_resistance = df['high'].shift(1).rolling(window=lookback).max()
    range_size = rolling_resistance - rolling_support

    close = df['close']
    open_price = df['open']

    valid = rolling_support.notna() & rolling_resistance.notna() & (range_size > 0)
    buffer = buffer_pct * range_size

    buy_cond = valid & (close < rolling_support + buffer) & (close > open_price)
    sell_cond = valid & (close > rolling_resistance - buffer) & (close < open_price)

    for i in range(len(df)):
        if buy_cond.iloc[i]:
            s = rolling_support.iloc[i]
            r = rolling_resistance.iloc[i]
            result.iloc[i] = f"buy_support|support={s:.2f}|resistance={r:.2f}"
        elif sell_cond.iloc[i]:
            s = rolling_support.iloc[i]
            r = rolling_resistance.iloc[i]
            result.iloc[i] = f"sell_resistance|support={s:.2f}|resistance={r:.2f}"

    return result


# ---------------------------------------------------------------------------
# Indicator 4: energy_breakout
# ---------------------------------------------------------------------------

def energy_breakout(df, params=None):
    """Breakout detection for energy using the Keltner Channel + volume.

    Keltner Channels use ATR-based envelopes around an EMA, which adapts
    better to energy's volatile price action than fixed-width Bollinger Bands.
    Volume confirmation helps filter false breakouts.

    Params:
        kc_period    (int):   Keltner Channel EMA period    (default 20)
        kc_atr_mult  (float): ATR multiplier for bands      (default 2.0)
        atr_period   (int):   ATR lookback                   (default 14)
        volume_mult  (float): Volume confirmation multiplier (default 1.5)

    Returns:
        pd.Series of signal strings per bar:
             'bullish_breakout'  - close > upper KC + volume confirmed
             'bearish_breakout'  - close < lower KC + volume confirmed
             'weak_bullish'      - close > upper KC, no volume
             'weak_bearish'      - close < lower KC, no volume
             'neutral'           - inside Keltner Channel
    """
    params = params or {}
    kc_period = params.get('kc_period', 20)
    kc_atr_mult = params.get('kc_atr_mult', 2.0)
    atr_period = params.get('atr_period', 14)
    volume_mult = params.get('volume_mult', 1.5)

    result = pd.Series('neutral', index=df.index, dtype=object)

    min_bars = max(kc_period, atr_period) + 1
    if len(df) < min_bars:
        return result

    # Keltner Channel
    close = df['close']
    kc_mid = close.ewm(span=kc_period, adjust=False).mean()
    atr_series = _atr(df, atr_period)
    kc_upper = kc_mid + kc_atr_mult * atr_series
    kc_lower = kc_mid - kc_atr_mult * atr_series

    valid = kc_upper.notna() & kc_lower.notna()

    # Volume confirmation per bar
    vol_col = 'volume' if 'volume' in df.columns else 'tick_volume'
    if vol_col not in df.columns:
        vol_confirmed = pd.Series(False, index=df.index)
    else:
        vol = df[vol_col]
        avg_vol = vol.rolling(window=kc_period).mean()
        vol_confirmed = (avg_vol.notna()) & (avg_vol != 0) & (vol > volume_mult * avg_vol)

    above_upper = (close > kc_upper) & valid
    below_lower = (close < kc_lower) & valid

    result[above_upper & vol_confirmed] = 'bullish_breakout'
    result[above_upper & ~vol_confirmed] = 'weak_bullish'
    result[below_lower & vol_confirmed] = 'bearish_breakout'
    result[below_lower & ~vol_confirmed] = 'weak_bearish'

    return result


# ---------------------------------------------------------------------------
# Indicator 5: keltner_channel
# ---------------------------------------------------------------------------

def keltner_channel(df, params=None):
    """Normalized position within the Keltner Channel.

    Returns a Series of floats representing where the close sits relative to
    the channel per bar:
        > 1.0 = above upper band
          0.5 = at the middle (EMA)
        < 0.0 = below lower band

    Params:
        period    (int):   EMA period        (default 20)
        atr_mult  (float): ATR multiplier    (default 2.0)
        atr_period (int):  ATR lookback       (default 14)

    Returns:
        pd.Series of float: (close - lower) / (upper - lower), or 0.5 on insufficient data.
    """
    params = params or {}
    period = params.get('period', 20)
    atr_mult = params.get('atr_mult', 2.0)
    atr_period = params.get('atr_period', 14)

    result = pd.Series(0.5, index=df.index)

    min_bars = max(period, atr_period) + 1
    if len(df) < min_bars:
        return result

    close = df['close']
    kc_mid = close.ewm(span=period, adjust=False).mean()
    atr_series = _atr(df, atr_period)
    kc_upper = kc_mid + atr_mult * atr_series
    kc_lower = kc_mid - atr_mult * atr_series

    channel_width = kc_upper - kc_lower
    valid = kc_upper.notna() & kc_lower.notna() & (channel_width != 0)

    result[valid] = (close[valid] - kc_lower[valid]) / channel_width[valid]

    return result


# ---------------------------------------------------------------------------
# Indicator 6: brent_wti_spread
# ---------------------------------------------------------------------------

def brent_wti_spread(df, params=None):
    """Brent-WTI spread relative value signal.

    The spread between Brent (UKOUSDft) and WTI (USOUSD) typically ranges
    from $1-$5.  Extreme readings suggest mean-reversion opportunities.

    Call this on a Brent (UKOUSDft) DataFrame and pass the current WTI price
    via params.

    Params:
        wti_price    (float): Current USOUSD price (required)
        spread_high  (float): Upper threshold for wide spread  (default 5.0)
        spread_low   (float): Lower threshold for narrow spread (default 1.0)

    Returns:
        pd.Series of signal strings per bar:
             'spread_wide'   - Brent premium > spread_high (potential mean reversion)
             'spread_narrow' - Brent premium < spread_low  (potential expansion)
             'normal'        - within typical range
    """
    params = params or {}
    wti_price = params.get('wti_price')
    spread_high = params.get('spread_high', 5.0)
    spread_low = params.get('spread_low', 1.0)

    result = pd.Series('normal', index=df.index, dtype=object)

    if wti_price is None or len(df) == 0:
        return result

    brent_close = df['close']
    valid = brent_close.notna()

    spread = brent_close - wti_price

    result[(spread > spread_high) & valid] = 'spread_wide'
    result[(spread < spread_low) & valid] = 'spread_narrow'

    return result


# ---------------------------------------------------------------------------
# Indicator 7: energy_volatility_regime
# ---------------------------------------------------------------------------

def energy_volatility_regime(df, params=None):
    """ATR-based volatility regime classifier for energy instruments.

    Replaces OVX (not available in MT5) with an ATR-ratio proxy.  Compares
    current ATR to its 50-period average to detect compression, normal, or
    expansion regimes.  This drives strategy selection and position sizing.

    Research: OVX regime filter doubled avg trade profit and cut drawdown 73%.
    ATR ratio correlates ~0.85 with OVX when calculated on H4 bars.

    Params:
        atr_period    (int):   ATR lookback            (default 14)
        avg_period    (int):   Long-term ATR average    (default 50)
        low_ratio     (float): Below this -> compression (default 0.7)
        high_ratio    (float): Above this -> elevated    (default 1.5)
        crisis_ratio  (float): Above this -> crisis      (default 2.5)

    Returns:
        pd.Series of signal strings per bar:
             'compression'  - ATR < 70% of avg (expect breakout)
             'normal'       - standard conditions
             'elevated'     - ATR 1.5-2.5x avg (trend only, 75% size)
             'high'         - ATR 2.5x+ avg (trend only, 50% size)
             'crisis'       - ATR 3.5x+ avg (no new positions recommended)
    """
    params = params or {}
    atr_period = params.get('atr_period', 14)
    avg_period = params.get('avg_period', 50)
    low_ratio = params.get('low_ratio', 0.7)
    high_ratio = params.get('high_ratio', 1.5)
    crisis_ratio = params.get('crisis_ratio', 2.5)

    result = pd.Series('normal', index=df.index, dtype=object)

    min_bars = max(atr_period, avg_period) + 5
    if len(df) < min_bars:
        return result

    atr_series = _atr(df, atr_period)
    atr_avg = atr_series.rolling(window=avg_period).mean()

    valid = atr_series.notna() & atr_avg.notna() & (atr_avg != 0)
    ratio = pd.Series(np.nan, index=df.index)
    ratio[valid] = atr_series[valid] / atr_avg[valid]

    # Apply thresholds in priority order (most extreme first)
    result[(ratio >= crisis_ratio * 1.4) & valid] = 'crisis'
    result[(ratio >= crisis_ratio) & (ratio < crisis_ratio * 1.4) & valid] = 'high'
    result[(ratio >= high_ratio) & (ratio < crisis_ratio) & valid] = 'elevated'
    result[(ratio < low_ratio) & valid] = 'compression'

    return result


# ---------------------------------------------------------------------------
# Indicator 8: ng_seasonal_filter
# ---------------------------------------------------------------------------

def ng_seasonal_filter(df, params=None):
    """Natural gas seasonal bias based on month of year.

    NG has the clearest seasonality of any major commodity.  The September
    rally (Sep 1 - Oct 25) averaged 56% return over 10 years with 7/10
    years positive and 1:3.2 R:R.

    Uses the timestamp of each bar to determine the month.

    Params:  (none -- seasonal rules are fixed)

    Returns:
        pd.Series of signal strings per bar:
             'strong_bullish' - September (best month historically)
             'bullish'        - March, April, October (pre-winter buildup)
             'bearish'        - May, June, November (injection ramp / sell-the-news)
             'neutral'        - other months (mixed signals)
    """
    result = pd.Series('neutral', index=df.index, dtype=object)

    if len(df) == 0:
        return result

    seasonal_map = {
        1: 'neutral',          # Jan: bearish late, mixed overall
        2: 'neutral',          # Feb: weather-dependent
        3: 'bullish',          # Mar: end of withdrawal = supply uncertainty
        4: 'bullish',          # Apr: transition month, often rallies
        5: 'bearish',          # May: injection ramps up
        6: 'bearish',          # Jun: peak injection, prices sink
        7: 'neutral',          # Jul: cooling demand can surprise
        8: 'neutral',          # Aug: prices find floor
        9: 'strong_bullish',   # Sep: MOST BULLISH -- pre-winter positioning
        10: 'bullish',         # Oct: winter premium pricing in
        11: 'bearish',         # Nov: "buy the rumor, sell the news"
        12: 'neutral',         # Dec: weather-driven swings
    }

    # Extract months from index or 'time' column
    if isinstance(df.index, pd.DatetimeIndex):
        months = df.index.month
    elif 'time' in df.columns:
        try:
            months = pd.to_datetime(df['time']).dt.month
        except Exception:
            return result
    else:
        return result

    for month_val, signal in seasonal_map.items():
        if signal != 'neutral':  # neutral is already the default
            result[months == month_val] = signal

    return result


# ---------------------------------------------------------------------------
# Indicator 9: energy_squeeze_detector
# ---------------------------------------------------------------------------

def energy_squeeze_detector(df, params=None):
    """Bollinger Band / Keltner Channel squeeze detection for energy.

    When Bollinger Bands contract INSIDE Keltner Channels, it signals
    extreme volatility compression -- an imminent explosive move.

    A "fire" signal occurs when the squeeze releases (BB expand back
    outside KC) with directional momentum.

    Params:
        bb_period  (int):   Bollinger Band period     (default 20)
        bb_std     (float): BB standard deviations     (default 2.0)
        kc_period  (int):   Keltner Channel EMA period (default 20)
        kc_mult    (float): KC ATR multiplier          (default 1.5)
        atr_period (int):   ATR period for KC          (default 14)
        min_squeeze_bars (int): Min consecutive squeeze bars (default 5)

    Returns:
        pd.Series of signal strings per bar:
             'squeeze'              - BB inside KC (squeeze active, enough consecutive bars)
             'squeeze_bullish_fire' - squeeze just released upward
             'squeeze_bearish_fire' - squeeze just released downward
             'no_squeeze'           - normal conditions
    """
    params = params or {}
    bb_period = params.get('bb_period', 20)
    bb_std = params.get('bb_std', 2.0)
    kc_period = params.get('kc_period', 20)
    kc_mult = params.get('kc_mult', 1.5)
    atr_period = params.get('atr_period', 14)
    min_squeeze_bars = params.get('min_squeeze_bars', 5)

    result = pd.Series('no_squeeze', index=df.index, dtype=object)

    min_bars = max(bb_period, kc_period, atr_period) + min_squeeze_bars + 2
    if len(df) < min_bars:
        return result

    close = df['close']

    # Bollinger Bands
    bb_mid = close.rolling(window=bb_period).mean()
    bb_rolling_std = close.rolling(window=bb_period).std()
    bb_upper = bb_mid + bb_std * bb_rolling_std
    bb_lower = bb_mid - bb_std * bb_rolling_std

    # Keltner Channels
    kc_mid = close.ewm(span=kc_period, adjust=False).mean()
    atr_series = _atr(df, atr_period)
    kc_upper = kc_mid + kc_mult * atr_series
    kc_lower = kc_mid - kc_mult * atr_series

    # Detect squeeze: BB inside KC
    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    squeeze = squeeze.fillna(False)

    # Count consecutive squeeze bars ending at each position
    consec = pd.Series(0, index=df.index, dtype=int)
    for i in range(len(df)):
        if squeeze.iloc[i]:
            consec.iloc[i] = (consec.iloc[i - 1] + 1) if i > 0 else 1
        else:
            consec.iloc[i] = 0

    squeeze_prev = squeeze.shift(1).fillna(False)
    consec_prev = consec.shift(1).fillna(0)

    # Fire: was in squeeze (enough bars), now released
    fire_mask = squeeze_prev & ~squeeze & (consec_prev >= min_squeeze_bars)
    result[fire_mask & (close > kc_mid) & kc_mid.notna()] = 'squeeze_bullish_fire'
    result[fire_mask & (close <= kc_mid) & kc_mid.notna()] = 'squeeze_bearish_fire'

    # Active squeeze with enough consecutive bars
    result[squeeze & (consec >= min_squeeze_bars) & (result == 'no_squeeze')] = 'squeeze'

    return result


# ---------------------------------------------------------------------------
# Indicator 10: energy_session_filter
# ---------------------------------------------------------------------------

def energy_session_filter(df, params=None):
    """Session filter for energy instruments.

    Energy markets have distinct liquidity profiles by session.  This
    indicator returns the current session per bar to allow strategies to trade
    only during peak liquidity windows.

    Sessions (UTC):
        london:     08:00-12:59  -- Brent primary liquidity
        overlap:    13:00-16:59  -- PEAK: London-NY overlap, tightest spreads
        new_york:   17:00-20:59  -- WTI primary
        dead_zone:  21:00-01:59  -- AVOID: widest spreads
        asian:      02:00-07:59  -- low volume, avoid new entries

    Params:  (none -- session times are fixed)

    Returns:
        pd.Series of session strings per bar:
             'london' | 'overlap' | 'new_york' | 'dead_zone' | 'asian'
    """
    result = pd.Series('dead_zone', index=df.index, dtype=object)

    if len(df) == 0:
        return result

    # Extract hours from index or 'time' column
    if isinstance(df.index, pd.DatetimeIndex):
        hours = df.index.hour
    elif 'time' in df.columns:
        try:
            hours = pd.to_datetime(df['time']).dt.hour
        except Exception:
            return result
    else:
        return result

    result[(hours >= 8) & (hours <= 12)] = 'london'
    result[(hours >= 13) & (hours <= 16)] = 'overlap'
    result[(hours >= 17) & (hours <= 20)] = 'new_york'
    result[(hours >= 21) | (hours <= 1)] = 'dead_zone'
    result[(hours >= 2) & (hours <= 7)] = 'asian'

    return result


# ---------------------------------------------------------------------------
# Indicator 11: energy_momentum_roc
# ---------------------------------------------------------------------------

def energy_momentum_roc(df, params=None):
    """Rate of Change momentum indicator for energy trend confirmation.

    Time-series momentum achieves Sharpe > 1.20 on commodity futures
    (academic research). This ROC indicator with signal line provides
    momentum confirmation for trend-following entries.

    Params:
        roc_period    (int): ROC lookback period        (default 14)
        signal_period (int): Signal line SMA period     (default 5)

    Returns:
        pd.Series of signal strings per bar:
             'strong_bullish'  - ROC > 0, above signal, and accelerating
             'bullish'         - ROC > 0 and above signal
             'strong_bearish'  - ROC < 0, below signal, and accelerating
             'bearish'         - ROC < 0 and below signal
             'neutral'         - ROC near zero or conflicting with signal
    """
    params = params or {}
    roc_period = params.get('roc_period', 14)
    signal_period = params.get('signal_period', 5)

    result = pd.Series('neutral', index=df.index, dtype=object)

    min_bars = roc_period + signal_period + 2
    if len(df) < min_bars:
        return result

    close = df['close']

    roc = ((close - close.shift(roc_period)) / close.shift(roc_period)) * 100
    signal_line = roc.rolling(window=signal_period).mean()
    roc_prev = roc.shift(1)

    valid = roc.notna() & roc_prev.notna() & signal_line.notna()

    bull_above = (roc > 0) & (roc > signal_line) & valid
    bear_below = (roc < 0) & (roc < signal_line) & valid

    result[bull_above & (roc > roc_prev)] = 'strong_bullish'
    result[bull_above & (roc <= roc_prev) & (result == 'neutral')] = 'bullish'
    result[bear_below & (roc < roc_prev)] = 'strong_bearish'
    result[bear_below & (roc >= roc_prev) & (result == 'neutral')] = 'bearish'

    return result

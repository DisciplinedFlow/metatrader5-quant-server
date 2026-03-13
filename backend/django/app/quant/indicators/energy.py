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
        str: 'strong_long'  - stacked bullish EMAs + MACD histogram > 0 and growing
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

    min_bars = max(trend_ema, macd_slow) + macd_signal + 2
    if len(df) < min_bars:
        return 'neutral'

    close = df['close']

    # EMAs
    ema_fast = close.ewm(span=fast_ema, adjust=False).mean()
    ema_slow = close.ewm(span=slow_ema, adjust=False).mean()
    ema_trend = close.ewm(span=trend_ema, adjust=False).mean()

    # MACD
    macd_line = close.ewm(span=macd_fast, adjust=False).mean() - close.ewm(span=macd_slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
    histogram = macd_line - signal_line

    # Latest values
    ef = ema_fast.iloc[-1]
    es = ema_slow.iloc[-1]
    et = ema_trend.iloc[-1]
    hist_now = histogram.iloc[-1]
    hist_prev = histogram.iloc[-2]

    if pd.isna(ef) or pd.isna(es) or pd.isna(et) or pd.isna(hist_now) or pd.isna(hist_prev):
        return 'neutral'

    bullish_stack = ef > es > et
    bearish_stack = ef < es < et

    if bullish_stack and hist_now > 0:
        if hist_now > hist_prev:
            return 'strong_long'
        return 'long'

    if bearish_stack and hist_now < 0:
        if hist_now < hist_prev:  # histogram more negative = shrinking
            return 'strong_short'
        return 'short'

    return 'neutral'


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
        str: 'ranging'  - ATR compressed AND BB width contracting (range-trade mode)
             'volatile' - ATR well above average (breakout likely)
             'normal'   - neither extreme
    """
    params = params or {}
    atr_period = params.get('atr_period', 14)
    bb_period = params.get('bb_period', 20)
    bb_std = params.get('bb_std', 2.0)
    squeeze_threshold = params.get('squeeze_threshold', 0.5)

    atr_ma_period = 50
    min_bars = max(atr_period, bb_period, atr_ma_period) + 2
    if len(df) < min_bars:
        return 'normal'

    # ATR and its 50-period moving average
    atr_series = _atr(df, atr_period)
    atr_ma = atr_series.rolling(window=atr_ma_period).mean()

    atr_now = atr_series.iloc[-1]
    atr_ma_now = atr_ma.iloc[-1]

    if pd.isna(atr_now) or pd.isna(atr_ma_now) or atr_ma_now == 0:
        return 'normal'

    # Bollinger Band width
    close = df['close']
    bb_mid = close.rolling(window=bb_period).mean()
    bb_rolling_std = close.rolling(window=bb_period).std()
    bb_upper = bb_mid + bb_std * bb_rolling_std
    bb_lower = bb_mid - bb_std * bb_rolling_std
    bb_width = (bb_upper - bb_lower) / bb_mid

    bb_width_now = bb_width.iloc[-1]
    bb_width_prev = bb_width.iloc[-2]

    if pd.isna(bb_width_now) or pd.isna(bb_width_prev):
        return 'normal'

    # Conditions
    atr_compressed = atr_now < squeeze_threshold * atr_ma_now
    bb_contracting = bb_width_now < bb_width_prev
    atr_expanded = atr_now > 1.5 * atr_ma_now

    if atr_compressed and bb_contracting:
        return 'ranging'

    if atr_expanded:
        return 'volatile'

    return 'normal'


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
        str: 'buy_support|support=X.XX|resistance=X.XX'
             'sell_resistance|support=X.XX|resistance=X.XX'
             'neutral'
    """
    params = params or {}
    lookback = params.get('lookback', 20)
    buffer_pct = params.get('buffer_pct', 0.002)

    if len(df) < lookback + 1:
        return 'neutral'

    window = df.iloc[-lookback - 1:-1]  # exclude current bar for level calc
    support = window['low'].min()
    resistance = window['high'].max()
    range_size = resistance - support

    if pd.isna(support) or pd.isna(resistance) or range_size <= 0:
        return 'neutral'

    close = df['close'].iloc[-1]
    open_price = df['open'].iloc[-1]
    buffer = buffer_pct * range_size

    support_fmt = f"{support:.2f}"
    resistance_fmt = f"{resistance:.2f}"

    # Buy at support: close near support AND bullish candle
    if close < support + buffer and close > open_price:
        return f"buy_support|support={support_fmt}|resistance={resistance_fmt}"

    # Sell at resistance: close near resistance AND bearish candle
    if close > resistance - buffer and close < open_price:
        return f"sell_resistance|support={support_fmt}|resistance={resistance_fmt}"

    return 'neutral'


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
        str: 'bullish_breakout'  - close > upper KC + volume confirmed
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

    min_bars = max(kc_period, atr_period) + 1
    if len(df) < min_bars:
        return 'neutral'

    # Keltner Channel
    close = df['close']
    kc_mid = close.ewm(span=kc_period, adjust=False).mean()
    atr_series = _atr(df, atr_period)
    kc_upper = kc_mid + kc_atr_mult * atr_series
    kc_lower = kc_mid - kc_atr_mult * atr_series

    upper = kc_upper.iloc[-1]
    lower = kc_lower.iloc[-1]
    close_now = close.iloc[-1]

    if pd.isna(upper) or pd.isna(lower):
        return 'neutral'

    # Volume confirmation
    vol_col = 'volume' if 'volume' in df.columns else 'tick_volume'
    if vol_col not in df.columns:
        # No volume data — treat all breakouts as weak
        volume_confirmed = False
    else:
        vol = df[vol_col]
        avg_vol = vol.rolling(window=kc_period).mean().iloc[-1]
        current_vol = vol.iloc[-1]
        if pd.isna(avg_vol) or avg_vol == 0:
            volume_confirmed = False
        else:
            volume_confirmed = current_vol > volume_mult * avg_vol

    # Signal logic
    if close_now > upper:
        return 'bullish_breakout' if volume_confirmed else 'weak_bullish'
    if close_now < lower:
        return 'bearish_breakout' if volume_confirmed else 'weak_bearish'

    return 'neutral'


# ---------------------------------------------------------------------------
# Indicator 5: keltner_channel
# ---------------------------------------------------------------------------

def keltner_channel(df, params=None):
    """Normalized position within the Keltner Channel.

    Returns a float representing where the current close sits relative to
    the channel:
        > 1.0 = above upper band
          0.5 = at the middle (EMA)
        < 0.0 = below lower band

    Params:
        period    (int):   EMA period        (default 20)
        atr_mult  (float): ATR multiplier    (default 2.0)
        atr_period (int):  ATR lookback       (default 14)

    Returns:
        float: (close - lower) / (upper - lower), or 0.5 on insufficient data.
    """
    params = params or {}
    period = params.get('period', 20)
    atr_mult = params.get('atr_mult', 2.0)
    atr_period = params.get('atr_period', 14)

    min_bars = max(period, atr_period) + 1
    if len(df) < min_bars:
        return 0.5

    close = df['close']
    kc_mid = close.ewm(span=period, adjust=False).mean()
    atr_series = _atr(df, atr_period)
    kc_upper = kc_mid + atr_mult * atr_series
    kc_lower = kc_mid - atr_mult * atr_series

    upper = kc_upper.iloc[-1]
    lower = kc_lower.iloc[-1]
    close_now = close.iloc[-1]

    if pd.isna(upper) or pd.isna(lower):
        return 0.5

    channel_width = upper - lower
    if channel_width == 0:
        return 0.5

    return float((close_now - lower) / channel_width)


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
        str: 'spread_wide'   - Brent premium > spread_high (potential mean reversion)
             'spread_narrow' - Brent premium < spread_low  (potential expansion)
             'normal'        - within typical range
    """
    params = params or {}
    wti_price = params.get('wti_price')
    spread_high = params.get('spread_high', 5.0)
    spread_low = params.get('spread_low', 1.0)

    if wti_price is None or len(df) == 0:
        return 'normal'

    brent_price = df['close'].iloc[-1]

    if pd.isna(brent_price) or pd.isna(wti_price):
        return 'normal'

    spread = brent_price - wti_price

    if spread > spread_high:
        return 'spread_wide'
    if spread < spread_low:
        return 'spread_narrow'

    return 'normal'

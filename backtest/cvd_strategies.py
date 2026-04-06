"""
CVD (Cumulative Volume Delta) strategies for backtesting.

Approach B — Body-weighted delta calculation:
  For each candle, split tick_volume into buy/sell pressure based on
  the candle's body position AND direction, not just close-within-range.

  - Strong bullish candle (close near high, big body) → most volume is buying
  - Doji/indecision (close ≈ open, near middle) → roughly equal
  - Strong bearish candle (close near low, big body) → most volume is selling

  body_ratio = abs(close - open) / (high - low)  [0..1]
  direction = 1 if close > open else -1
  buy_pct = 0.5 + direction * body_ratio * 0.5
  buy_vol = tick_volume * buy_pct
  sell_vol = tick_volume * (1 - buy_pct)
  delta = buy_vol - sell_vol
  cvd = cumsum(delta)

Each strategy: fn(df, i) -> 'BUY' | 'SELL' | None
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# CVD calculation (Approach B — body-weighted)
# ---------------------------------------------------------------------------

def compute_cvd(df):
    """Add CVD columns to DataFrame using body-weighted delta.

    Adds: 'delta', 'cvd', 'cvd_ema5', 'cvd_ema13'
    """
    h = df['high']
    l = df['low']
    o = df['open']
    c = df['close']
    vol = df['tick_volume']

    # Bar range (avoid division by zero)
    bar_range = (h - l).replace(0, np.nan)

    # Body ratio: how much of the bar is body vs wick [0..1]
    body_ratio = (abs(c - o) / bar_range).fillna(0).clip(0, 1)

    # Direction: +1 bullish, -1 bearish, 0 doji
    direction = np.sign(c - o)

    # Buy percentage: 0.5 is neutral, skewed by body direction and size
    buy_pct = 0.5 + direction * body_ratio * 0.5

    # Delta = buy_volume - sell_volume
    df = df.copy()
    df['delta'] = vol * (2 * buy_pct - 1)
    df['cvd'] = df['delta'].cumsum()

    # Smoothed CVD for signal detection
    df['cvd_ema5'] = df['cvd'].ewm(span=5, adjust=False).mean()
    df['cvd_ema13'] = df['cvd'].ewm(span=13, adjust=False).mean()

    # Delta EMA for absorption detection
    df['delta_ema'] = df['delta'].ewm(span=10, adjust=False).mean()
    df['delta_std'] = df['delta'].rolling(20).std()

    # Normalized delta (z-score)
    df['delta_z'] = (df['delta'] - df['delta'].rolling(20).mean()) / df['delta'].rolling(20).std()

    return df


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi_wilder(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def adx_indicator(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr_s = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_s
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return adx_val, plus_di, minus_di


def swing_high_val(df, i, lookback=10):
    """Highest high in the last `lookback` bars."""
    return df['high'].iloc[max(0, i-lookback):i+1].max()


def swing_low_val(df, i, lookback=10):
    """Lowest low in the last `lookback` bars."""
    return df['low'].iloc[max(0, i-lookback):i+1].min()


# ---------------------------------------------------------------------------
# STRATEGY 1: CVD Lack of Participation (Divergence)
# ---------------------------------------------------------------------------
# Price makes a new swing high/low but CVD fails to confirm.
# This signals that participants aren't backing the move — likely to reverse.
#
# BUY: Price makes lower low, but CVD makes higher low (bullish LoP)
# SELL: Price makes higher high, but CVD makes lower high (bearish LoP)

def cvd_lack_of_participation(df, i, price_lookback=20, cvd_lookback=20):
    """CVD Lack of Participation — divergence between price and CVD."""
    if i < max(price_lookback, cvd_lookback) + 5:
        return None

    # Current and prior swing points
    price_now = df['close'].iloc[i]
    cvd_now = df['cvd'].iloc[i]

    # Find the swing low/high in the prior window
    window_start = max(0, i - price_lookback)
    mid = i - price_lookback // 2  # split into two halves

    # Prior half and current half
    prior_price_low = df['low'].iloc[window_start:mid].min()
    recent_price_low = df['low'].iloc[mid:i+1].min()
    prior_price_high = df['high'].iloc[window_start:mid].max()
    recent_price_high = df['high'].iloc[mid:i+1].max()

    prior_cvd_low = df['cvd'].iloc[window_start:mid].min()
    recent_cvd_low = df['cvd'].iloc[mid:i+1].min()
    prior_cvd_high = df['cvd'].iloc[window_start:mid].max()
    recent_cvd_high = df['cvd'].iloc[mid:i+1].max()

    # Bullish LoP: price lower low, CVD higher low
    if recent_price_low < prior_price_low and recent_cvd_low > prior_cvd_low:
        # Confirmation: current bar closes above its open (bullish)
        if df['close'].iloc[i] > df['open'].iloc[i]:
            return 'BUY'

    # Bearish LoP: price higher high, CVD lower high
    if recent_price_high > prior_price_high and recent_cvd_high < prior_cvd_high:
        # Confirmation: current bar closes below its open (bearish)
        if df['close'].iloc[i] < df['open'].iloc[i]:
            return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 2: CVD Absorption
# ---------------------------------------------------------------------------
# High volume at a level but price doesn't move — limit orders absorbing flow.
# Detected by: large delta spike but small price movement.
#
# BUY: Large negative delta (selling pressure) but price holds/bounces = buyers absorbing
# SELL: Large positive delta (buying pressure) but price stalls/drops = sellers absorbing

def cvd_absorption(df, i, delta_threshold=1.5, price_threshold=0.3):
    """CVD Absorption — large delta but price doesn't follow."""
    if i < 25:
        return None

    delta_z = df['delta_z'].iloc[i]
    if pd.isna(delta_z):
        return None

    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return None

    # Price movement relative to ATR
    price_move = abs(df['close'].iloc[i] - df['open'].iloc[i]) / atr

    # Bullish absorption: heavy selling (negative delta) but price doesn't drop
    if delta_z < -delta_threshold and price_move < price_threshold:
        # Price held above recent low = absorption confirmed
        if df['close'].iloc[i] > df['low'].iloc[max(0,i-3):i].min():
            return 'BUY'

    # Bearish absorption: heavy buying (positive delta) but price doesn't rise
    if delta_z > delta_threshold and price_move < price_threshold:
        # Price held below recent high = absorption confirmed
        if df['close'].iloc[i] < df['high'].iloc[max(0,i-3):i].max():
            return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 3: CVD LoP + EMA Trend Filter
# ---------------------------------------------------------------------------
# Same as LoP but only take signals in the direction of the trend.
# This filters out counter-trend divergences that are more likely to fail.

def cvd_lop_trend(df, i, price_lookback=20, ema_period=50):
    """CVD LoP only in the direction of EMA trend."""
    if i < max(price_lookback, ema_period) + 5:
        return None

    # Trend direction
    ema_val = ema(df['close'].iloc[:i+1], ema_period).iloc[-1]
    if pd.isna(ema_val):
        return None

    price = df['close'].iloc[i]
    bullish_trend = price > ema_val
    bearish_trend = price < ema_val

    # Get LoP signal
    signal = cvd_lack_of_participation(df, i, price_lookback)

    # Only take with-trend signals
    if signal == 'BUY' and bullish_trend:
        return 'BUY'
    if signal == 'SELL' and bearish_trend:
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 4: CVD Absorption + EMA Trend Filter
# ---------------------------------------------------------------------------

def cvd_absorption_trend(df, i, delta_threshold=1.5, ema_period=50):
    """CVD Absorption only in the direction of EMA trend."""
    if i < max(25, ema_period) + 5:
        return None

    ema_val = ema(df['close'].iloc[:i+1], ema_period).iloc[-1]
    if pd.isna(ema_val):
        return None

    price = df['close'].iloc[i]
    bullish_trend = price > ema_val
    bearish_trend = price < ema_val

    signal = cvd_absorption(df, i, delta_threshold)

    if signal == 'BUY' and bullish_trend:
        return 'BUY'
    if signal == 'SELL' and bearish_trend:
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 5: CVD LoP + Session Sweep
# ---------------------------------------------------------------------------
# Combine CVD divergence with session range sweep.
# Most powerful at London open (07-10 UTC) sweeping Asia range,
# or NY open (13-16 UTC) sweeping London range.

def cvd_lop_session_sweep(df, i, price_lookback=20):
    """CVD LoP at session range extremes."""
    if i < price_lookback + 5:
        return None

    bar = df.iloc[i]
    hour = bar['time'].hour
    today = bar['time'].date()

    # Determine which session range to use
    if 7 <= hour < 12:
        # London: sweep Asia range (00-07 UTC)
        range_start, range_end = 0, 7
    elif 13 <= hour < 17:
        # NY: sweep London range (07-13 UTC)
        range_start, range_end = 7, 13
    else:
        return None

    # Build session range
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

    # Check if price swept the range
    swept_high = bar['high'] > range_high
    swept_low = bar['low'] < range_low

    # Get LoP signal
    signal = cvd_lack_of_participation(df, i, price_lookback)

    # Bullish: swept low (stop hunt) + CVD bullish divergence
    if swept_low and signal == 'BUY':
        return 'BUY'

    # Bearish: swept high (stop hunt) + CVD bearish divergence
    if swept_high and signal == 'SELL':
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 6: CVD Momentum Confirmation
# ---------------------------------------------------------------------------
# Only enter when BOTH price and CVD confirm direction.
# Opposite of divergence — this is a trend-continuation signal.
# CVD EMA crossover + price above EMA = strong momentum.

def cvd_momentum(df, i, cvd_fast=5, cvd_slow=13, price_ema=21):
    """CVD momentum: CVD EMA crossover confirms price trend."""
    if i < max(cvd_slow, price_ema) + 5:
        return None

    # CVD EMA crossover
    cvd_fast_now = df['cvd_ema5'].iloc[i]
    cvd_slow_now = df['cvd_ema13'].iloc[i]
    cvd_fast_prev = df['cvd_ema5'].iloc[i-1]
    cvd_slow_prev = df['cvd_ema13'].iloc[i-1]

    if pd.isna(cvd_fast_now) or pd.isna(cvd_slow_now):
        return None

    # Price trend
    price_ema_val = ema(df['close'].iloc[:i+1], price_ema).iloc[-1]
    if pd.isna(price_ema_val):
        return None

    price = df['close'].iloc[i]

    # Bullish: CVD fast crosses above slow + price above EMA
    if (cvd_fast_prev <= cvd_slow_prev and cvd_fast_now > cvd_slow_now
            and price > price_ema_val):
        return 'BUY'

    # Bearish: CVD fast crosses below slow + price below EMA
    if (cvd_fast_prev >= cvd_slow_prev and cvd_fast_now < cvd_slow_now
            and price < price_ema_val):
        return 'SELL'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 7: CVD Exhaustion
# ---------------------------------------------------------------------------
# Extreme CVD readings (far from mean) signal exhaustion.
# After a strong trend, CVD reaching 2+ std deviations suggests reversal.

def cvd_exhaustion(df, i, lookback=50, std_threshold=2.0):
    """CVD Exhaustion — extreme CVD readings signal potential reversal."""
    if i < lookback + 10:
        return None

    cvd_slice = df['cvd'].iloc[i-lookback:i+1]
    cvd_mean = cvd_slice.mean()
    cvd_std = cvd_slice.std()

    if pd.isna(cvd_std) or cvd_std <= 0:
        return None

    cvd_z = (df['cvd'].iloc[i] - cvd_mean) / cvd_std

    # Confirmation: reversal candle
    bullish_reversal = df['close'].iloc[i] > df['open'].iloc[i] and df['close'].iloc[i-1] < df['open'].iloc[i-1]
    bearish_reversal = df['close'].iloc[i] < df['open'].iloc[i] and df['close'].iloc[i-1] > df['open'].iloc[i-1]

    # Exhaustion high: CVD extremely positive + bearish reversal
    if cvd_z > std_threshold and bearish_reversal:
        return 'SELL'

    # Exhaustion low: CVD extremely negative + bullish reversal
    if cvd_z < -std_threshold and bullish_reversal:
        return 'BUY'

    return None


# ---------------------------------------------------------------------------
# STRATEGY 8: CVD LoP + Structure (higher-highs / lower-lows)
# ---------------------------------------------------------------------------
# Price makes a structure break (lower low in uptrend) but CVD diverges.
# This is the most refined version — combines structure + divergence.

def cvd_lop_structure(df, i, swing_lookback=10, ema_period=50):
    """CVD LoP at market structure levels with trend filter."""
    if i < max(swing_lookback * 3, ema_period) + 5:
        return None

    # Trend
    ema_val = ema(df['close'].iloc[:i+1], ema_period).iloc[-1]
    if pd.isna(ema_val):
        return None
    price = df['close'].iloc[i]

    # Find last two swing lows and highs
    # Window 1: i-3*lookback to i-lookback
    # Window 2: i-lookback to i
    w1_start = max(0, i - swing_lookback * 3)
    w1_end = i - swing_lookback
    w2_start = i - swing_lookback
    w2_end = i + 1

    if w1_end <= w1_start:
        return None

    # Swing lows
    sw1_low = df['low'].iloc[w1_start:w1_end].min()
    sw2_low = df['low'].iloc[w2_start:w2_end].min()
    sw1_cvd_low = df['cvd'].iloc[w1_start:w1_end].min()
    sw2_cvd_low = df['cvd'].iloc[w2_start:w2_end].min()

    # Swing highs
    sw1_high = df['high'].iloc[w1_start:w1_end].max()
    sw2_high = df['high'].iloc[w2_start:w2_end].max()
    sw1_cvd_high = df['cvd'].iloc[w1_start:w1_end].max()
    sw2_cvd_high = df['cvd'].iloc[w2_start:w2_end].max()

    # Bullish LoP at structure: lower low in price, higher low in CVD, in uptrend
    if price > ema_val:  # uptrend
        if sw2_low < sw1_low and sw2_cvd_low > sw1_cvd_low:
            # Current bar is bullish
            if df['close'].iloc[i] > df['open'].iloc[i]:
                return 'BUY'

    # Bearish LoP at structure: higher high in price, lower high in CVD, in downtrend
    if price < ema_val:  # downtrend
        if sw2_high > sw1_high and sw2_cvd_high < sw1_cvd_high:
            # Current bar is bearish
            if df['close'].iloc[i] < df['open'].iloc[i]:
                return 'SELL'

    return None

"""
Strategy functions for backtesting.

Each strategy: fn(df, i) -> 'BUY' | 'SELL' | None
  df: full OHLCV DataFrame (with atr column). Only look at rows[:i+1].
  i:  current bar index (the bar that just closed).
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Indicator helpers (pure numpy/pandas, no external deps)
# ---------------------------------------------------------------------------

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    return series.rolling(period).mean()


def rsi_wilder(series, period=14):
    """RSI with Wilder's smoothing (correct implementation)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line


def adx(df, period=14):
    """Average Directional Index."""
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # Zero out when other DM is larger
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr_s = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr_s
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean(), plus_di, minus_di


def bollinger_bands(series, period=20, std_dev=2):
    mid = sma(series, period)
    std = series.rolling(period).std()
    return mid, mid + std_dev * std, mid - std_dev * std


def keltner_channels(df, ema_period=20, atr_period=14, atr_mult=1.5):
    mid = ema(df['close'], ema_period)
    upper = mid + atr_mult * df['atr']
    lower = mid - atr_mult * df['atr']
    return mid, upper, lower


def stochastic(df, k_period=14, d_period=3):
    low_min = df['low'].rolling(k_period).min()
    high_max = df['high'].rolling(k_period).max()
    k = 100 * (df['close'] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = sma(k, d_period)
    return k, d


def volume_sma(df, period=20):
    return sma(df['tick_volume'], period)


def swing_high(df, lookback=3):
    """True where bar is a swing high (highest high in lookback bars each side)."""
    highs = df['high']
    result = pd.Series(False, index=df.index)
    for i in range(lookback, len(df) - lookback):
        window = highs.iloc[i-lookback:i+lookback+1]
        if highs.iloc[i] == window.max():
            result.iloc[i] = True
    return result


def swing_low(df, lookback=3):
    """True where bar is a swing low (lowest low in lookback bars each side)."""
    lows = df['low']
    result = pd.Series(False, index=df.index)
    for i in range(lookback, len(df) - lookback):
        window = lows.iloc[i-lookback:i+lookback+1]
        if lows.iloc[i] == window.min():
            result.iloc[i] = True
    return result


# ---------------------------------------------------------------------------
# STRATEGIES
# ---------------------------------------------------------------------------

def ema_crossover(df, i, fast=8, slow=21):
    """EMA crossover: BUY when fast crosses above slow, SELL when below."""
    if i < slow + 1:
        return None
    close = df['close']
    fast_now = ema(close.iloc[:i+1], fast).iloc[-1]
    fast_prev = ema(close.iloc[:i], fast).iloc[-1]
    slow_now = ema(close.iloc[:i+1], slow).iloc[-1]
    slow_prev = ema(close.iloc[:i], slow).iloc[-1]
    if fast_prev <= slow_prev and fast_now > slow_now:
        return 'BUY'
    if fast_prev >= slow_prev and fast_now < slow_now:
        return 'SELL'
    return None


def rsi_reversal(df, i, period=14, oversold=30, overbought=70):
    """RSI mean reversion: BUY when RSI crosses back above oversold, SELL when crosses below overbought."""
    if i < period + 2:
        return None
    r = rsi_wilder(df['close'].iloc[:i+1], period)
    if len(r) < 2:
        return None
    now, prev = r.iloc[-1], r.iloc[-2]
    if pd.isna(now) or pd.isna(prev):
        return None
    if prev <= oversold and now > oversold:
        return 'BUY'
    if prev >= overbought and now < overbought:
        return 'SELL'
    return None


def macd_momentum(df, i):
    """MACD crossover with ADX trend filter. Only trade when ADX > 20."""
    if i < 35:
        return None
    close = df['close'].iloc[:i+1]
    m, s = macd(close)
    adx_val, plus_di, minus_di = adx(df.iloc[:i+1])
    if pd.isna(m.iloc[-1]) or pd.isna(adx_val.iloc[-1]):
        return None
    if adx_val.iloc[-1] < 20:
        return None
    # MACD cross
    if m.iloc[-2] <= s.iloc[-2] and m.iloc[-1] > s.iloc[-1]:
        return 'BUY'
    if m.iloc[-2] >= s.iloc[-2] and m.iloc[-1] < s.iloc[-1]:
        return 'SELL'
    return None


def bollinger_bounce(df, i, period=20, std_dev=2):
    """Bollinger Band mean reversion: BUY at lower band, SELL at upper band.
    Only when band is contracting (squeeze = low volatility → expect expansion)."""
    if i < period + 5:
        return None
    close = df['close'].iloc[:i+1]
    mid, upper, lower = bollinger_bands(close, period, std_dev)
    if pd.isna(upper.iloc[-1]):
        return None
    # Band width contracting (squeeze)
    bw_now = (upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1]
    bw_prev = (upper.iloc[-5] - lower.iloc[-5]) / mid.iloc[-5] if not pd.isna(mid.iloc[-5]) else bw_now
    squeeze = bw_now < bw_prev
    price = df['close'].iloc[i]
    if price <= lower.iloc[-1] and squeeze:
        return 'BUY'
    if price >= upper.iloc[-1] and squeeze:
        return 'SELL'
    return None


def session_breakout(df, i, range_start=0, range_end=7, trade_start=7, trade_end=10):
    """London session breakout: compute Asian session range (00-07 UTC),
    trade breakout in London open (07-10 UTC)."""
    if i < 30:
        return None
    bar = df.iloc[i]
    hour = bar['time'].hour
    if hour < trade_start or hour >= trade_end:
        return None
    # Find the range from range_start to range_end today
    today = bar['time'].date()
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
    if bar['close'] > range_high:
        return 'BUY'
    if bar['close'] < range_low:
        return 'SELL'
    return None


def keltner_breakout(df, i, ema_period=20, atr_mult=1.5):
    """Keltner Channel breakout with volume confirmation.
    BUY when close breaks above upper channel with above-average volume."""
    if i < ema_period + 14 + 1:
        return None
    close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]
    mid, upper, lower = keltner_channels(df.iloc[:i+1], ema_period, 14, atr_mult)
    if pd.isna(upper.iloc[-1]):
        return None
    vol = df['tick_volume'].iloc[i]
    avg_vol = df['tick_volume'].iloc[max(0,i-20):i].mean()
    vol_confirm = vol > avg_vol * 1.2
    if prev_close <= upper.iloc[-2] and close > upper.iloc[-1] and vol_confirm:
        return 'BUY'
    if prev_close >= lower.iloc[-2] and close < lower.iloc[-1] and vol_confirm:
        return 'SELL'
    return None


def stoch_rsi_combo(df, i, rsi_period=14, stoch_k=14, stoch_d=3):
    """Stochastic + RSI combo: trade when both agree at extremes.
    BUY when RSI < 40 AND Stoch %K crosses above %D from below 20.
    SELL when RSI > 60 AND Stoch %K crosses below %D from above 80."""
    if i < max(rsi_period, stoch_k) + stoch_d + 2:
        return None
    r = rsi_wilder(df['close'].iloc[:i+1], rsi_period)
    k, d = stochastic(df.iloc[:i+1], stoch_k, stoch_d)
    if pd.isna(r.iloc[-1]) or pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]):
        return None
    # BUY
    if r.iloc[-1] < 40 and k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1] and k.iloc[-1] < 30:
        return 'BUY'
    # SELL
    if r.iloc[-1] > 60 and k.iloc[-2] >= d.iloc[-2] and k.iloc[-1] < d.iloc[-1] and k.iloc[-1] > 70:
        return 'SELL'
    return None


def engulfing_pattern(df, i):
    """Candlestick engulfing pattern at key levels (near swing high/low).
    BUY: bullish engulfing near recent swing low.
    SELL: bearish engulfing near recent swing high."""
    if i < 20:
        return None
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    curr_body = curr['close'] - curr['open']
    prev_body = prev['close'] - prev['open']
    # Bullish engulfing
    if (prev_body < 0 and curr_body > 0 and
        curr['open'] <= prev['close'] and curr['close'] >= prev['open'] and
        abs(curr_body) > abs(prev_body)):
        # Near recent low (within 1 ATR of 10-bar low)
        recent_low = df['low'].iloc[max(0,i-10):i].min()
        if curr['low'] <= recent_low + df['atr'].iloc[i] * 0.5:
            return 'BUY'
    # Bearish engulfing
    if (prev_body > 0 and curr_body < 0 and
        curr['open'] >= prev['close'] and curr['close'] <= prev['open'] and
        abs(curr_body) > abs(prev_body)):
        recent_high = df['high'].iloc[max(0,i-10):i].max()
        if curr['high'] >= recent_high - df['atr'].iloc[i] * 0.5:
            return 'SELL'
    return None


def triple_ema_pullback(df, i, fast=8, mid=21, slow=50):
    """Trend-following: 3 EMAs aligned + pullback to mid EMA.
    BUY when EMA8 > EMA21 > EMA50, price pulls back to touch EMA21, then closes above.
    SELL when EMA8 < EMA21 < EMA50, price pulls back to EMA21, closes below."""
    if i < slow + 5:
        return None
    close = df['close'].iloc[:i+1]
    f = ema(close, fast)
    m = ema(close, mid)
    s = ema(close, slow)
    if pd.isna(f.iloc[-1]):
        return None
    # Bullish alignment
    if f.iloc[-1] > m.iloc[-1] > s.iloc[-1]:
        # Pullback: previous bar low touched EMA21, current bar closes above EMA21
        if df['low'].iloc[i-1] <= m.iloc[-2] and df['close'].iloc[i] > m.iloc[-1]:
            return 'BUY'
    # Bearish alignment
    if f.iloc[-1] < m.iloc[-1] < s.iloc[-1]:
        if df['high'].iloc[i-1] >= m.iloc[-2] and df['close'].iloc[i] < m.iloc[-1]:
            return 'SELL'
    return None

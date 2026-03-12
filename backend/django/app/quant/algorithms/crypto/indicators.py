import pandas as pd
import numpy as np


def calculate_sma(prices: pd.Series, window: int) -> pd.Series:
    return prices.rolling(window=window, min_periods=window).mean()


def calculate_ema(prices: pd.Series, span: int) -> pd.Series:
    return prices.ewm(span=span, adjust=False).mean()


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_momentum(prices: pd.Series, period: int = 10) -> pd.Series:
    return prices / prices.shift(period) - 1


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    high_low = high - low
    high_close = (high - close.shift(1)).abs()
    low_close = (low - close.shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period, min_periods=period).mean()


# ─────────────────────────────────────────────
# Advanced indicators for multi-strategy system
# ─────────────────────────────────────────────

def calculate_bollinger_bands(prices: pd.Series, window: int = 20, num_std: float = 2.0):
    """Returns (middle, upper, lower, bandwidth, %b)."""
    middle = prices.rolling(window=window, min_periods=window).mean()
    std = prices.rolling(window=window, min_periods=window).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = (upper - lower) / middle
    pct_b = (prices - lower) / (upper - lower)
    return middle, upper, lower, bandwidth, pct_b


def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_stochastic_rsi(prices: pd.Series, rsi_period: int = 14, stoch_period: int = 14,
                              k_smooth: int = 3, d_smooth: int = 3):
    """Returns (stoch_k, stoch_d) in 0-100 range."""
    rsi = calculate_rsi(prices, rsi_period)
    rsi_min = rsi.rolling(window=stoch_period, min_periods=stoch_period).min()
    rsi_max = rsi.rolling(window=stoch_period, min_periods=stoch_period).max()
    stoch_k = 100 * (rsi - rsi_min) / (rsi_max - rsi_min)
    stoch_k = stoch_k.rolling(window=k_smooth, min_periods=1).mean()
    stoch_d = stoch_k.rolling(window=d_smooth, min_periods=1).mean()
    return stoch_k, stoch_d


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — measures trend strength (0-100)."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = calculate_atr(high, low, close, period)
    plus_di = 100 * (plus_dm.rolling(window=period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period, min_periods=period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.rolling(window=period, min_periods=period).mean()
    return adx


def calculate_vwap_proxy(high: pd.Series, low: pd.Series, close: pd.Series,
                          volume: pd.Series, period: int = 20) -> pd.Series:
    """Rolling VWAP proxy (true VWAP resets intraday, this is a rolling approximation)."""
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).rolling(window=period, min_periods=period).sum() / \
           volume.rolling(window=period, min_periods=period).sum()
    return vwap


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume — cumulative volume flow."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (volume * direction).cumsum()


def calculate_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume SMA for relative volume analysis."""
    return volume.rolling(window=period, min_periods=period).mean()

"""
CVD (Cumulative Volume Delta) calculator for crypto using Binance klines.

Uses taker buy/sell volume from Binance REST API (no key required) to compute
accurate CVD for Lighter.xyz crypto pairs. Detects four divergence patterns:

- lack_of_participants: price makes new extreme, CVD does not confirm
- absorption: CVD makes new extreme, price does not follow
- extremes: price at range boundary while CVD momentum disagrees
- multi_timeframe: LoP confirmed on 2 timeframes (15m + 1h)

CVD delta per candle = 2 × taker_buy_volume − total_volume
"""
import logging
import requests
import pandas as pd
import numpy as np

logger = logging.getLogger('app.lighter')

BINANCE_KLINES_URL = 'https://api.binance.com/api/v3/klines'
BINANCE_REQUEST_TIMEOUT = 8

LIGHTER_TO_BINANCE = {
    'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT',
    'AVAX': 'AVAXUSDT', 'DOGE': 'DOGEUSDT', 'LINK': 'LINKUSDT',
    'XRP': 'XRPUSDT', 'NEAR': 'NEARUSDT', 'DOT': 'DOTUSDT',
    'SUI': 'SUIUSDT', 'BNB': 'BNBUSDT', 'AAVE': 'AAVEUSDT',
    'ADA': 'ADAUSDT', 'ARB': 'ARBUSDT', 'OP': 'OPUSDT',
    'TON': 'TONUSDT', 'HYPE': 'HYPEUSDT',
}

# Binance interval → readable string mapping for caching
_INTERVAL_ALIASES = {'5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}

# Cache TTL slightly under the task interval so each run gets fresh data
CVD_CACHE_TTL = 55  # seconds


def get_cvd_dataframe(symbol: str, interval: str = '15m', limit: int = 60) -> pd.DataFrame | None:
    """
    Fetch Binance OHLCV + taker buy volume and compute running CVD.

    Returns a DataFrame with columns: open, high, low, close, volume, cvd_delta, cvd.
    Returns None if symbol not mappable or API fails.
    Cached per (symbol, interval) for CVD_CACHE_TTL seconds.
    """
    from django.core.cache import cache

    binance_sym = LIGHTER_TO_BINANCE.get(symbol)
    if not binance_sym:
        logger.debug("CVD: no Binance mapping for %s", symbol)
        return None

    cache_key = f'lighter:cvd_df:{symbol}:{interval}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            BINANCE_KLINES_URL,
            params={'symbol': binance_sym, 'interval': interval, 'limit': limit},
            timeout=BINANCE_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        logger.debug("CVD: Binance fetch failed for %s %s: %s", symbol, interval, e)
        return None

    # Binance kline columns (12 total):
    # 0=open_time, 1=open, 2=high, 3=low, 4=close, 5=volume,
    # 6=close_time, 7=quote_vol, 8=trades, 9=taker_buy_base_vol,
    # 10=taker_buy_quote_vol, 11=ignore
    df = pd.DataFrame(raw, columns=[
        'ts', 'open', 'high', 'low', 'close', 'volume',
        'close_ts', 'quote_vol', 'trades', 'taker_buy_vol', 'taker_buy_quote_vol', '_',
    ])
    for col in ('open', 'high', 'low', 'close', 'volume', 'taker_buy_vol'):
        df[col] = df[col].astype(float)

    # CVD delta: positive = net buying, negative = net selling
    df['cvd_delta'] = 2.0 * df['taker_buy_vol'] - df['volume']
    df['cvd'] = df['cvd_delta'].cumsum()

    cache.set(cache_key, df, timeout=CVD_CACHE_TTL)
    return df


# ---------------------------------------------------------------------------
# Divergence Detection
# ---------------------------------------------------------------------------

def detect_divergence(df: pd.DataFrame, cvd_type: str, lookback: int = 20) -> tuple:
    """
    Detect CVD divergence using a split-window comparison.

    Method: Split the last `lookback` bars into two equal halves.
    Compare price and CVD extremes between older half and recent half.

    Returns: (signal: int, label: str)
      signal: 1=bullish, -1=bearish, 0=no signal
      label: short description used in logging and entry_signal field
    """
    if df is None or len(df) < lookback + 5:
        return 0, ''

    highs  = df['high'].values[-lookback:]
    lows   = df['low'].values[-lookback:]
    closes = df['close'].values[-lookback:]
    cvd    = df['cvd'].values[-lookback:]

    half = lookback // 2
    prev_h,   recent_h   = highs[:half],  highs[half:]
    prev_l,   recent_l   = lows[:half],   lows[half:]
    prev_cvd, recent_cvd = cvd[:half],    cvd[half:]

    if cvd_type in ('lack_of_participants', 'real_time_leading'):
        # Bearish LoP: price makes higher high, CVD makes lower high → buyers exhausted
        if max(recent_h) > max(prev_h) and max(recent_cvd) < max(prev_cvd):
            return -1, 'bearish_lop'
        # Bullish LoP: price makes lower low, CVD makes higher low → sellers exhausted
        if min(recent_l) < min(prev_l) and min(recent_cvd) > min(prev_cvd):
            return 1, 'bullish_lop'

    elif cvd_type == 'absorption':
        # Bearish Absorption: CVD makes HH (aggressive buying), price does NOT break out
        # → large limit sell orders absorbing market buys at resistance
        if (max(recent_cvd) > max(prev_cvd) and
                max(recent_h) <= max(prev_h) * 1.0015):
            return -1, 'bearish_absorption'
        # Bullish Absorption: CVD makes LL (aggressive selling), price holds
        # → large limit buy orders absorbing market sells at support
        if (min(recent_cvd) < min(prev_cvd) and
                min(recent_l) >= min(prev_l) * 0.9985):
            return 1, 'bullish_absorption'

    elif cvd_type == 'extremes':
        # Price at range extreme without CVD confirmation — exhaustion at key level
        rng = max(highs) - min(lows)
        if rng < 1e-10:
            return 0, ''
        price_pos = (closes[-1] - min(lows)) / rng
        cvd_rng = max(cvd) - min(cvd)
        cvd_pos = (cvd[-1] - min(cvd)) / (cvd_rng + 1e-10)

        # Price near top of range, CVD momentum lagging → bearish
        if price_pos > 0.80 and cvd_pos < 0.45:
            return -1, 'bearish_extreme'
        # Price near bottom of range, CVD strengthening → bullish
        if price_pos < 0.20 and cvd_pos > 0.55:
            return 1, 'bullish_extreme'

    elif cvd_type == 'spot_vs_perpetual':
        # Without separate spot feed, use LoP as proxy (same divergence logic)
        return detect_divergence(df, 'lack_of_participants', lookback)

    return 0, ''


def detect_multitf_divergence(symbol: str, lookback: int = 20) -> tuple:
    """
    Multi-timeframe CVD divergence: require agreement on both 15m and 1h.

    Returns (signal, label) only when both timeframes show the same direction.
    """
    df_15m = get_cvd_dataframe(symbol, interval='15m', limit=60)
    df_1h  = get_cvd_dataframe(symbol, interval='1h',  limit=60)

    sig_15m, lbl_15m = detect_divergence(df_15m, 'lack_of_participants', lookback)
    sig_1h,  lbl_1h  = detect_divergence(df_1h,  'lack_of_participants', lookback)

    if sig_15m != 0 and sig_15m == sig_1h:
        return sig_15m, f'mtf_{lbl_15m}'
    return 0, ''

"""
Market Regime Detection Module

Classifies the current market state for each currency pair into:
- TRENDING_UP: ADX > 25, price above EMAs, clear directional move
- TRENDING_DOWN: ADX > 25, price below EMAs, clear downward move
- RANGING: ADX < 20, tight Bollinger Bands, sideways price action
- VOLATILE: High ATR ratio, wide Bollinger Bands, erratic moves
- UNKNOWN: Transitional state, no clear regime

Used by the entry dispatcher to route strategies to appropriate market conditions:
- TRENDING -> EMA Ribbon Pullback, session breakout strategies
- RANGING -> CVD divergence, mean reversion strategies
- VOLATILE -> reduce position size, widen stops
"""

import logging
import numpy as np
import pandas as pd

from app.utils.constants import MT5Timeframe
from app.utils.api.data import fetch_data_pos

logger = logging.getLogger('regime')


def _compute_adx(df, period=14):
    """Compute Average Directional Index (ADX).

    Replicates the implementation from indicators/momentum.py to keep this
    module self-contained (no circular import risk).
    """
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smoothed averages
    atr = pd.Series(tr, index=df.index).ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, min_periods=period).mean() / atr

    # ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return adx


def _compute_atr(df, period=14):
    """Compute Average True Range (ATR).

    Standard ATR: smoothed average of True Range over *period* bars.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_values = true_range.ewm(span=period, adjust=False).mean()

    return atr_values


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def classify_regime(df, params=None):
    """Classify the current market regime from an OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: open, high, low, close.  At least 50 rows of
        H1 (or equivalent) data are recommended for reliable results.
    params : dict, optional
        Overrides for indicator periods / thresholds:
        - adx_period (default 14)
        - bb_period  (default 20)
        - bb_std     (default 2.0)
        - adx_trend_threshold  (default 25)
        - adx_range_threshold  (default 20)
        - bb_range_threshold   (default 0.02)
        - bb_volatile_threshold (default 0.04)
        - atr_volatile_threshold (default 0.015)

    Returns
    -------
    dict with keys: regime, adx, bb_width, atr_ratio, confidence, ema_direction
    """
    params = params or {}
    adx_period = params.get('adx_period', 14)
    bb_period = params.get('bb_period', 20)
    bb_std = params.get('bb_std', 2.0)
    adx_trend_threshold = params.get('adx_trend_threshold', 25)
    adx_range_threshold = params.get('adx_range_threshold', 20)
    bb_range_threshold = params.get('bb_range_threshold', 0.02)
    bb_volatile_threshold = params.get('bb_volatile_threshold', 0.04)
    atr_volatile_threshold = params.get('atr_volatile_threshold', 0.015)

    close = df['close']

    # Minimum data guard
    min_bars = max(adx_period * 3, bb_period + 5)
    if len(df) < min_bars:
        return {
            'regime': 'UNKNOWN',
            'adx': 0.0,
            'bb_width': 0.0,
            'atr_ratio': 0.0,
            'confidence': 0.0,
            'ema_direction': 'UP',
        }

    # 1. ADX ---------------------------------------------------------------
    adx = _compute_adx(df, adx_period)
    adx_val = adx.iloc[-1]

    # 2. Bollinger Bandwidth (% of middle band) ----------------------------
    bb_mid = close.rolling(bb_period).mean()
    bb_std_val = close.rolling(bb_period).std()
    bb_upper = bb_mid + bb_std * bb_std_val
    bb_lower = bb_mid - bb_std * bb_std_val
    bb_mid_last = bb_mid.iloc[-1]
    if pd.isna(bb_mid_last) or bb_mid_last == 0:
        bb_width = 0.0
    else:
        bb_width = ((bb_upper - bb_lower) / bb_mid).iloc[-1]

    # 3. ATR ratio (normalised volatility) ---------------------------------
    atr_series = _compute_atr(df, 14)
    close_last = close.iloc[-1]
    if close_last > 0 and not pd.isna(atr_series.iloc[-1]):
        atr_ratio = atr_series.iloc[-1] / close_last
    else:
        atr_ratio = 0.0

    # 4. EMA direction (fast vs slow) --------------------------------------
    ema_fast = close.ewm(span=8, adjust=False).mean().iloc[-1]
    ema_slow = close.ewm(span=34, adjust=False).mean().iloc[-1]
    ema_direction = 'UP' if ema_fast > ema_slow else 'DOWN'

    # 5. Classification logic ----------------------------------------------
    if not pd.isna(adx_val) and adx_val > adx_trend_threshold:
        regime = 'TRENDING_UP' if ema_direction == 'UP' else 'TRENDING_DOWN'
        confidence = min((adx_val - adx_trend_threshold) / 25.0, 1.0)
    elif (not pd.isna(adx_val) and adx_val < adx_range_threshold
          and not pd.isna(bb_width) and bb_width < bb_range_threshold):
        regime = 'RANGING'
        confidence = min((adx_range_threshold - adx_val) / 10.0, 1.0)
    elif atr_ratio > atr_volatile_threshold or (not pd.isna(bb_width) and bb_width > bb_volatile_threshold):
        regime = 'VOLATILE'
        confidence = min(atr_ratio / 0.02, 1.0)
    else:
        regime = 'UNKNOWN'
        confidence = 0.3

    return {
        'regime': regime,
        'adx': float(adx_val) if not pd.isna(adx_val) else 0.0,
        'bb_width': float(bb_width) if not pd.isna(bb_width) else 0.0,
        'atr_ratio': float(atr_ratio) if not pd.isna(atr_ratio) else 0.0,
        'confidence': float(confidence),
        'ema_direction': ema_direction,
    }


# ---------------------------------------------------------------------------
# Pair scanning (called by Celery)
# ---------------------------------------------------------------------------

FOREX_PAIRS = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD',
    'NZDUSD', 'USDCAD', 'USDCHF',
]


def scan_all_pairs():
    """Scan all forex pairs and classify their market regime.

    Stores results in the MarketRegime model so that other modules
    (entry dispatcher, AI brain, dashboard) can query the latest regime
    without re-computing.

    Intended to be called by a Celery periodic task every ~5 minutes.
    """
    from app.nexus.models import MarketRegime

    for pair in FOREX_PAIRS:
        try:
            df = fetch_data_pos(pair, MT5Timeframe.H1, 100)
            if df is None or len(df) < 50:
                logger.warning(f"Regime scan: skipping {pair} — insufficient data.")
                continue

            result = classify_regime(df)

            MarketRegime.objects.update_or_create(
                symbol=pair,
                timeframe='H1',
                defaults={
                    'regime': result['regime'],
                    'adx': result['adx'],
                    'bb_width': result['bb_width'],
                    'atr_ratio': result['atr_ratio'],
                    'confidence': result['confidence'],
                },
            )
            logger.info(
                f"Regime scan: {pair} = {result['regime']} "
                f"(ADX={result['adx']:.1f}, conf={result['confidence']:.2f})"
            )
        except Exception as e:
            logger.error(f"Regime scan failed for {pair}: {e}")

    # HMM regime scan (data-driven, runs alongside rule-based)
    try:
        from app.quant.ml.regime_hmm import scan_all_hmm_regimes
        scan_all_hmm_regimes(FOREX_PAIRS, fetch_data_pos, MT5Timeframe.H1)
    except Exception as e:
        logger.debug(f"HMM regime scan skipped: {e}")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_regime_for_pair(symbol):
    """Return the cached regime string for *symbol*, or ``'UNKNOWN'``.

    Only trusts results computed within the last 10 minutes to avoid
    acting on stale data.
    """
    from app.nexus.models import MarketRegime
    from django.utils import timezone
    from datetime import timedelta

    try:
        mr = MarketRegime.objects.get(symbol=symbol, timeframe='H1')
        if mr.computed_at > timezone.now() - timedelta(minutes=10):
            return mr.regime
    except MarketRegime.DoesNotExist:
        pass
    return 'UNKNOWN'


def get_dominant_regime():
    """Return the most common regime across all recently scanned pairs.

    Useful for strategy-level filtering (e.g. disable mean-reversion
    strategies when the dominant regime is TRENDING).
    """
    from app.nexus.models import MarketRegime
    from django.utils import timezone
    from datetime import timedelta
    from collections import Counter

    cutoff = timezone.now() - timedelta(minutes=10)
    regimes = list(
        MarketRegime.objects.filter(computed_at__gt=cutoff)
        .values_list('regime', flat=True)
    )
    if not regimes:
        return 'UNKNOWN'
    counter = Counter(regimes)
    return counter.most_common(1)[0][0]

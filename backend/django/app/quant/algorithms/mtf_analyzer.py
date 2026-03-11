"""
Multi-Timeframe Analyzer — HTF bias detection for confluence scoring.

ICT principle: NEVER trade against higher-timeframe structure.
The HTF bias is worth 2 points in the confluence scorer (the most
valuable single factor alongside CVD divergence and liquidity sweeps).

Current scope: HTF bias via H4 EMA alignment + swing structure.
Future: full MTF (H1/M15 structure) + LTF (M5 entry timing).

Timeframe mapping:
  HTF = H4    (bias determination — 100 bars = ~17 trading days)
  MTF = M15   (structure & setup — future)
  LTF = M5    (entry timing — future)

Livermore: "The big money is made by watching the big swings."
HTF bias IS the big swing.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('mtf_analyzer')


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HTFBias:
    """Higher-timeframe directional bias."""
    bias: str = 'neutral'           # 'bullish', 'bearish', 'neutral'
    confidence: float = 0.0         # 0.0 - 1.0
    ema_direction: str = 'neutral'  # 'bullish', 'bearish', 'neutral'
    swing_structure: str = 'mixed'  # 'HH_HL', 'LH_LL', 'mixed'
    premium_discount: str = ''      # 'premium', 'discount', 'equilibrium'
    previous_day_high: float = 0.0
    previous_day_low: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_htf_bias(symbol: str, fetch_fn=None) -> HTFBias:
    """Get the higher-timeframe directional bias for a symbol.

    Uses H4 data: EMA alignment + swing structure + premium/discount zone.

    Args:
        symbol: Trading pair (e.g. 'EURUSD')
        fetch_fn: Function(symbol, timeframe, bars) -> DataFrame.
                  If None, uses fetch_data_pos.

    Returns:
        HTFBias with directional assessment.
        On any error, returns neutral bias (fail-open).
    """
    try:
        if fetch_fn is None:
            from app.utils.api.data import fetch_data_pos
            from app.utils.constants import MT5Timeframe
            fetch_fn = fetch_data_pos
            timeframe = MT5Timeframe.H4
        else:
            from app.utils.constants import MT5Timeframe
            timeframe = MT5Timeframe.H4

        df = fetch_fn(symbol, timeframe, 100)
        if df is None or len(df) < 30:
            logger.debug(f"HTF bias {symbol}: insufficient H4 data ({len(df) if df is not None else 0} bars)")
            return HTFBias()

        return _analyze_htf_bias(df)

    except Exception as e:
        logger.debug(f"HTF bias detection failed for {symbol}: {e}")
        return HTFBias()


def get_htf_bias_string(symbol: str, fetch_fn=None) -> Optional[str]:
    """Convenience: return just the bias string for the confluence scorer.

    Returns 'bullish', 'bearish', or None (neutral treated as None to
    not penalize in confluence scoring).
    """
    result = get_htf_bias(symbol, fetch_fn)
    if result.bias in ('bullish', 'bearish'):
        return result.bias
    return None


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _analyze_htf_bias(df: pd.DataFrame) -> HTFBias:
    """Analyze H4 data for directional bias.

    Three-signal voting system:
    1. EMA alignment (8 vs 34) — momentum direction
    2. Swing structure (HH/HL vs LH/LL) — price structure
    3. Premium/discount zone — mean reversion context

    Bias is set when at least 2 of 3 signals agree.
    Confidence scales with signal agreement and EMA separation.
    """
    result = HTFBias()

    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)

    # --- Signal 1: EMA alignment ---
    close_series = pd.Series(close)
    ema_fast = close_series.ewm(span=8, adjust=False).mean().iloc[-1]
    ema_slow = close_series.ewm(span=34, adjust=False).mean().iloc[-1]

    ema_separation = abs(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0

    if ema_fast > ema_slow * 1.0005:  # Small threshold to filter noise
        result.ema_direction = 'bullish'
    elif ema_fast < ema_slow * 0.9995:
        result.ema_direction = 'bearish'
    else:
        result.ema_direction = 'neutral'

    # --- Signal 2: Swing structure ---
    swing_highs, swing_lows = _find_swings(high, low, lookback=5)

    sh_prices = [high[i] for i in swing_highs[-4:]] if swing_highs else []
    sl_prices = [low[i] for i in swing_lows[-4:]] if swing_lows else []

    swing_bias = 'mixed'
    if len(sh_prices) >= 2 and len(sl_prices) >= 2:
        hh = sh_prices[-1] > sh_prices[-2]
        hl = sl_prices[-1] > sl_prices[-2]
        if hh and hl:
            swing_bias = 'HH_HL'
        elif not hh and not hl:
            swing_bias = 'LH_LL'
    result.swing_structure = swing_bias

    # --- Signal 3: Premium/discount zone ---
    recent_high = float(high[-50:].max()) if len(high) >= 50 else float(high.max())
    recent_low = float(low[-50:].min()) if len(low) >= 50 else float(low.min())
    midpoint = (recent_high + recent_low) / 2
    current_price = close[-1]

    result.previous_day_high = recent_high
    result.previous_day_low = recent_low

    if current_price > midpoint:
        result.premium_discount = 'premium'
    elif current_price < midpoint:
        result.premium_discount = 'discount'
    else:
        result.premium_discount = 'equilibrium'

    # --- Vote counting ---
    bullish_votes = 0
    bearish_votes = 0

    if result.ema_direction == 'bullish':
        bullish_votes += 1
    elif result.ema_direction == 'bearish':
        bearish_votes += 1

    if swing_bias == 'HH_HL':
        bullish_votes += 1
    elif swing_bias == 'LH_LL':
        bearish_votes += 1

    # Premium/discount is a contrarian signal:
    # discount zone = more room for bullish, premium = more room for bearish
    # But for trend following, we want price in discount for buys (trend pullback)
    # We DON'T add it as a vote — it's used for confidence modulation only

    # --- Final bias ---
    if bullish_votes >= 2:
        result.bias = 'bullish'
        result.confidence = min(0.5 + ema_separation * 50, 1.0)
    elif bearish_votes >= 2:
        result.bias = 'bearish'
        result.confidence = min(0.5 + ema_separation * 50, 1.0)
    elif bullish_votes == 1 and bearish_votes == 0:
        result.bias = 'bullish'
        result.confidence = 0.3 + ema_separation * 30
    elif bearish_votes == 1 and bullish_votes == 0:
        result.bias = 'bearish'
        result.confidence = 0.3 + ema_separation * 30
    else:
        result.bias = 'neutral'
        result.confidence = 0.2

    # Confidence boost if price is in the right zone for the bias
    if result.bias == 'bullish' and result.premium_discount == 'discount':
        result.confidence = min(result.confidence + 0.15, 1.0)
    elif result.bias == 'bearish' and result.premium_discount == 'premium':
        result.confidence = min(result.confidence + 0.15, 1.0)

    logger.debug(
        f"HTF bias {result.bias} (conf={result.confidence:.2f}): "
        f"EMA={result.ema_direction}, swing={result.swing_structure}, "
        f"zone={result.premium_discount}"
    )

    return result


def _find_swings(high: np.ndarray, low: np.ndarray, lookback: int = 5):
    """Find swing high and swing low indices.

    A swing high at index i means high[i] is the maximum in the window
    [i-lookback, i+lookback]. Similarly for swing lows.

    Returns (swing_high_indices, swing_low_indices) as lists of int.
    """
    n = len(high)
    sh_indices = []
    sl_indices = []

    for i in range(lookback, n - lookback):
        window_h = high[i - lookback:i + lookback + 1]
        if high[i] == window_h.max() and np.sum(window_h == high[i]) == 1:
            sh_indices.append(i)

        window_l = low[i - lookback:i + lookback + 1]
        if low[i] == window_l.min() and np.sum(window_l == low[i]) == 1:
            sl_indices.append(i)

    return sh_indices, sl_indices

"""
Feature extraction for ML trade scoring — research-backed feature engineering.

Upgrades from v1:
- Cyclical time encoding (sin/cos) so the model knows hour 23 ≈ hour 0
- Fractional differentiation (d=0.4) for stationarity with memory preservation
- Garman-Klass volatility estimator (more efficient than close-to-close)
- Multi-horizon volatility ratio for regime detection
- HMM regime state (data-driven vs rule-based)

Reference: Lopez de Prado, "Advances in Financial Machine Learning" (2018)
"""

import logging
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone as tz

logger = logging.getLogger('app.quant.ml')

# Feature names in fixed order — model depends on this ordering
FEATURE_NAMES = [
    # Temporal (cyclical encoding — captures circular nature of time)
    'hour_sin',             # sin(2π * hour / 24)
    'hour_cos',             # cos(2π * hour / 24)
    'dow_sin',              # sin(2π * weekday / 5)
    'dow_cos',              # cos(2π * weekday / 5)
    'session',              # 0=Asian, 1=London, 2=NY, 3=London_NY_overlap
    'minutes_into_session',

    # Symbol & direction
    'symbol_id',            # Label-encoded symbol
    'order_direction',      # 1=BUY, -1=SELL

    # Technical indicators (classic)
    'atr_normalized',       # ATR / close price
    'rsi',
    'ema_alignment',        # (EMA8 - EMA21) / EMA21
    'bb_width',             # 2σ / SMA20
    'adx',

    # Volatility regime (new — captures vol structure)
    'frac_diff_close',      # Fractionally differentiated close (d=0.4)
    'vol_ratio',            # ATR(5) / ATR(21) — regime transition detector
    'realized_vol',         # 21-bar realized volatility of returns
    'garman_klass_vol',     # Garman-Klass OHLC vol estimator

    # Market regime
    'regime_encoded',       # -1=DOWN, 0=RANGING, 1=UP, 2=VOLATILE
    'regime_confidence',
    'hmm_regime',           # HMM-predicted regime (0/1/2), -1 if unavailable

    # Macro context
    'macro_risk_level',
    'macro_avoid',          # 0/1
    'macro_bias_aligned',   # 1=aligned, 0=neutral, -1=opposing

    # Performance context
    'recent_streak',        # Positive = wins, negative = losses
    'symbol_wr_10',         # Win rate on this symbol, last 10 trades
    'strategy_wr_20',       # Win rate for this strategy, last 20 trades
    'drawdown_pct',         # Current drawdown as % of peak
    'positions_open',       # Number of currently open positions

    # Trade quality
    'spread_atr_ratio',     # Spread / ATR
    'signal_strength',      # Strategy-specific signal strength (0-1)
]

# Selected features for ML model — reduced from 30 to 8 per the
# "one-in-ten" rule (need ~10 samples per feature to avoid overfitting).
# Full 30 features still extracted into features_json for LLM training data.
# Expand this list gradually as labeled trade count grows past 100, 200, etc.
SELECTED_FEATURES = [
    'session',           # Session timing is the strongest predictor
    'order_direction',   # Core signal direction
    'atr_normalized',    # Volatility context for entry quality
    'rsi',               # Momentum / overbought-oversold
    'vol_ratio',         # ATR(5)/ATR(21) — regime transition detector
    'spread_atr_ratio',  # Trade cost quality (high spread = bad entry)
    'symbol_wr_10',      # Recent symbol performance
    'recent_streak',     # Win/loss momentum
]

SYMBOL_ENCODING = {
    'EURUSD': 0, 'GBPUSD': 1, 'USDJPY': 2, 'AUDUSD': 3,
    'NZDUSD': 4, 'USDCAD': 5, 'USDCHF': 6,
}


# ---------------------------------------------------------------------------
# Advanced feature computation (Lopez de Prado-inspired)
# ---------------------------------------------------------------------------

def frac_diff(series, d=0.4, thresh=1e-5):
    """Fractionally differentiate a time series.

    Achieves stationarity (d=1 is too aggressive, destroys memory)
    while preserving long-range dependence (d=0 is raw, non-stationary).
    d ≈ 0.4 is the empirically optimal sweet spot for financial series.

    Reference: AFML Chapter 5, "Fractionally Differentiated Features"
    """
    vals = series.values if hasattr(series, 'values') else np.array(series)
    n = len(vals)
    # Compute weights using the recursive formula
    weights = [1.0]
    for k in range(1, n):
        w = -weights[-1] * (d - k + 1) / k
        if abs(w) < thresh:
            break
        weights.append(w)
    weights = np.array(weights[::-1])
    width = len(weights)

    result = np.full(n, np.nan)
    for t in range(width - 1, n):
        result[t] = np.dot(weights, vals[t - width + 1:t + 1])
    return result


def garman_klass_volatility(df, window=21):
    """Garman-Klass volatility estimator using OHLC data.

    More efficient than close-to-close vol because it uses
    intraday high-low range information. Approximately 5x more
    efficient (in statistical terms) than simple vol.

    Reference: Garman & Klass (1980), "On the Estimation of Security Price
    Volatilities from Historical Data"
    """
    log_hl_sq = np.log(df['high'] / df['low']) ** 2
    log_co_sq = np.log(df['close'] / df['open']) ** 2
    gk = 0.5 * log_hl_sq - (2 * math.log(2) - 1) * log_co_sq
    return np.sqrt(gk.rolling(window, min_periods=5).mean())


def classify_session(hour):
    """Classify the trading session from UTC hour."""
    if 0 <= hour < 7:
        return 0  # Asian
    elif 7 <= hour < 13:
        return 1  # London
    elif 13 <= hour < 17:
        return 3  # London-NY overlap
    elif 17 <= hour < 22:
        return 2  # NY
    else:
        return 0  # Late Asian / off-hours


# ---------------------------------------------------------------------------
# Main feature extraction
# ---------------------------------------------------------------------------

def extract_features(
    symbol,
    order_type,
    df,
    atr_val,
    strategy_config=None,
    custom_strategy=None,
    tick_info=None,
):
    """Extract a 30-feature vector from current market state.

    Combines classic technical indicators with research-backed features:
    cyclical time encoding, fractional differentiation, Garman-Klass
    volatility, multi-horizon vol ratios, and HMM regime states.
    """
    try:
        now = datetime.now(tz.utc)
        close_price = df['close'].iloc[-1]

        features = {}

        # --- Temporal features (cyclical encoding) ---
        features['hour_sin'] = math.sin(2 * math.pi * now.hour / 24)
        features['hour_cos'] = math.cos(2 * math.pi * now.hour / 24)
        features['dow_sin'] = math.sin(2 * math.pi * now.weekday() / 5)
        features['dow_cos'] = math.cos(2 * math.pi * now.weekday() / 5)
        features['session'] = classify_session(now.hour)
        session_starts = {0: 0, 1: 7, 2: 17, 3: 13}
        features['minutes_into_session'] = (
            (now.hour - session_starts.get(features['session'], 0)) * 60 + now.minute
        )

        # --- Symbol and direction ---
        features['symbol_id'] = SYMBOL_ENCODING.get(symbol, len(SYMBOL_ENCODING))
        features['order_direction'] = 1 if order_type == 'BUY' else -1

        # --- Technical indicators ---
        features['atr_normalized'] = float(atr_val / close_price) if close_price > 0 else 0.0

        if 'RSI' in df.columns and not pd.isna(df['RSI'].iloc[-1]):
            features['rsi'] = float(df['RSI'].iloc[-1])
        else:
            features['rsi'] = 50.0

        ema_fast = df['close'].ewm(span=8, adjust=False).mean().iloc[-1]
        ema_slow = df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
        features['ema_alignment'] = float((ema_fast - ema_slow) / ema_slow) if ema_slow > 0 else 0.0

        bb_mid = df['close'].rolling(20).mean().iloc[-1]
        bb_std = df['close'].rolling(20).std().iloc[-1]
        if not pd.isna(bb_mid) and bb_mid > 0 and not pd.isna(bb_std):
            features['bb_width'] = float(2 * bb_std / bb_mid)
        else:
            features['bb_width'] = 0.0

        features['adx'] = (
            float(df['ADX'].iloc[-1])
            if 'ADX' in df.columns and not pd.isna(df['ADX'].iloc[-1])
            else 20.0
        )

        # --- Volatility regime features (new) ---
        # Fractional differentiation of close price
        if len(df) >= 20:
            fd = frac_diff(df['close'], d=0.4)
            last_fd = fd[-1] if not np.isnan(fd[-1]) else 0.0
            # Normalize by close price for cross-pair comparability
            features['frac_diff_close'] = float(last_fd / close_price) if close_price > 0 else 0.0
        else:
            features['frac_diff_close'] = 0.0

        # ATR ratio: short-term / long-term volatility
        if len(df) >= 21:
            from app.quant.indicators.scalping import atr as compute_atr
            atr_5 = compute_atr(df, period=5).iloc[-1]
            atr_21 = compute_atr(df, period=21).iloc[-1]
            if not pd.isna(atr_5) and not pd.isna(atr_21) and atr_21 > 0:
                features['vol_ratio'] = float(atr_5 / atr_21)
            else:
                features['vol_ratio'] = 1.0
        else:
            features['vol_ratio'] = 1.0

        # Realized volatility (21-bar rolling std of log returns)
        if len(df) >= 21:
            log_returns = np.log(df['close'] / df['close'].shift(1))
            rv = log_returns.rolling(21).std().iloc[-1]
            features['realized_vol'] = float(rv) if not pd.isna(rv) else 0.0
        else:
            features['realized_vol'] = 0.0

        # Garman-Klass OHLC volatility
        if len(df) >= 21 and all(c in df.columns for c in ['open', 'high', 'low', 'close']):
            gk = garman_klass_volatility(df, window=21)
            gk_val = gk.iloc[-1]
            features['garman_klass_vol'] = float(gk_val) if not pd.isna(gk_val) else 0.0
        else:
            features['garman_klass_vol'] = 0.0

        # --- Market regime ---
        regime_data = _get_regime(symbol)
        features['regime_encoded'] = regime_data['encoded']
        features['regime_confidence'] = regime_data['confidence']

        # HMM regime (data-driven)
        features['hmm_regime'] = _get_hmm_regime(symbol)

        # --- Macro context ---
        macro = _get_macro_context()
        features['macro_risk_level'] = macro['risk_level']
        features['macro_avoid'] = macro['avoid']
        features['macro_bias_aligned'] = _check_macro_alignment(symbol, order_type, macro)

        # --- Performance context ---
        perf = _get_performance_context(symbol, strategy_config)
        features['recent_streak'] = perf['streak']
        features['symbol_wr_10'] = perf['symbol_wr']
        features['strategy_wr_20'] = perf['strategy_wr']
        features['drawdown_pct'] = perf['drawdown_pct']
        features['positions_open'] = perf['positions_open']

        # --- Trade cost ---
        if tick_info is not None and not tick_info.empty:
            spread = tick_info['ask'].iloc[0] - tick_info['bid'].iloc[0]
            features['spread_atr_ratio'] = float(spread / atr_val) if atr_val > 0 else 0.0
        else:
            features['spread_atr_ratio'] = 0.0

        # --- Signal strength ---
        if 'CVD' in df.columns and not pd.isna(df['CVD'].iloc[-1]):
            cvd_val = abs(float(df['CVD'].iloc[-1]))
            features['signal_strength'] = min(cvd_val / 100.0, 1.0)
        else:
            features['signal_strength'] = 0.5

        return features

    except Exception as e:
        logger.error(f"Feature extraction failed: {e}")
        return None


def features_to_array(features_dict):
    """Convert feature dict to numpy array using SELECTED_FEATURES only.

    Uses the reduced 8-feature subset for ML model training/scoring.
    The full 30-feature dict is preserved in features_json for LLM data.
    """
    return np.array([features_dict.get(name, 0.0) for name in SELECTED_FEATURES], dtype=np.float64)


# ---------------------------------------------------------------------------
# Helper data lookups
# ---------------------------------------------------------------------------

def _get_regime(symbol):
    """Get market regime for a symbol."""
    try:
        from app.nexus.models import MarketRegime
        mr = MarketRegime.objects.filter(symbol=symbol).first()
        if mr:
            encoding = {
                'TRENDING_UP': 1, 'TRENDING_DOWN': -1,
                'RANGING': 0, 'VOLATILE': 2, 'UNKNOWN': 0,
            }
            return {
                'encoded': encoding.get(mr.regime, 0),
                'confidence': float(mr.confidence) if mr.confidence else 0.5,
            }
    except Exception:
        pass
    return {'encoded': 0, 'confidence': 0.5}


def _get_hmm_regime(symbol):
    """Get HMM-predicted regime from cache. Returns -1 if unavailable."""
    try:
        from django.core.cache import cache
        state = cache.get(f'hmm_regime:{symbol}')
        if state is not None:
            return int(state)
    except Exception:
        pass
    return -1  # Not available


def _get_macro_context():
    """Get current macro analysis context."""
    try:
        from django.core.cache import cache
        macro = cache.get('macro:analysis')
        if macro:
            return {
                'risk_level': macro.get('risk_level', 5),
                'avoid': 1 if macro.get('avoid_trading', False) else 0,
                'currency_bias': macro.get('currency_bias', {}),
            }
    except Exception:
        pass
    return {'risk_level': 5, 'avoid': 0, 'currency_bias': {}}


def _check_macro_alignment(symbol, order_type, macro):
    """Check if trade direction aligns with macro bias. Returns -1, 0, or 1."""
    try:
        bias = macro.get('currency_bias', {})
        base = symbol[:3]
        base_info = bias.get(base, {})
        direction = base_info.get('direction', 'neutral')
        confidence = base_info.get('confidence', 0)

        if confidence < 5:
            return 0

        if order_type == 'BUY' and direction == 'bullish':
            return 1
        elif order_type == 'BUY' and direction == 'bearish':
            return -1
        elif order_type == 'SELL' and direction == 'bearish':
            return 1
        elif order_type == 'SELL' and direction == 'bullish':
            return -1
    except Exception:
        pass
    return 0


def _get_performance_context(symbol, strategy_config):
    """Get recent performance metrics."""
    result = {
        'streak': 0,
        'symbol_wr': 0.5,
        'strategy_wr': 0.5,
        'drawdown_pct': 0.0,
        'positions_open': 0,
    }
    try:
        from app.nexus.models import Trade
        from app.utils.api.positions import get_positions

        recent = Trade.objects.filter(
            close_time__isnull=False, pnl__isnull=False,
        ).order_by('-close_time')[:10]
        streak = 0
        for t in recent:
            if t.pnl > 0:
                if streak >= 0:
                    streak += 1
                else:
                    break
            else:
                if streak <= 0:
                    streak -= 1
                else:
                    break
        result['streak'] = streak

        sym_trades = Trade.objects.filter(
            symbol=symbol, close_time__isnull=False, pnl__isnull=False,
        ).order_by('-close_time')[:10]
        sym_pnls = [t.pnl for t in sym_trades]
        if sym_pnls:
            result['symbol_wr'] = sum(1 for p in sym_pnls if p > 0) / len(sym_pnls)

        if strategy_config:
            strat_trades = Trade.objects.filter(
                strategy_config=strategy_config,
                close_time__isnull=False, pnl__isnull=False,
            ).order_by('-close_time')[:20]
            strat_pnls = [t.pnl for t in strat_trades]
            if strat_pnls:
                result['strategy_wr'] = sum(1 for p in strat_pnls if p > 0) / len(strat_pnls)

        all_pnls = Trade.objects.filter(
            close_time__isnull=False, pnl__isnull=False,
        ).order_by('close_time').values_list('pnl', flat=True)
        cumulative = 0.0
        peak = 0.0
        for pnl in all_pnls:
            cumulative += pnl
            peak = max(peak, cumulative)
        result['drawdown_pct'] = ((peak - cumulative) / peak * 100) if peak > 0 else 0.0

        positions = get_positions()
        result['positions_open'] = len(positions) if positions is not None and not positions.empty else 0

    except Exception as e:
        logger.debug(f"Performance context error: {e}")

    return result

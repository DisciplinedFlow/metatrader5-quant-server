"""
HMM Regime Detection — data-driven market state classification.

Enhanced from v1:
- 4 observation features: log returns, rolling vol, Bollinger bandwidth, ADX normalized
- 1000 EM iterations for stable convergence
- Model caching in Redis (1h TTL) — avoids refitting every scan cycle
- Explicit state labeling based on mean return + variance per state
- Confidence scoring via posterior probabilities
- ATR percentile fallback — top 5th percentile overrides to VOLATILE
- Cross-pair consensus with leader-weighting (EURUSD/GBPUSD get 2x weight)

Reference: Hamilton (1989), "A New Approach to the Economic Analysis
of Nonstationary Time Series and the Business Cycle"
QuantStart HMM Study: 57% drawdown reduction with regime filtering.
"""

import json
import logging
import time

import numpy as np
import pandas as pd

logger = logging.getLogger('app.quant.ml')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_STATES = 3
MIN_BARS = 60                # MT5 API returns max 100 bars; ~60 usable after warmup
EM_ITERATIONS = 1000          # Full convergence (research recommendation)
REFIT_INTERVAL_SECONDS = 3600 # Refit model every hour
ATR_VOLATILE_PERCENTILE = 95  # Top 5th percentile ATR forces VOLATILE
CACHE_TTL = 3600              # 1 hour TTL for model cache
DETAIL_CACHE_TTL = 600        # 10 min TTL for detail/consensus results

# State labels
LABEL_TRENDING = 'TRENDING'
LABEL_RANGING = 'RANGING'
LABEL_VOLATILE = 'VOLATILE'
LABEL_UNKNOWN = 'UNKNOWN'

# Leader pairs get 2x weight in consensus (Livermore: group leaders matter)
# XAUUSD added as commodity leader — gold telegraphs risk sentiment
CONSENSUS_LEADERS = {'EURUSD', 'GBPUSD', 'XAUUSD'}
LEADER_WEIGHT = 2


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _compute_features(df):
    """Build the 4-feature observation matrix from OHLCV data.

    Features:
        1. Log returns — price momentum signal
        2. Rolling volatility — 20-bar rolling std of log returns
        3. Bollinger bandwidth — (upper - lower) / middle, normalized squeeze measure
        4. ADX normalized — ADX / 100, directional strength [0, 1]

    All features are z-score normalized for stable HMM fitting.

    Returns:
        np.ndarray of shape (n_obs, 4), or None if insufficient data.
    """
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)

    n = len(close)
    if n < MIN_BARS:
        return None

    # Feature 1: Log returns
    log_returns = np.diff(np.log(close))

    # Feature 2: 20-bar rolling volatility of log returns
    vol_window = 20
    rolling_vol = np.full(len(log_returns), np.nan)
    for i in range(len(log_returns)):
        start = max(0, i - vol_window + 1)
        rolling_vol[i] = np.std(log_returns[start:i + 1])

    # Feature 3: Bollinger bandwidth (20-period)
    bb_period = 20
    bb_std_mult = 2.0
    close_series = pd.Series(close)
    bb_mid = close_series.rolling(bb_period).mean()
    bb_std = close_series.rolling(bb_period).std()
    bb_upper = bb_mid + bb_std_mult * bb_std
    bb_lower = bb_mid - bb_std_mult * bb_std
    bb_width = ((bb_upper - bb_lower) / bb_mid).values
    # Align with log_returns (which has n-1 elements)
    bb_width = bb_width[1:]

    # Feature 4: ADX normalized (0-1 range)
    adx_period = 14
    df_copy = df.copy()
    adx_series = _compute_adx_fast(df_copy, adx_period)
    adx_norm = (adx_series / 100.0).values
    adx_norm = adx_norm[1:]  # Align with log_returns

    # Stack all features
    X = np.column_stack([log_returns, rolling_vol, bb_width, adx_norm])

    # Remove rows with NaN/inf
    mask = np.isfinite(X).all(axis=1)
    X = X[mask]

    if len(X) < MIN_BARS // 2:
        return None

    # Z-score normalize each feature for stable HMM fitting
    means = X.mean(axis=0)
    stds = X.std(axis=0)
    stds[stds == 0] = 1.0  # Prevent division by zero
    X = (X - means) / stds

    return X


def _compute_adx_fast(df, period=14):
    """Compute ADX from DataFrame. Self-contained to avoid circular imports."""
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr = pd.Series(tr, index=df.index).ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / period, min_periods=period
    ).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / period, min_periods=period
    ).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return adx


def _compute_atr_percentile(df, lookback=200, percentile=ATR_VOLATILE_PERCENTILE):
    """Check if current ATR is above the given percentile over lookback bars.

    Returns (is_extreme: bool, current_pct: float).
    """
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    close = df['close'].values.astype(float)

    # True Range
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )

    # Use last `lookback` bars of TR
    tr = tr[-lookback:] if len(tr) > lookback else tr
    if len(tr) < 50:
        return False, 50.0

    # EMA-smoothed ATR (14-period)
    atr_values = pd.Series(tr).ewm(span=14, adjust=False).mean().values
    current_atr = atr_values[-1]
    pct = float(np.percentile(atr_values, percentile))
    current_pct = float(
        np.searchsorted(np.sort(atr_values), current_atr) / len(atr_values) * 100
    )

    return current_atr >= pct, current_pct


# ---------------------------------------------------------------------------
# State labeling
# ---------------------------------------------------------------------------

def _label_states(model, X, states, n_states):
    """Analyze mean returns + variance per state to assign labels.

    Logic:
    - State with highest variance in vol feature -> VOLATILE
    - Among remaining, state with highest abs(mean return) + ADX -> TRENDING
    - Remaining state -> RANGING

    Returns:
        dict mapping raw_state_int -> label_string
    """
    labels = {}
    state_stats = {}

    for s in range(n_states):
        mask = states == s
        if not mask.any():
            state_stats[s] = {'mean_ret': 0.0, 'var_vol': 0.0, 'count': 0}
            continue
        state_data = X[mask]
        state_stats[s] = {
            'mean_ret': float(np.mean(state_data[:, 0])),      # Mean log return
            'var_vol': float(np.var(state_data[:, 1])),         # Variance of vol feature
            'mean_vol': float(np.mean(state_data[:, 1])),       # Mean of vol feature
            'mean_adx': float(np.mean(state_data[:, 3])),       # Mean ADX normalized
            'count': int(mask.sum()),
        }

    if not state_stats:
        return {s: LABEL_UNKNOWN for s in range(n_states)}

    # Step 1: Highest vol variance -> VOLATILE
    volatile_state = max(state_stats.keys(), key=lambda s: state_stats[s]['var_vol'])
    labels[volatile_state] = LABEL_VOLATILE

    # Step 2: Among remaining, highest abs(mean_return) + high ADX -> TRENDING
    remaining = [s for s in range(n_states) if s != volatile_state]
    if remaining:
        trending_state = max(
            remaining,
            key=lambda s: abs(state_stats[s]['mean_ret']) + state_stats[s].get('mean_adx', 0),
        )
        labels[trending_state] = LABEL_TRENDING

        # Step 3: Whatever is left -> RANGING
        for s in remaining:
            if s not in labels:
                labels[s] = LABEL_RANGING

    return labels


def _determine_direction(df, states, label_map):
    """Determine trend direction based on EMA crossover for trending states.

    Returns 'UP', 'DOWN', or 'NEUTRAL'.
    """
    close = df['close'].values.astype(float)
    if len(close) < 34:
        return 'NEUTRAL'

    close_series = pd.Series(close)
    ema_fast = close_series.ewm(span=8, adjust=False).mean().iloc[-1]
    ema_slow = close_series.ewm(span=34, adjust=False).mean().iloc[-1]

    current_state = states[-1]
    current_label = label_map.get(current_state, LABEL_UNKNOWN)

    if current_label == LABEL_TRENDING:
        return 'UP' if ema_fast > ema_slow else 'DOWN'
    return 'NEUTRAL'


# ---------------------------------------------------------------------------
# Model caching
# ---------------------------------------------------------------------------

def _get_cached_model(symbol):
    """Retrieve a cached HMM model + metadata from Redis.

    Uses pickle because hmmlearn GaussianHMM objects contain numpy arrays
    and fitted parameters that cannot be JSON-serialized. The data is only
    written/read by our own Django/Celery processes, never from external input.

    Returns (model, metadata_dict) or (None, None) if cache miss / expired.
    """
    try:
        from django.core.cache import cache
        import pickle  # noqa: S403 — trusted internal data only

        cache_key = f'hmm_model:{symbol}'
        cached = cache.get(cache_key)
        if cached is not None:
            data = pickle.loads(cached)  # noqa: S301 — trusted internal data only
            fitted_at = data.get('fitted_at', 0)
            if time.time() - fitted_at < REFIT_INTERVAL_SECONDS:
                return data['model'], data['metadata']
    except Exception as e:
        logger.debug(f"HMM cache read failed for {symbol}: {e}")

    return None, None


def _cache_model(symbol, model, metadata):
    """Store a fitted HMM model + metadata in Redis with TTL.

    Uses pickle because hmmlearn GaussianHMM objects contain numpy arrays
    and fitted parameters that cannot be JSON-serialized. The data is only
    written/read by our own Django/Celery processes, never from external input.
    """
    try:
        from django.core.cache import cache
        import pickle  # noqa: S403 — trusted internal data only

        data = {
            'model': model,
            'metadata': metadata,
            'fitted_at': time.time(),
        }
        cache_key = f'hmm_model:{symbol}'
        cache.set(cache_key, pickle.dumps(data), timeout=CACHE_TTL)
    except Exception as e:
        logger.debug(f"HMM cache write failed for {symbol}: {e}")


# ---------------------------------------------------------------------------
# Core enhanced fitting
# ---------------------------------------------------------------------------

def fit_and_predict_enhanced(df, n_states=N_STATES, symbol=None):
    """Enhanced HMM fitting with 4-feature observations, model caching,
    explicit state labeling, confidence scoring, and ATR fallback.

    Args:
        df: OHLCV DataFrame with at least MIN_BARS rows.
        n_states: Number of hidden states (default 3).
        symbol: Symbol string for model caching (e.g. 'EURUSD').

    Returns:
        dict:
            - state: int (raw state number from sorted model)
            - label: str ('TRENDING', 'RANGING', 'VOLATILE')
            - confidence: float (posterior probability of assigned state)
            - direction: str ('UP', 'DOWN', 'NEUTRAL')
            - atr_override: bool (True if ATR percentile forced VOLATILE)
            - state_durations: dict {state_int: avg_consecutive_bars}
            - transition_matrix: list of lists (n_states x n_states)
        Returns None if fitting fails.
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        logger.debug("hmmlearn not installed, HMM regime unavailable")
        return None

    if df is None or len(df) < MIN_BARS:
        return None

    try:
        # Check for cached model first
        cached_model, cached_meta = (None, None)
        if symbol:
            cached_model, cached_meta = _get_cached_model(symbol)

        # Build observation matrix
        X = _compute_features(df)
        if X is None:
            return None

        if cached_model is not None:
            # Use cached model — just predict on new data
            model = cached_model
            logger.debug(f"HMM {symbol}: using cached model (fitted {cached_meta.get('bars_used', '?')} bars)")
        else:
            # Fit new model with 1000 EM iterations
            model = GaussianHMM(
                n_components=n_states,
                covariance_type='full',
                n_iter=EM_ITERATIONS,
                random_state=42,
                verbose=False,
                tol=1e-4,
            )
            model.fit(X)

            # Cache the fitted model
            if symbol:
                _cache_model(symbol, model, {
                    'bars_used': len(X),
                    'n_states': n_states,
                })
                logger.debug(f"HMM {symbol}: fitted new model on {len(X)} bars, cached for {REFIT_INTERVAL_SECONDS}s")

        # Predict hidden states
        states = model.predict(X)

        # Get posterior probabilities for confidence scoring
        posteriors = model.predict_proba(X)
        current_posterior = posteriors[-1]  # Last bar's posterior
        current_raw_state = states[-1]
        confidence = float(current_posterior[current_raw_state])

        # Label states by analyzing per-state statistics
        label_map = _label_states(model, X, states, n_states)

        current_label = label_map.get(current_raw_state, LABEL_UNKNOWN)

        # ATR percentile fallback — override to VOLATILE if extreme
        atr_override = False
        atr_extreme, atr_pct = _compute_atr_percentile(df)
        if atr_extreme and current_label != LABEL_VOLATILE:
            logger.debug(
                f"HMM {symbol}: ATR at {atr_pct:.0f}th percentile, "
                f"overriding {current_label} -> VOLATILE"
            )
            current_label = LABEL_VOLATILE
            atr_override = True

        # Determine trend direction
        direction = _determine_direction(df, states, label_map)

        # Compute average state durations (consecutive bars per state)
        state_durations = _compute_state_durations(states, n_states)

        # Extract transition matrix
        try:
            trans_matrix = model.transmat_.tolist()
        except Exception:
            trans_matrix = []

        return {
            'state': int(current_raw_state),
            'label': current_label,
            'confidence': round(confidence, 4),
            'direction': direction,
            'atr_override': atr_override,
            'state_durations': state_durations,
            'transition_matrix': trans_matrix,
        }

    except Exception as e:
        logger.warning(f"HMM enhanced fitting failed for {symbol}: {e}")
        return None


def _compute_state_durations(states, n_states):
    """Compute average consecutive bar duration per state."""
    durations = {s: [] for s in range(n_states)}
    if len(states) == 0:
        return {s: 0 for s in range(n_states)}

    current_state = states[0]
    run_length = 1

    for i in range(1, len(states)):
        if states[i] == current_state:
            run_length += 1
        else:
            durations[current_state].append(run_length)
            current_state = states[i]
            run_length = 1
    durations[current_state].append(run_length)

    return {
        s: round(np.mean(runs), 1) if runs else 0.0
        for s, runs in durations.items()
    }


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------

def fit_and_predict(df, n_states=N_STATES):
    """Backward-compatible wrapper: returns int state or -1.

    Matches the original v1 API signature so existing callers (features.py,
    data_collector.py) continue to work without changes.

    Args:
        df: OHLCV DataFrame with at least MIN_BARS rows
        n_states: Number of hidden states (default 3)

    Returns:
        int: Current regime state (0, 1, or 2), or -1 if fitting fails.
    """
    result = fit_and_predict_enhanced(df, n_states=n_states)
    if result is None:
        return -1
    return result['state']


# ---------------------------------------------------------------------------
# Cross-pair consensus
# ---------------------------------------------------------------------------

def get_cross_pair_regime_consensus(pair_results):
    """Compute cross-pair regime consensus with leader-weighting.

    EURUSD and GBPUSD get 2x weight in the vote (Livermore: leader stocks
    telegraph the market's true direction).

    Args:
        pair_results: dict of {symbol: result_dict} from fit_and_predict_enhanced

    Returns:
        dict:
            - dominant_regime: str (most common label by weighted vote)
            - consensus_pct: float (fraction of weighted votes for dominant)
            - per_pair: dict {symbol: label}
            - weighted_votes: dict {label: weighted_count}
    """
    if not pair_results:
        return {
            'dominant_regime': LABEL_UNKNOWN,
            'consensus_pct': 0.0,
            'per_pair': {},
            'weighted_votes': {},
        }

    weighted_votes = {}
    per_pair = {}
    total_weight = 0

    for symbol, result in pair_results.items():
        if result is None:
            continue
        label = result.get('label', LABEL_UNKNOWN)
        per_pair[symbol] = label
        weight = LEADER_WEIGHT if symbol in CONSENSUS_LEADERS else 1
        weighted_votes[label] = weighted_votes.get(label, 0) + weight
        total_weight += weight

    if not weighted_votes or total_weight == 0:
        return {
            'dominant_regime': LABEL_UNKNOWN,
            'consensus_pct': 0.0,
            'per_pair': per_pair,
            'weighted_votes': weighted_votes,
        }

    dominant_regime = max(weighted_votes, key=weighted_votes.get)
    consensus_pct = round(weighted_votes[dominant_regime] / total_weight, 4)

    return {
        'dominant_regime': dominant_regime,
        'consensus_pct': consensus_pct,
        'per_pair': per_pair,
        'weighted_votes': weighted_votes,
    }


# ---------------------------------------------------------------------------
# Scan entry point (called by regime.py scan_all_pairs)
# ---------------------------------------------------------------------------

def scan_all_hmm_regimes(pairs, fetch_fn, timeframe):
    """Scan HMM regimes for all pairs with enhanced detection and consensus.

    Caches three tiers of data in Redis:
    - hmm_regime:{symbol}         — int state (backward compat for features.py)
    - hmm_regime_detail:{symbol}  — full result dict (JSON)
    - hmm_regime_consensus        — cross-pair consensus dict (JSON)

    Args:
        pairs: List of symbol strings
        fetch_fn: Function(symbol, timeframe, bars) -> DataFrame
        timeframe: MT5Timeframe enum value

    Returns:
        dict: {symbol: result_dict} for all successfully scanned pairs
    """
    try:
        from django.core.cache import cache
    except ImportError:
        return {}

    pair_results = {}

    for symbol in pairs:
        try:
            df = fetch_fn(symbol, timeframe, max(MIN_BARS + 50, 300))
            if df is None or len(df) < MIN_BARS:
                logger.debug(f"HMM scan: skipping {symbol} — only {len(df) if df is not None else 0} bars")
                continue

            result = fit_and_predict_enhanced(df, n_states=N_STATES, symbol=symbol)
            if result is None:
                continue

            pair_results[symbol] = result

            # Cache tier 1: backward-compatible int state
            cache.set(f'hmm_regime:{symbol}', result['state'], timeout=DETAIL_CACHE_TTL)

            # Cache tier 2: full detail dict as JSON
            detail_json = json.dumps(result, default=str)
            cache.set(f'hmm_regime_detail:{symbol}', detail_json, timeout=DETAIL_CACHE_TTL)

            logger.debug(
                f"HMM regime {symbol}: {result['label']} "
                f"(state={result['state']}, conf={result['confidence']:.2f}, "
                f"dir={result['direction']}, atr_override={result['atr_override']})"
            )

        except Exception as e:
            logger.warning(f"HMM scan failed for {symbol}: {e}")

    # Cross-pair consensus
    if pair_results:
        consensus = get_cross_pair_regime_consensus(pair_results)
        try:
            cache.set(
                'hmm_regime_consensus',
                json.dumps(consensus, default=str),
                timeout=DETAIL_CACHE_TTL,
            )
        except Exception as e:
            logger.debug(f"HMM consensus cache failed: {e}")

        logger.info(
            f"HMM consensus: {consensus['dominant_regime']} "
            f"({consensus['consensus_pct']:.0%} agreement, "
            f"{len(pair_results)}/{len(pairs)} pairs scanned) "
            f"| per-pair: {consensus['per_pair']}"
        )

    return pair_results

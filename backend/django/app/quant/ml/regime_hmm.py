"""
HMM Regime Detection — data-driven market state classification.

Uses a Gaussian Hidden Markov Model to identify latent market regimes
from returns and volatility data. Unlike rule-based regime detection
(ADX > 25 = trending), HMMs discover regimes from the data itself.

Typically finds 3 states that map to:
- State 0: Low volatility / trending (quiet markets)
- State 1: Normal volatility / ranging
- State 2: High volatility / crisis (volatile regime)

The states are ordered by volatility (lowest to highest) after fitting.

Reference: Hamilton (1989), "A New Approach to the Economic Analysis
of Nonstationary Time Series and the Business Cycle"
"""

import logging
import numpy as np

logger = logging.getLogger('app.quant.ml')

N_STATES = 3
MIN_BARS = 100  # Minimum bars needed to fit HMM


def fit_and_predict(df, n_states=N_STATES):
    """Fit HMM on returns + volatility and predict current regime.

    Args:
        df: OHLCV DataFrame with at least MIN_BARS rows
        n_states: Number of hidden states (default 3)

    Returns:
        int: Current regime state (0=calm, 1=normal, 2=volatile),
             or -1 if fitting fails
    """
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        logger.debug("hmmlearn not installed, HMM regime unavailable")
        return -1

    if df is None or len(df) < MIN_BARS:
        return -1

    try:
        # Compute observation features: log returns + realized vol
        close = df['close'].values.astype(float)
        log_returns = np.diff(np.log(close))

        # 5-bar rolling vol of returns
        vol_window = 5
        rolling_vol = np.array([
            np.std(log_returns[max(0, i - vol_window):i]) if i >= vol_window else np.std(log_returns[:i + 1])
            for i in range(len(log_returns))
        ])

        # Stack into observation matrix [returns, vol]
        X = np.column_stack([log_returns, rolling_vol])

        # Remove NaN/inf
        mask = np.isfinite(X).all(axis=1)
        X = X[mask]

        if len(X) < MIN_BARS - 10:
            return -1

        # Fit HMM
        model = GaussianHMM(
            n_components=n_states,
            covariance_type='full',
            n_iter=50,
            random_state=42,
            verbose=False,
        )
        model.fit(X)

        # Predict hidden states
        states = model.predict(X)

        # Reorder states by volatility (mean of vol feature) so they're consistent
        state_vols = {}
        for s in range(n_states):
            state_mask = states == s
            if state_mask.any():
                state_vols[s] = X[state_mask, 1].mean()
            else:
                state_vols[s] = 0.0

        # Sort by volatility: 0=lowest vol, 2=highest vol
        sorted_states = sorted(state_vols.keys(), key=lambda s: state_vols[s])
        state_map = {old: new for new, old in enumerate(sorted_states)}

        current_raw_state = states[-1]
        return state_map.get(current_raw_state, -1)

    except Exception as e:
        logger.debug(f"HMM fitting failed: {e}")
        return -1


def scan_all_hmm_regimes(pairs, fetch_fn, timeframe):
    """Scan HMM regimes for all pairs and cache results.

    Args:
        pairs: List of symbol strings
        fetch_fn: Function(symbol, timeframe, bars) -> DataFrame
        timeframe: MT5Timeframe enum value
    """
    try:
        from django.core.cache import cache
    except ImportError:
        return

    for symbol in pairs:
        try:
            df = fetch_fn(symbol, timeframe, 200)
            if df is None or df.empty:
                continue

            state = fit_and_predict(df)
            if state >= 0:
                # Cache for 10 minutes (regime scan runs every 5 min)
                cache.set(f'hmm_regime:{symbol}', state, timeout=600)
                logger.debug(f"HMM regime {symbol}: state={state}")
        except Exception as e:
            logger.debug(f"HMM scan failed for {symbol}: {e}")

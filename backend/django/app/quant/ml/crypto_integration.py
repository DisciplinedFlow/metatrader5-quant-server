"""
Crypto ML integration — meta-filter for Lighter.xyz strategies.

Provides a single entry point that RSI scalper and mean reversion strategies
call before entering a trade. The ML model acts as a confirmation gate:
it can BLOCK low-probability setups but never INITIATES trades.

Design principles:
- Fail open: if no model is trained, always allow (permissive mode)
- Fail open: if prediction errors, always allow (don't break trading)
- Transparent: returns reason string for logging/debugging
- Lightweight: single Redis lookup + numpy dot product, <1ms latency
"""

import logging
import math

from .crypto_features import CRYPTO_FEATURES, CRYPTO_SYMBOL_ENCODING
from .crypto_trainer import predict_crypto_trade

logger = logging.getLogger('app.lighter')


def ml_filter_crypto(
    symbol: str,
    signal_type: str,
    rsi_value: float = None,
    adx_value: float = None,
    hour: int = None,
    side: str = None,
) -> tuple:
    """ML meta-filter for crypto trades.

    Call this before entering a Lighter position. The ML model scores the
    setup and returns whether it passes the probability threshold.

    Args:
        symbol: Trading pair (e.g., 'ETH', 'BTC', 'SOL')
        signal_type: Entry signal type (e.g., 'rsi2_buy_rsi5_emaup',
                      'mr_buy_bb2.0_rsi25_adx18')
        rsi_value: RSI value at entry (optional, parsed from signal_type if None)
        adx_value: ADX value at entry (optional, parsed from signal_type if None)
        hour: UTC hour of entry (optional, uses current time if None)
        side: 'LONG' or 'SHORT' (optional, parsed from signal_type if None)

    Returns:
        (passed: bool, score: float, reason: str)
        - passed: True if trade should proceed
        - score: ML probability of win (0.0-1.0), 0.5 if no model
        - reason: Human-readable explanation
    """
    try:
        # Build feature dict from available information
        features = _build_features_from_signal(
            symbol=symbol,
            signal_type=signal_type,
            rsi_value=rsi_value,
            adx_value=adx_value,
            hour=hour,
            side=side,
        )

        score, should_trade = predict_crypto_trade(features)

        if should_trade:
            reason = f"ML passed (score={score:.2f})"
        else:
            reason = f"ML blocked (score={score:.2f}, threshold=0.55)"

        logger.debug(
            f"Crypto ML filter: {symbol} {signal_type} -> "
            f"score={score:.3f}, passed={should_trade}"
        )

        return should_trade, score, reason

    except Exception as e:
        logger.warning(f"Crypto ML filter error: {e}")
        # Fail open — never block trades due to ML errors
        return True, 0.5, f"ML error (permissive): {e}"


def _build_features_from_signal(
    symbol: str,
    signal_type: str,
    rsi_value: float = None,
    adx_value: float = None,
    hour: int = None,
    side: str = None,
) -> dict:
    """Build a feature dict compatible with CRYPTO_FEATURES from signal metadata.

    This mirrors crypto_features.extract_trade_features() but works at
    prediction time (before the trade exists in the database).
    """
    import re
    from datetime import datetime, timezone

    features = {}

    # RSI — use provided value, or parse from signal, or default
    if rsi_value is not None:
        features['rsi_at_entry'] = float(rsi_value)
    else:
        match = re.search(r'_rsi(\d+(?:\.\d+)?)', signal_type)
        features['rsi_at_entry'] = float(match.group(1)) if match else 50.0

    # ADX — use provided value, or parse from signal, or default
    if adx_value is not None:
        features['adx_at_entry'] = float(adx_value)
    else:
        match = re.search(r'_adx(\d+(?:\.\d+)?)', signal_type)
        features['adx_at_entry'] = float(match.group(1)) if match else 25.0

    # EMA trend
    if 'emaup' in signal_type:
        features['ema_trend'] = 1.0
    elif 'emadown' in signal_type:
        features['ema_trend'] = -1.0
    else:
        features['ema_trend'] = 0.0

    # Side
    if side is not None:
        features['side_encoded'] = 1.0 if side == 'LONG' else -1.0
    elif 'buy' in signal_type.lower():
        features['side_encoded'] = 1.0
    elif 'sell' in signal_type.lower():
        features['side_encoded'] = -1.0
    else:
        features['side_encoded'] = 0.0

    # Symbol
    features['symbol_encoded'] = float(
        CRYPTO_SYMBOL_ENCODING.get(symbol, len(CRYPTO_SYMBOL_ENCODING))
    )

    # Time — cyclical encoding
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    features['hour_sin'] = math.sin(2 * math.pi * hour / 24)
    features['hour_cos'] = math.cos(2 * math.pi * hour / 24)

    # Strategy type
    if signal_type.startswith('mr_liq_'):
        features['strategy_encoded'] = 2.0
    elif signal_type.startswith('mr_'):
        features['strategy_encoded'] = 1.0
    elif signal_type.startswith('rsi2_'):
        features['strategy_encoded'] = 0.0
    elif signal_type.startswith('ema_cross'):
        features['strategy_encoded'] = 3.0
    else:
        features['strategy_encoded'] = 4.0

    # Confluence tag
    features['has_confluence'] = 1.0 if re.search(r'_c\d+', signal_type) else 0.0

    # Hold duration is 0 at prediction time (trade hasn't happened yet)
    features['hold_duration_min'] = 0.0

    return features

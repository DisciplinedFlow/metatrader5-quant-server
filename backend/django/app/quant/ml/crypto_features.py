"""
Crypto feature extraction for ML trade scoring — Lighter.xyz positions.

Designed for small datasets (~100 trades). Features are derived from:
1. The CryptoPosition record itself (entry_signal, opened_at, pnl_usd, etc.)
2. Parsed signal metadata (RSI value, trend direction, ADX)
3. Trade context (hold duration, symbol, side, leverage)

No historical candle fetch required — all features come from the trade record
and its entry_signal string, which encodes strategy state at entry time.

Entry signal formats:
- RSI scalper:  "lighter:rsi2_buy_rsi5_emaup"   / "lighter:rsi2_sell_rsi95_emadown"
- Mean reversion: "lighter:mr_buy_bb2.0_rsi25_adx18"  / "lighter:mr_sell_bb2.0_rsi75_adx22"
- Mean reversion + liq: "lighter:mr_buy_bb2.0_rsi25_adx18_liq2.5x"
- Liq-only MR: "lighter:mr_liq_buy_vol3.2x_adx15"
- EMA cross:   "lighter:ema_cross_buy_ema_8_21"
- Reconciled:  "lighter:reconciled"
"""

import logging
import math
import re

import numpy as np

logger = logging.getLogger('app.lighter')

# Feature names in fixed order — model depends on this ordering.
# 10 features max for ~100 trades (rule of thumb: N/10 features).
CRYPTO_FEATURES = [
    'rsi_at_entry',        # RSI value parsed from entry_signal (0-100, default 50)
    'adx_at_entry',        # ADX value parsed from entry_signal (0-100, default 25)
    'ema_trend',           # 1=up, -1=down, 0=unknown (from entry_signal)
    'side_encoded',        # 1=LONG, -1=SHORT
    'symbol_encoded',      # Numeric ID for the symbol
    'hour_sin',            # sin(2*pi*hour/24) — cyclical time encoding
    'hour_cos',            # cos(2*pi*hour/24) — cyclical time encoding
    'strategy_encoded',    # 0=rsi2, 1=mr, 2=mr_liq, 3=ema_cross, 4=other
    'has_confluence',      # 1 if entry_signal contains confluence tag, 0 otherwise
    'hold_duration_min',   # Minutes position was held (closed trades only)
]

# Symbol encoding — crypto majors traded on Lighter
CRYPTO_SYMBOL_ENCODING = {
    'BTC': 0, 'ETH': 1, 'SOL': 2, 'DOGE': 3, 'XRP': 4,
    'LINK': 5, 'AVAX': 6, 'NEAR': 7, 'DOT': 8, 'TON': 9,
    'SUI': 10, 'HYPE': 11, 'BNB': 12, 'AAVE': 13, 'ADA': 14,
    'ARB': 15, 'OP': 16,
}

# Strategy encoding based on entry_signal prefix
STRATEGY_ENCODING = {
    'rsi2': 0,
    'mr': 1,
    'mr_liq': 2,
    'ema_cross': 3,
}


def _parse_rsi(signal: str) -> float:
    """Extract RSI value from entry_signal string.

    Examples:
        'lighter:rsi2_buy_rsi5_emaup' -> 5.0
        'lighter:mr_sell_bb2.0_rsi75_adx22' -> 75.0
    """
    match = re.search(r'_rsi(\d+(?:\.\d+)?)', signal)
    if match:
        return float(match.group(1))
    return 50.0  # neutral default


def _parse_adx(signal: str) -> float:
    """Extract ADX value from entry_signal string.

    Examples:
        'lighter:mr_buy_bb2.0_rsi25_adx18' -> 18.0
        'lighter:mr_liq_buy_vol3.2x_adx15' -> 15.0
    """
    match = re.search(r'_adx(\d+(?:\.\d+)?)', signal)
    if match:
        return float(match.group(1))
    return 25.0  # neutral default


def _parse_ema_trend(signal: str) -> int:
    """Extract EMA trend direction from entry_signal string.

    Examples:
        'lighter:rsi2_buy_rsi5_emaup' -> 1
        'lighter:rsi2_sell_rsi95_emadown' -> -1
    """
    if 'emaup' in signal:
        return 1
    elif 'emadown' in signal:
        return -1
    return 0


def _parse_strategy(signal: str) -> int:
    """Classify strategy from entry_signal string.

    Order matters: check mr_liq before mr (more specific first).
    """
    # Strip platform prefix
    body = signal.replace('lighter:', '', 1)

    if body.startswith('mr_liq_'):
        return STRATEGY_ENCODING['mr_liq']
    if body.startswith('mr_'):
        return STRATEGY_ENCODING['mr']
    if body.startswith('rsi2_'):
        return STRATEGY_ENCODING['rsi2']
    if body.startswith('ema_cross'):
        return STRATEGY_ENCODING['ema_cross']
    return 4  # unknown / reconciled


def _has_confluence_tag(signal: str) -> int:
    """Check if the signal has a confluence tag appended (mean reversion)."""
    return 1 if '_c' in signal and re.search(r'_c\d+', signal) else 0


def extract_trade_features(position) -> dict:
    """Extract feature dict from a single CryptoPosition record.

    Args:
        position: CryptoPosition model instance (must be CLOSED).

    Returns:
        Dict mapping feature names to float values, or None if unusable.
    """
    signal = position.entry_signal or ''
    if not signal.startswith('lighter:'):
        return None

    # Skip reconciled positions — no real entry signal metadata
    if signal == 'lighter:reconciled':
        return None

    features = {}

    # Parse signal metadata
    features['rsi_at_entry'] = _parse_rsi(signal)
    features['adx_at_entry'] = _parse_adx(signal)
    features['ema_trend'] = float(_parse_ema_trend(signal))

    # Trade attributes
    features['side_encoded'] = 1.0 if position.side == 'LONG' else -1.0
    features['symbol_encoded'] = float(
        CRYPTO_SYMBOL_ENCODING.get(position.symbol, len(CRYPTO_SYMBOL_ENCODING))
    )

    # Cyclical time encoding from opened_at
    if position.opened_at:
        hour = position.opened_at.hour
        features['hour_sin'] = math.sin(2 * math.pi * hour / 24)
        features['hour_cos'] = math.cos(2 * math.pi * hour / 24)
    else:
        features['hour_sin'] = 0.0
        features['hour_cos'] = 0.0

    # Strategy type
    features['strategy_encoded'] = float(_parse_strategy(signal))

    # Confluence tag
    features['has_confluence'] = float(_has_confluence_tag(signal))

    # Hold duration
    if position.opened_at and position.closed_at:
        delta = (position.closed_at - position.opened_at).total_seconds() / 60.0
        features['hold_duration_min'] = max(delta, 0.0)
    else:
        features['hold_duration_min'] = 0.0

    return features


def features_to_array(features_dict: dict) -> np.ndarray:
    """Convert feature dict to numpy array in CRYPTO_FEATURES order."""
    return np.array(
        [features_dict.get(name, 0.0) for name in CRYPTO_FEATURES],
        dtype=np.float64,
    )


def extract_crypto_features():
    """Extract feature matrix from all closed Lighter positions.

    Returns:
        (X, y, trade_ids) where:
        - X: np.ndarray of shape (n_trades, n_features)
        - y: np.ndarray of shape (n_trades,) with 1=win, 0=loss
        - trade_ids: list of CryptoPosition IDs

    Returns (None, None, []) if no usable trades found.
    """
    from app.crypto.models import CryptoPosition

    closed = CryptoPosition.objects.filter(
        status='CLOSED',
        entry_signal__startswith='lighter:',
        pnl_usd__isnull=False,
    ).order_by('opened_at')  # chronological for walk-forward

    X_list = []
    y_list = []
    trade_ids = []
    skipped = 0

    for pos in closed:
        try:
            feat = extract_trade_features(pos)
            if feat is None:
                skipped += 1
                continue

            X_list.append(features_to_array(feat))
            y_list.append(1 if pos.pnl_usd > 0 else 0)
            trade_ids.append(pos.id)
        except Exception as e:
            logger.debug(f"Skipping crypto position {pos.id}: {e}")
            skipped += 1

    if not X_list:
        logger.info("Crypto ML: No usable closed trades found.")
        return None, None, []

    X = np.array(X_list)
    y = np.array(y_list)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    logger.info(
        f"Crypto ML: Extracted {len(X_list)} trades "
        f"({skipped} skipped, {sum(y)} wins, {len(y) - sum(y)} losses)"
    )

    return X, y, trade_ids

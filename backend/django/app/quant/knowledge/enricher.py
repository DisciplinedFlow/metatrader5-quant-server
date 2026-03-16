"""
Graph Feature Enricher — provides 5 graph-derived features for XGBoost.

Phase 1: Returns defaults (0.5 = neutral).
Phase 2: Reads pre-computed features from Redis, computed by run_graph_enrichment task.
"""

import logging
from typing import Dict

logger = logging.getLogger('app.quant.knowledge')

DEFAULTS = {
    'graph_similar_wr': 0.5,
    'graph_strategy_regime_wr': 0.5,
    'graph_news_sentiment': 0.0,
    'graph_time_wr': 0.5,
    'graph_symbol_regime_wr': 0.5,
}


def enrich_features(symbol: str, order_type: str, regime: str,
                    hour_utc: int, session: str, strategy_name: str,
                    confluence_score: int) -> Dict[str, float]:
    """
    Return 5 graph-derived features for ML model input.

    Reads from Redis cache (pre-computed by run_graph_enrichment task).
    Falls back to neutral defaults if graph data unavailable.
    """
    try:
        from django.core.cache import cache

        direction = 'BUY' if order_type in ('BUY', 'buy', 0) else 'SELL'
        cached = cache.get(f'graph_features:{symbol}:{direction}')
        if cached and isinstance(cached, dict):
            return {**DEFAULTS, **cached}

        # No cached features — return neutral defaults
        return dict(DEFAULTS)

    except Exception:
        return dict(DEFAULTS)


def compute_and_cache_features(symbol: str, regime_detail: dict) -> None:
    """
    Pre-compute graph features for a symbol and cache in Redis.
    Called by run_graph_enrichment Celery task every 5 minutes.
    """
    try:
        from django.core.cache import cache
        from .connection import get_graph

        graph = get_graph()
        if graph is None:
            return

        regime = regime_detail.get('label', 'UNKNOWN')
        adx = regime_detail.get('adx', 0)
        bb_width = regime_detail.get('bb_width', 0)
        hour_utc = __import__('datetime').datetime.utcnow().hour
        from .graph import _get_session
        session_name = _get_session(hour_utc)

        for direction in ('BUY', 'SELL'):
            features = dict(DEFAULTS)

            # 1. Similar conditions win rate
            similar = graph.find_similar_conditions(
                symbol, regime, adx, bb_width, session_name, hour_utc
            )
            if similar and similar.get('total', 0) >= 5:
                features['graph_similar_wr'] = round(similar['win_rate'], 4)

            # 2. Symbol regime history
            sym_regime = graph.get_symbol_regime_history(symbol, regime)
            if sym_regime and sym_regime.get('total', 0) >= 5:
                features['graph_symbol_regime_wr'] = round(sym_regime['win_rate'], 4)

            cache.set(
                f'graph_features:{symbol}:{direction}',
                features,
                timeout=360  # 6 min (slightly longer than 5-min enrichment cycle)
            )

    except Exception as e:
        logger.debug("Feature enrichment failed for %s: %s", symbol, e)

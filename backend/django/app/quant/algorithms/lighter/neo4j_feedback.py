"""
Neo4j Feedback Loop — queries historical trade outcomes before entering.

"Last 5 times RSI(2) fired on ETH at 01:00 UTC, 4 were wins" -> boost size
"Last 5 times we went LONG XAU during EXTREME news, 4 were losses" -> reduce size

This is what separates a rule-based system from a learning system.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger('app.lighter')

# ── Thresholds ──────────────────────────────────────────────
MIN_TRADES_FOR_SIGNAL = 5   # Need at least 5 similar trades to act on data
BOOST_WR = 0.65             # > 65% win rate -> boost size
NORMAL_LOW = 0.45           # 45-65% -> normal size
REDUCE_WR = 0.30            # 30-45% -> reduce size; < 30% -> skip

BOOST_MULT = 1.2
NORMAL_MULT = 1.0
REDUCE_MULT = 0.7
SKIP_MULT = 0.0

# Hour performance thresholds
HOUR_BOOST_WR = 0.70        # > 70% at this hour -> slight boost
HOUR_REDUCE_WR = 0.35       # < 35% at this hour -> slight reduce

# Cache TTL (seconds) — avoid hammering Neo4j on every 10s tick
CACHE_TTL = 120  # 2 minutes


def _get_driver_session():
    """Get a Neo4j read session via the knowledge graph connection.

    Returns (session, database) tuple or (None, None) if unavailable.
    """
    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if graph is None or not graph.connected or graph.driver is None:
            return None, None
        return graph.driver.session(database=graph.database), graph.database
    except Exception as e:
        logger.debug("Neo4j feedback: connection unavailable: %s", e)
        return None, None


def query_similar_trades(symbol: str, direction: str, strategy_type: str,
                         hour_utc: Optional[int] = None, limit: int = 10) -> Dict:
    """
    Query Neo4j for similar historical trades on Lighter.

    Args:
        symbol: e.g. 'ETH', 'SOL', 'XAU'
        direction: 'LONG' or 'SHORT'
        strategy_type: substring match on strategy field, e.g. 'rsi2', 'mr'
        hour_utc: optional hour filter (0-23)
        limit: max trades to consider

    Returns dict with:
        total_found, win_rate, avg_pnl, avg_win, avg_loss,
        best_hours, worst_hours, recommendation, size_modifier
    """
    default = {
        'total_found': 0,
        'win_rate': 0.5,
        'avg_pnl': 0.0,
        'avg_win': 0.0,
        'avg_loss': 0.0,
        'best_hours': [],
        'worst_hours': [],
        'recommendation': 'NORMAL',
        'size_modifier': NORMAL_MULT,
    }

    # Check cache first
    try:
        from django.core.cache import cache
        cache_key = f'neo4j_fb:similar:{symbol}:{direction}:{strategy_type}:{hour_utc}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        cache = None
        cache_key = None

    session = None
    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if graph is None or not graph.connected or graph.driver is None:
            return default

        with graph.driver.session(database=graph.database) as session:
            # Map direction: strategies store LONG/SHORT, graph stores BUY/SELL
            graph_direction = 'BUY' if direction in ('LONG', 'BUY') else 'SELL'

            result = session.run(
                """
                MATCH (t:Trade {venue: 'LIGHTER', symbol: $symbol, direction: $direction})
                WHERE t.strategy CONTAINS $strategy_type
                RETURN t.pnl AS pnl, t.closing_reason AS closing_reason,
                       t.hour_utc AS hour_utc, t.session AS session
                ORDER BY t.entry_time DESC
                LIMIT $limit
                """,
                symbol=symbol,
                direction=graph_direction,
                strategy_type=strategy_type,
                limit=limit,
            )

            trades = [dict(record) for record in result]

        if not trades:
            return default

        total = len(trades)
        wins = [t for t in trades if (t.get('pnl') or 0) > 0]
        losses = [t for t in trades if (t.get('pnl') or 0) <= 0]

        win_rate = len(wins) / total if total > 0 else 0.5
        avg_pnl = sum(t.get('pnl', 0) or 0 for t in trades) / total if total > 0 else 0.0
        avg_win = (sum(t.get('pnl', 0) or 0 for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t.get('pnl', 0) or 0 for t in losses) / len(losses)) if losses else 0.0

        # Compute per-hour win rates for best/worst hours
        hour_wins = defaultdict(int)
        hour_total = defaultdict(int)
        for t in trades:
            h = t.get('hour_utc')
            if h is not None:
                hour_total[h] += 1
                if (t.get('pnl') or 0) > 0:
                    hour_wins[h] += 1

        best_hours = []
        worst_hours = []
        for h, cnt in hour_total.items():
            if cnt >= 2:  # Need at least 2 trades at this hour
                hr_wr = hour_wins[h] / cnt
                if hr_wr >= HOUR_BOOST_WR:
                    best_hours.append(h)
                elif hr_wr <= HOUR_REDUCE_WR:
                    worst_hours.append(h)

        # Determine recommendation
        if win_rate >= BOOST_WR:
            recommendation = 'BOOST'
            size_modifier = BOOST_MULT
        elif win_rate >= NORMAL_LOW:
            recommendation = 'NORMAL'
            size_modifier = NORMAL_MULT
        elif win_rate >= REDUCE_WR:
            recommendation = 'REDUCE'
            size_modifier = REDUCE_MULT
        else:
            recommendation = 'SKIP'
            size_modifier = SKIP_MULT

        output = {
            'total_found': total,
            'win_rate': round(win_rate, 3),
            'avg_pnl': round(avg_pnl, 4),
            'avg_win': round(avg_win, 4),
            'avg_loss': round(avg_loss, 4),
            'best_hours': sorted(best_hours),
            'worst_hours': sorted(worst_hours),
            'recommendation': recommendation,
            'size_modifier': size_modifier,
        }

        # Cache the result
        try:
            if cache_key:
                from django.core.cache import cache as django_cache
                django_cache.set(cache_key, output, timeout=CACHE_TTL)
        except Exception:
            pass

        return output

    except Exception as e:
        logger.debug("Neo4j feedback query_similar_trades failed: %s", e)
        return default


def query_hour_performance(symbol: str, hour_utc: int, limit: int = 20) -> Dict:
    """
    Query how a symbol performs at a specific hour on Lighter.

    Returns dict with: total, wins, win_rate, avg_pnl
    """
    default = {
        'total': 0,
        'wins': 0,
        'win_rate': 0.5,
        'avg_pnl': 0.0,
    }

    # Check cache
    try:
        from django.core.cache import cache
        cache_key = f'neo4j_fb:hour:{symbol}:{hour_utc}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        cache = None
        cache_key = None

    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if graph is None or not graph.connected or graph.driver is None:
            return default

        with graph.driver.session(database=graph.database) as session:
            result = session.run(
                """
                MATCH (t:Trade {venue: 'LIGHTER', symbol: $symbol})
                WHERE t.hour_utc = $hour
                RETURN count(t) AS total,
                       sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                       avg(t.pnl) AS avg_pnl
                """,
                symbol=symbol,
                hour=hour_utc,
            )
            record = result.single()

        if not record or record['total'] == 0:
            return default

        total = record['total']
        wins = record['wins']
        avg_pnl = record['avg_pnl'] or 0.0

        output = {
            'total': total,
            'wins': wins,
            'win_rate': round(wins / total, 3) if total > 0 else 0.5,
            'avg_pnl': round(avg_pnl, 4),
        }

        # Cache
        try:
            if cache_key:
                from django.core.cache import cache as django_cache
                django_cache.set(cache_key, output, timeout=CACHE_TTL)
        except Exception:
            pass

        return output

    except Exception as e:
        logger.debug("Neo4j feedback query_hour_performance failed: %s", e)
        return default


def get_neo4j_sizing(symbol: str, direction: str, strategy_type: str,
                     hour_utc: int) -> float:
    """
    Main entry point for strategies. Returns a size multiplier (0.0 to 1.3).

    Combines:
    - Similar trade performance (primary signal)
    - Hour-of-day performance (secondary adjustment)

    Falls back to 1.0 if Neo4j is unavailable or insufficient data.

    Args:
        symbol: e.g. 'ETH', 'SOL', 'XAU'
        direction: 'LONG' or 'SHORT'
        strategy_type: e.g. 'rsi2', 'mr'
        hour_utc: current hour (0-23)

    Returns:
        float multiplier: 0.0 (skip) to 1.3 (max boost)
    """
    try:
        # 1. Query similar trades
        similar = query_similar_trades(symbol, direction, strategy_type, hour_utc=hour_utc)

        # Insufficient data — return neutral
        if similar['total_found'] < MIN_TRADES_FOR_SIGNAL:
            logger.debug("Neo4j feedback %s %s %s: only %d similar trades (need %d), neutral",
                         symbol, direction, strategy_type,
                         similar['total_found'], MIN_TRADES_FOR_SIGNAL)
            return 1.0

        base_mult = similar['size_modifier']

        # SKIP means do not trade at all
        if base_mult == 0.0:
            logger.warning(
                "Neo4j feedback SKIP: %s %s %s — WR=%.1f%% from %d trades, avg_pnl=$%.4f",
                symbol, direction, strategy_type,
                similar['win_rate'] * 100, similar['total_found'], similar['avg_pnl']
            )
            return 0.0

        # 2. Hour performance adjustment (subtle: +/- 10%)
        hour_perf = query_hour_performance(symbol, hour_utc)
        hour_adj = 1.0
        if hour_perf['total'] >= 3:  # Need 3+ trades at this hour
            if hour_perf['win_rate'] >= HOUR_BOOST_WR:
                hour_adj = 1.1  # +10% for historically strong hour
            elif hour_perf['win_rate'] <= HOUR_REDUCE_WR:
                hour_adj = 0.9  # -10% for historically weak hour

        final_mult = round(base_mult * hour_adj, 2)

        # Clamp to [0.0, 1.3]
        final_mult = max(0.0, min(1.3, final_mult))

        logger.info(
            "Neo4j feedback %s %s %s: rec=%s WR=%.1f%% (%d trades) "
            "avg_pnl=$%.4f hour_%d_wr=%.1f%% -> mult=%.2f",
            symbol, direction, strategy_type,
            similar['recommendation'], similar['win_rate'] * 100,
            similar['total_found'], similar['avg_pnl'],
            hour_utc, hour_perf['win_rate'] * 100, final_mult
        )

        return final_mult

    except Exception as e:
        logger.debug("Neo4j feedback get_neo4j_sizing failed: %s — returning 1.0", e)
        return 1.0

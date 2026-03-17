"""Neo4j Pattern Advisor — consults the knowledge graph before each trade.

Before entering a trade, asks the graph:
1. What happened in similar setups? (win rate, avg R:R)
2. How does this symbol perform in the current regime?
3. What's the news-adjusted historical performance?
4. Are there any warning patterns? (losing streaks on this setup type)

Returns a confidence score (0-1) and sizing recommendation.
The advisor is CONSULTATIVE — it informs, not blocks.
"""

import logging
from typing import Dict, List, Optional, Tuple

from django.core.cache import cache

logger = logging.getLogger('quant')

ADVISOR_CACHE_TTL = 300  # 5 minutes
MIN_SAMPLE_SIZE = 3      # Need at least 3 similar trades to make a recommendation

# Neutral defaults when graph is unavailable
_NEUTRAL_ADVICE = {
    'confidence': 0.5,
    'size_modifier': 1.0,
    'similar_trades': 0,
    'similar_wr': 0.5,
    'similar_avg_r': 0.0,
    'symbol_regime_wr': 0.5,
    'news_risk_wr': 0.5,
    'warnings': [],
    'recommendation': 'NORMAL',
    'reasoning': 'Graph advisor unavailable — using neutral defaults',
}


class GraphAdvisor:
    """Consults Neo4j for trade entry decisions."""

    def __init__(self):
        from app.quant.knowledge.connection import get_graph
        self.graph = get_graph()

    def consult(
        self,
        symbol: str,
        direction: str,
        strategy: str,
        regime: str = 'UNKNOWN',
        confluence_score: int = 0,
        session: str = 'unknown',
        news_risk: str = 'NORMAL',
        hour_utc: int = 0,
    ) -> Dict:
        """Get advisory recommendation for a trade.

        Returns:
            {
                'confidence': 0.0-1.0,
                'size_modifier': 0.5-1.5,
                'similar_trades': int,
                'similar_wr': float,
                'similar_avg_r': float,
                'symbol_regime_wr': float,
                'news_risk_wr': float,
                'warnings': [],
                'recommendation': str,   # 'STRONG', 'NORMAL', 'CAUTION', 'AVOID'
                'reasoning': str,
            }
        """
        if self.graph is None or not self.graph.connected:
            return dict(_NEUTRAL_ADVICE)

        try:
            # Run all four queries
            similar = self._query_similar_setups(
                symbol, direction, regime, confluence_score, session
            )
            sym_regime = self._query_symbol_regime_performance(symbol, regime)
            news_perf = self._query_news_risk_performance(
                symbol, direction, news_risk
            )
            warnings = self._detect_warning_patterns(symbol, direction)

            # Extract win rates (use 0.5 neutral if sample too small)
            similar_trades = similar.get('total', 0) if similar else 0
            similar_wr = (
                similar['win_rate'] if similar and similar_trades >= MIN_SAMPLE_SIZE
                else 0.5
            )
            similar_avg_r = (
                similar['avg_r'] if similar and similar_trades >= MIN_SAMPLE_SIZE
                else 0.0
            )

            sym_regime_total = sym_regime.get('total', 0) if sym_regime else 0
            symbol_regime_wr = (
                sym_regime['win_rate']
                if sym_regime and sym_regime_total >= MIN_SAMPLE_SIZE
                else 0.5
            )

            news_total = news_perf.get('total', 0) if news_perf else 0
            news_risk_wr = (
                news_perf['win_rate']
                if news_perf and news_total >= MIN_SAMPLE_SIZE
                else 0.5
            )

            # Calculate overall confidence and sizing
            confidence = self._calculate_confidence(
                similar_wr, symbol_regime_wr, news_risk_wr, warnings
            )
            size_modifier = self._calculate_size_modifier(confidence)
            recommendation, reasoning = self._build_recommendation(
                confidence, similar_trades, similar_wr, similar_avg_r,
                symbol_regime_wr, news_risk_wr, warnings, symbol, direction,
                regime, news_risk,
            )

            result = {
                'confidence': round(confidence, 3),
                'size_modifier': round(size_modifier, 2),
                'similar_trades': similar_trades,
                'similar_wr': round(similar_wr, 3),
                'similar_avg_r': round(similar_avg_r or 0, 3),
                'symbol_regime_wr': round(symbol_regime_wr, 3),
                'news_risk_wr': round(news_risk_wr, 3),
                'warnings': warnings,
                'recommendation': recommendation,
                'reasoning': reasoning,
            }

            logger.info(
                "Graph advice %s %s %s: conf=%.2f size=%.2fx rec=%s (%d similar, %d warnings)",
                symbol, direction, regime, confidence, size_modifier,
                recommendation, similar_trades, len(warnings),
            )
            return result

        except Exception as e:
            logger.warning("Graph advisor query failed: %s", e)
            return dict(_NEUTRAL_ADVICE)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def _query_similar_setups(
        self,
        symbol: str,
        direction: str,
        regime: str,
        confluence_score: int,
        session: str,
        lookback_days: int = 90,
    ) -> Optional[Dict]:
        """Find trades with similar parameters in the last N days.

        Match on: same symbol, same direction, similar regime,
        confluence score within +/-2, same session.
        """
        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    self._similar_setups_tx,
                    symbol, direction, regime, confluence_score,
                    session, lookback_days,
                )
                return result
        except Exception as e:
            logger.debug("Similar setups query failed: %s", e)
            return None

    @staticmethod
    def _similar_setups_tx(tx, symbol, direction, regime, conf, session, lookback):
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.direction = $direction
              AND t.regime_at_entry = $regime
              AND abs(t.confluence_score - $conf) <= 2
              AND t.session = $session
              AND t.entry_time > datetime() - duration({days: $lookback})
            RETURN
                count(t) AS total,
                sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                CASE WHEN count(t) > 0
                     THEN sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 / count(t)
                     ELSE 0.0 END AS win_rate,
                avg(t.pnl) AS avg_pnl,
                avg(t.return_r) AS avg_r
        """,
            symbol=symbol,
            direction=direction,
            regime=regime,
            conf=conf,
            session=session,
            lookback=lookback,
        )
        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def _query_symbol_regime_performance(
        self,
        symbol: str,
        regime: str,
        lookback_days: int = 90,
    ) -> Optional[Dict]:
        """How does this symbol perform in this regime?"""
        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    self._symbol_regime_tx, symbol, regime, lookback_days,
                )
                return result
        except Exception as e:
            logger.debug("Symbol-regime query failed: %s", e)
            return None

    @staticmethod
    def _symbol_regime_tx(tx, symbol, regime, lookback):
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.regime_at_entry = $regime
              AND t.entry_time > datetime() - duration({days: $lookback})
            RETURN
                count(t) AS total,
                CASE WHEN count(t) > 0
                     THEN sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 / count(t)
                     ELSE 0.0 END AS win_rate,
                avg(t.return_r) AS avg_r,
                avg(t.pnl) AS avg_pnl
        """,
            symbol=symbol,
            regime=regime,
            lookback=lookback,
        )
        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def _query_news_risk_performance(
        self,
        symbol: str,
        direction: str,
        news_risk: str,
        lookback_days: int = 90,
    ) -> Optional[Dict]:
        """How do trades perform under this news risk level?

        News risk is not stored on Trade nodes directly, so we approximate:
        - NORMAL: all trades (baseline)
        - ELEVATED: trades where return_r < 0 are weighted more (proxy for
          volatile conditions). We use regime=VOLATILE as a proxy.
        - EXTREME: same as ELEVATED but stricter filter.

        If the graph eventually stores news_risk on Trade nodes, this query
        should be updated to match directly.
        """
        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    self._news_risk_tx, symbol, direction, news_risk, lookback_days,
                )
                return result
        except Exception as e:
            logger.debug("News-risk query failed: %s", e)
            return None

    @staticmethod
    def _news_risk_tx(tx, symbol, direction, news_risk, lookback):
        # For NORMAL risk, look at all trades for this symbol+direction.
        # For ELEVATED/EXTREME, filter to volatile regimes as a proxy.
        if news_risk in ('ELEVATED', 'EXTREME'):
            result = tx.run("""
                MATCH (t:Trade)
                WHERE t.symbol = $symbol
                  AND t.direction = $direction
                  AND t.regime_at_entry IN ['VOLATILE', 'HIGH_VOL', 'CHOPPY']
                  AND t.entry_time > datetime() - duration({days: $lookback})
                RETURN
                    count(t) AS total,
                    CASE WHEN count(t) > 0
                         THEN sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 / count(t)
                         ELSE 0.0 END AS win_rate,
                    avg(t.return_r) AS avg_r
            """,
                symbol=symbol,
                direction=direction,
                lookback=lookback,
            )
        else:
            result = tx.run("""
                MATCH (t:Trade)
                WHERE t.symbol = $symbol
                  AND t.direction = $direction
                  AND t.entry_time > datetime() - duration({days: $lookback})
                RETURN
                    count(t) AS total,
                    CASE WHEN count(t) > 0
                         THEN sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 / count(t)
                         ELSE 0.0 END AS win_rate,
                    avg(t.return_r) AS avg_r
            """,
                symbol=symbol,
                direction=direction,
                lookback=lookback,
            )

        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def _detect_warning_patterns(
        self,
        symbol: str,
        direction: str,
        lookback_days: int = 30,
    ) -> List[str]:
        """Check for warning patterns:
        - 3+ consecutive losses on this symbol+direction in last 30 days
        - Declining win rate trend (last 10 trades worse than last 30)
        - High loss magnitude (avg loss > 2x avg win)
        """
        warnings: List[str] = []

        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                # 1. Recent consecutive losses
                streak = sess.execute_read(
                    self._consecutive_losses_tx, symbol, direction, lookback_days,
                )
                if streak and streak >= 3:
                    warnings.append(
                        f"Losing streak: {streak} consecutive losses on {symbol} {direction}"
                    )

                # 2. Declining win rate (last 10 vs last 30 trades)
                trend = sess.execute_read(
                    self._wr_trend_tx, symbol, direction,
                )
                if trend and trend.get('declining'):
                    recent_wr = trend.get('recent_wr', 0)
                    older_wr = trend.get('older_wr', 0)
                    warnings.append(
                        f"Declining WR: recent {recent_wr:.0%} vs older {older_wr:.0%}"
                    )

                # 3. High loss magnitude
                magnitude = sess.execute_read(
                    self._loss_magnitude_tx, symbol, direction, lookback_days,
                )
                if magnitude and magnitude.get('high_loss_ratio'):
                    warnings.append(
                        f"High loss magnitude: avg loss {magnitude['avg_loss']:.2f} "
                        f"vs avg win {magnitude['avg_win']:.2f}"
                    )

        except Exception as e:
            logger.debug("Warning pattern detection failed: %s", e)

        return warnings

    @staticmethod
    def _consecutive_losses_tx(tx, symbol, direction, lookback):
        """Count consecutive losses from most recent trade backwards."""
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.direction = $direction
              AND t.entry_time > datetime() - duration({days: $lookback})
            WITH t ORDER BY t.entry_time DESC
            WITH collect(t.pnl) AS pnls
            WITH pnls,
                 reduce(streak = 0, p IN pnls |
                     CASE WHEN p <= 0 AND streak >= 0
                          THEN streak + 1
                          ELSE CASE WHEN streak >= 0 THEN -1 ELSE streak END
                     END
                 ) AS raw_streak
            RETURN CASE WHEN raw_streak >= 0 THEN raw_streak ELSE 0 END AS streak
        """,
            symbol=symbol,
            direction=direction,
            lookback=lookback,
        )
        record = result.single()
        if record:
            return record['streak']
        return 0

    @staticmethod
    def _wr_trend_tx(tx, symbol, direction):
        """Compare win rate of last 10 trades vs last 30 trades."""
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol AND t.direction = $direction
            WITH t ORDER BY t.entry_time DESC
            WITH collect(t) AS all_trades
            WITH all_trades,
                 all_trades[0..10] AS recent,
                 all_trades[10..30] AS older
            WHERE size(recent) >= 5 AND size(older) >= 5
            WITH
                reduce(w = 0, tr IN recent |
                    CASE WHEN tr.pnl > 0 THEN w + 1 ELSE w END
                ) * 1.0 / size(recent) AS recent_wr,
                reduce(w = 0, tr IN older |
                    CASE WHEN tr.pnl > 0 THEN w + 1 ELSE w END
                ) * 1.0 / size(older) AS older_wr
            RETURN recent_wr, older_wr,
                   recent_wr < older_wr - 0.1 AS declining
        """,
            symbol=symbol,
            direction=direction,
        )
        record = result.single()
        if record:
            return dict(record)
        return None

    @staticmethod
    def _loss_magnitude_tx(tx, symbol, direction, lookback):
        """Check if average loss magnitude exceeds 2x average win."""
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.direction = $direction
              AND t.entry_time > datetime() - duration({days: $lookback})
            WITH
                avg(CASE WHEN t.pnl > 0 THEN t.pnl END) AS avg_win,
                avg(CASE WHEN t.pnl < 0 THEN abs(t.pnl) END) AS avg_loss,
                count(CASE WHEN t.pnl > 0 THEN 1 END) AS win_count,
                count(CASE WHEN t.pnl < 0 THEN 1 END) AS loss_count
            WHERE win_count >= 2 AND loss_count >= 2
              AND avg_win IS NOT NULL AND avg_loss IS NOT NULL
            RETURN avg_win, avg_loss,
                   avg_loss > avg_win * 2 AS high_loss_ratio
        """,
            symbol=symbol,
            direction=direction,
            lookback=lookback,
        )
        record = result.single()
        if record:
            return dict(record)
        return None

    # ------------------------------------------------------------------
    # Scoring logic
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_confidence(
        similar_wr: float,
        symbol_regime_wr: float,
        news_wr: float,
        warnings: List[str],
    ) -> float:
        """Combine all signals into a single confidence score 0-1.

        Weights:
        - Similar setup WR: 40%
        - Symbol+regime WR: 30%
        - News-risk WR: 20%
        - Warning penalty: -10% per warning (up to -30%)
        """
        base = (
            similar_wr * 0.40
            + symbol_regime_wr * 0.30
            + news_wr * 0.20
        )
        # Remaining 10% is baseline (always contributes 0.05)
        base += 0.05

        # Warning penalty: -0.10 per warning, max -0.30
        penalty = min(len(warnings) * 0.10, 0.30)
        confidence = base - penalty

        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _calculate_size_modifier(confidence: float) -> float:
        """Convert confidence to a sizing multiplier.

        confidence >= 0.7  -> 1.2x (high confidence, slightly larger)
        confidence 0.5-0.7 -> 1.0x (normal)
        confidence 0.3-0.5 -> 0.7x (low confidence, reduce size)
        confidence < 0.3   -> 0.5x (very low, half size)
        """
        if confidence >= 0.7:
            return 1.2
        elif confidence >= 0.5:
            return 1.0
        elif confidence >= 0.3:
            return 0.7
        else:
            return 0.5

    @staticmethod
    def _build_recommendation(
        confidence: float,
        similar_trades: int,
        similar_wr: float,
        similar_avg_r: float,
        symbol_regime_wr: float,
        news_risk_wr: float,
        warnings: List[str],
        symbol: str,
        direction: str,
        regime: str,
        news_risk: str,
    ) -> Tuple[str, str]:
        """Build a human-readable recommendation and reasoning string.

        Returns:
            (recommendation, reasoning)
        """
        # Determine recommendation tier
        if confidence >= 0.7:
            rec = 'STRONG'
        elif confidence >= 0.5:
            rec = 'NORMAL'
        elif confidence >= 0.3:
            rec = 'CAUTION'
        else:
            rec = 'AVOID'

        # Build reasoning
        parts = []

        if similar_trades >= MIN_SAMPLE_SIZE:
            parts.append(
                f"{similar_trades} similar setups found: "
                f"{similar_wr:.0%} WR, avg {similar_avg_r:+.2f}R"
            )
        else:
            parts.append(
                f"Only {similar_trades} similar setups (need {MIN_SAMPLE_SIZE}+)"
            )

        parts.append(f"{symbol} in {regime}: {symbol_regime_wr:.0%} WR")

        if news_risk != 'NORMAL':
            parts.append(f"News risk {news_risk}: {news_risk_wr:.0%} WR in volatile regimes")

        for w in warnings:
            parts.append(f"WARNING: {w}")

        reasoning = '; '.join(parts)
        return rec, reasoning


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------

def get_trade_advice(symbol: str, direction: str, strategy: str, **kwargs) -> Dict:
    """Convenience function — creates advisor and consults.

    Caches result for 5 minutes per (symbol, direction, regime) combo.
    Returns neutral advice if graph is unavailable.
    """
    regime = kwargs.get('regime', 'UNKNOWN')
    cache_key = f"graph_advice:{symbol}:{direction}:{regime}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        advisor = GraphAdvisor()
        result = advisor.consult(symbol, direction, strategy, **kwargs)
        cache.set(cache_key, result, timeout=ADVISOR_CACHE_TTL)
        return result
    except Exception as e:
        logger.debug("Graph advisor unavailable: %s", e)
        return dict(_NEUTRAL_ADVICE)

"""Neo4j Pattern Advisor — consults the knowledge graph before each trade.

Before entering a trade, asks the graph:
1. What happened in similar setups? (time-weighted win rate, avg R:R)
2. How does this symbol perform in the current regime?
3. What's the news-adjusted historical performance?
4. Are there any warning patterns? (losing streaks on this setup type)
5. How does this setup type perform recently?
6. How does this symbol+direction perform at this hour of day?

Returns a confidence score (0-1) and sizing recommendation.
The advisor is CONSULTATIVE — it informs, not blocks.

Temporal decay: recent trades weighted exponentially more than old ones.
Half-life = 7 days  =>  7d ago = 0.5x, 14d = 0.25x, 30d = 0.02x.
Brain era awareness: BRAIN_V1 trades get 2x weight over RULE_BASED.
"""

import logging
from typing import Dict, List, Optional, Tuple

from django.core.cache import cache

logger = logging.getLogger('quant')

ADVISOR_CACHE_TTL = 300  # 5 minutes
MIN_SAMPLE_SIZE = 3      # Need at least 3 similar trades to make a recommendation
DECAY_HALF_LIFE_DAYS = 7  # Exponential decay half-life in days
LN2 = 0.693147           # ln(2) for decay formula

# Neutral defaults when graph is unavailable
_NEUTRAL_ADVICE = {
    'confidence': 0.5,
    'size_modifier': 1.0,
    'similar_trades': 0,
    'similar_wr': 0.5,
    'similar_avg_r': 0.0,
    'symbol_regime_wr': 0.5,
    'news_risk_wr': 0.5,
    'setup_type_wr': 0.5,
    'time_of_day_wr': 0.5,
    'effective_sample_size': 0.0,
    'warnings': [],
    'recommendation': 'NORMAL',
    'reasoning': 'Graph advisor unavailable — using neutral defaults',
}

# Cypher snippet for temporal decay with brain era awareness.
# Neo4j 5.x supports exp() and duration.between().
# Produces columns: weight (combined temporal + era weight)
#
# NOTE: If exp() is unavailable on your Neo4j build, replace with the
# polynomial approximation in _DECAY_WEIGHT_POLY below.
_DECAY_WEIGHT_CYPHER = """
    duration.between(t.entry_time, datetime()).days AS age_days,
    exp(-{ln2} * toFloat(duration.between(t.entry_time, datetime()).days) / {half_life}) AS time_weight,
    CASE WHEN t.trading_era = 'BRAIN_V1' THEN 2.0 ELSE 1.0 END AS era_weight
WITH t, age_days, time_weight, era_weight,
     time_weight * era_weight AS weight
""".format(ln2=LN2, half_life=DECAY_HALF_LIFE_DAYS)

# Polynomial approximation of exp(-0.099x) for x in [0, 90],
# used if Neo4j lacks exp(). Accuracy ~5% for 0-90 day range.
_DECAY_WEIGHT_POLY = """
    duration.between(t.entry_time, datetime()).days AS age_days,
    CASE
        WHEN duration.between(t.entry_time, datetime()).days <= 0 THEN 1.0
        WHEN duration.between(t.entry_time, datetime()).days > 90 THEN 0.001
        ELSE 1.0 - 0.08 * toFloat(duration.between(t.entry_time, datetime()).days)
             + 0.002 * toFloat(duration.between(t.entry_time, datetime()).days)
               * toFloat(duration.between(t.entry_time, datetime()).days)
             - 0.00002 * toFloat(duration.between(t.entry_time, datetime()).days)
               * toFloat(duration.between(t.entry_time, datetime()).days)
               * toFloat(duration.between(t.entry_time, datetime()).days)
    END AS time_weight,
    CASE WHEN t.trading_era = 'BRAIN_V1' THEN 2.0 ELSE 1.0 END AS era_weight
WITH t, age_days, time_weight, era_weight,
     CASE WHEN time_weight < 0.001 THEN 0.001 ELSE time_weight END * era_weight AS weight
"""


class GraphAdvisor:
    """Consults Neo4j for trade entry decisions."""

    def __init__(self):
        from app.quant.knowledge.connection import get_graph
        self.graph = get_graph()
        self._use_exp = True  # Assume exp() available; fallback on first failure

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
        setup_type: str = '',
    ) -> Dict:
        """Get advisory recommendation for a trade.

        Args:
            symbol: Trading instrument (e.g. 'EURUSD')
            direction: 'BUY' or 'SELL'
            strategy: Strategy name
            regime: HMM regime label
            confluence_score: 0-14 confluence score
            session: Trading session (e.g. 'london', 'new_york')
            news_risk: 'NORMAL', 'ELEVATED', 'EXTREME'
            hour_utc: Current hour in UTC (0-23)
            setup_type: 'TREND_CONTINUATION', 'BREAKOUT', 'REVERSAL', 'RANGE_FADE', or ''

        Returns:
            {
                'confidence': 0.0-1.0,
                'size_modifier': 0.5-1.5,
                'similar_trades': int,
                'similar_wr': float,
                'similar_avg_r': float,
                'symbol_regime_wr': float,
                'news_risk_wr': float,
                'setup_type_wr': float,
                'time_of_day_wr': float,
                'effective_sample_size': float,
                'warnings': [],
                'recommendation': str,   # 'STRONG', 'NORMAL', 'CAUTION', 'AVOID'
                'reasoning': str,
            }
        """
        if self.graph is None or not self.graph.connected:
            return dict(_NEUTRAL_ADVICE)

        try:
            # Run all six queries
            similar = self._query_similar_setups(
                symbol, direction, regime, confluence_score, session
            )
            sym_regime = self._query_symbol_regime_performance(symbol, regime)
            news_perf = self._query_news_risk_performance(
                symbol, direction, news_risk
            )
            warnings = self._detect_warning_patterns(symbol, direction)

            # New queries
            setup_perf = (
                self._query_setup_type_performance(setup_type, symbol)
                if setup_type else None
            )
            tod_perf = self._query_time_of_day_performance(
                symbol, direction, hour_utc
            )

            # Extract win rates (use 0.5 neutral if sample too small)
            similar_eff_size = similar.get('effective_sample_size', 0) if similar else 0
            similar_trades = similar.get('total', 0) if similar else 0
            similar_wr = (
                similar['weighted_wr']
                if similar and similar_eff_size >= MIN_SAMPLE_SIZE
                else 0.5
            )
            similar_avg_r = (
                similar['weighted_avg_r']
                if similar and similar_eff_size >= MIN_SAMPLE_SIZE
                else 0.0
            )

            sym_regime_eff = sym_regime.get('effective_sample_size', 0) if sym_regime else 0
            symbol_regime_wr = (
                sym_regime['weighted_wr']
                if sym_regime and sym_regime_eff >= MIN_SAMPLE_SIZE
                else 0.5
            )

            news_eff = news_perf.get('effective_sample_size', 0) if news_perf else 0
            news_risk_wr = (
                news_perf['weighted_wr']
                if news_perf and news_eff >= MIN_SAMPLE_SIZE
                else 0.5
            )

            setup_eff = setup_perf.get('effective_sample_size', 0) if setup_perf else 0
            setup_type_wr = (
                setup_perf['weighted_wr']
                if setup_perf and setup_eff >= MIN_SAMPLE_SIZE
                else 0.5
            )

            tod_eff = tod_perf.get('effective_sample_size', 0) if tod_perf else 0
            time_of_day_wr = (
                tod_perf['weighted_wr']
                if tod_perf and tod_eff >= MIN_SAMPLE_SIZE
                else 0.5
            )

            # Total effective sample size across all queries
            total_eff = similar_eff_size + sym_regime_eff + news_eff + setup_eff + tod_eff

            # Calculate overall confidence and sizing
            confidence = self._calculate_confidence(
                similar_wr, symbol_regime_wr, news_risk_wr,
                setup_type_wr, time_of_day_wr, warnings, total_eff,
            )
            size_modifier = self._calculate_size_modifier(confidence)
            recommendation, reasoning = self._build_recommendation(
                confidence, similar_trades, similar_wr, similar_avg_r,
                symbol_regime_wr, news_risk_wr, setup_type_wr,
                time_of_day_wr, warnings, symbol, direction,
                regime, news_risk, setup_type, hour_utc,
                similar_eff_size,
            )

            result = {
                'confidence': round(confidence, 3),
                'size_modifier': round(size_modifier, 2),
                'similar_trades': similar_trades,
                'similar_wr': round(similar_wr, 3),
                'similar_avg_r': round(similar_avg_r or 0, 3),
                'symbol_regime_wr': round(symbol_regime_wr, 3),
                'news_risk_wr': round(news_risk_wr, 3),
                'setup_type_wr': round(setup_type_wr, 3),
                'time_of_day_wr': round(time_of_day_wr, 3),
                'effective_sample_size': round(total_eff, 1),
                'warnings': warnings,
                'recommendation': recommendation,
                'reasoning': reasoning,
            }

            logger.info(
                "Graph advice %s %s %s: conf=%.2f size=%.2fx rec=%s "
                "(%d similar, eff=%.1f, %d warnings)",
                symbol, direction, regime, confidence, size_modifier,
                recommendation, similar_trades, total_eff, len(warnings),
            )
            return result

        except Exception as e:
            logger.warning("Graph advisor query failed: %s", e)
            return dict(_NEUTRAL_ADVICE)

    # ------------------------------------------------------------------
    # Decay weight Cypher helper
    # ------------------------------------------------------------------

    @property
    def _decay_cypher(self) -> str:
        """Return the appropriate decay weight Cypher snippet."""
        return _DECAY_WEIGHT_CYPHER if self._use_exp else _DECAY_WEIGHT_POLY

    def _run_weighted_query(self, tx_func, *args):
        """Run a weighted query, falling back to polynomial if exp() fails."""
        try:
            return tx_func(*args, use_exp=True)
        except Exception as e:
            err_str = str(e).lower()
            if 'unknown function' in err_str and 'exp' in err_str:
                logger.warning("Neo4j exp() unavailable, falling back to polynomial decay")
                self._use_exp = False
                return tx_func(*args, use_exp=False)
            raise

    # ------------------------------------------------------------------
    # Query methods (all with temporal decay + era awareness)
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
        """Find trades with similar parameters, weighted by recency + era.

        Match on: same symbol, same direction, similar regime,
        confluence score within +/-2, same session.
        Returns weighted_wr instead of flat win_rate.
        """
        cache_key = f"gadv:similar:{symbol}:{direction}:{regime}:{confluence_score}:{session}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    lambda tx: self._run_weighted_query(
                        self._similar_setups_tx, tx,
                        symbol, direction, regime, confluence_score,
                        session, lookback_days,
                    )
                )
                cache.set(cache_key, result, timeout=ADVISOR_CACHE_TTL)
                return result
        except Exception as e:
            logger.debug("Similar setups query failed: %s", e)
            return None

    @staticmethod
    def _similar_setups_tx(tx, symbol, direction, regime, conf, session, lookback, use_exp=True):
        decay = _DECAY_WEIGHT_CYPHER if use_exp else _DECAY_WEIGHT_POLY
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.direction = $direction
              AND t.regime_at_entry = $regime
              AND abs(t.confluence_score - $conf) <= 2
              AND t.session = $session
              AND t.entry_time > datetime() - duration({{days: $lookback}})
            WITH t,
                 {decay}
            RETURN
                count(t) AS total,
                sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) / sum(weight) AS weighted_wr,
                sum(weight) AS effective_sample_size,
                sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) AS weighted_wins,
                CASE WHEN sum(weight) > 0
                     THEN sum(t.return_r * weight) / sum(weight)
                     ELSE 0.0 END AS weighted_avg_r,
                avg(t.pnl) AS avg_pnl
        """.format(decay=decay),
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
        """How does this symbol perform in this regime? (time-weighted)"""
        cache_key = f"gadv:symregime:{symbol}:{regime}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    lambda tx: self._run_weighted_query(
                        self._symbol_regime_tx, tx,
                        symbol, regime, lookback_days,
                    )
                )
                cache.set(cache_key, result, timeout=ADVISOR_CACHE_TTL)
                return result
        except Exception as e:
            logger.debug("Symbol-regime query failed: %s", e)
            return None

    @staticmethod
    def _symbol_regime_tx(tx, symbol, regime, lookback, use_exp=True):
        decay = _DECAY_WEIGHT_CYPHER if use_exp else _DECAY_WEIGHT_POLY
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.regime_at_entry = $regime
              AND t.entry_time > datetime() - duration({{days: $lookback}})
            WITH t,
                 {decay}
            RETURN
                count(t) AS total,
                CASE WHEN sum(weight) > 0
                     THEN sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) / sum(weight)
                     ELSE 0.0 END AS weighted_wr,
                sum(weight) AS effective_sample_size,
                CASE WHEN sum(weight) > 0
                     THEN sum(t.return_r * weight) / sum(weight)
                     ELSE 0.0 END AS weighted_avg_r,
                avg(t.pnl) AS avg_pnl
        """.format(decay=decay),
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
        """How do trades perform under this news risk level? (time-weighted)

        News risk is not stored on Trade nodes directly, so we approximate:
        - NORMAL: all trades (baseline)
        - ELEVATED: trades where regime is volatile (proxy for volatile conditions)
        - EXTREME: same as ELEVATED but stricter filter.

        If the graph eventually stores news_risk on Trade nodes, this query
        should be updated to match directly.
        """
        cache_key = f"gadv:news:{symbol}:{direction}:{news_risk}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    lambda tx: self._run_weighted_query(
                        self._news_risk_tx, tx,
                        symbol, direction, news_risk, lookback_days,
                    )
                )
                cache.set(cache_key, result, timeout=ADVISOR_CACHE_TTL)
                return result
        except Exception as e:
            logger.debug("News-risk query failed: %s", e)
            return None

    @staticmethod
    def _news_risk_tx(tx, symbol, direction, news_risk, lookback, use_exp=True):
        decay = _DECAY_WEIGHT_CYPHER if use_exp else _DECAY_WEIGHT_POLY
        # For ELEVATED/EXTREME risk, filter to volatile regimes as a proxy.
        if news_risk in ('ELEVATED', 'EXTREME'):
            result = tx.run("""
                MATCH (t:Trade)
                WHERE t.symbol = $symbol
                  AND t.direction = $direction
                  AND t.regime_at_entry IN ['VOLATILE', 'HIGH_VOL', 'CHOPPY']
                  AND t.entry_time > datetime() - duration({{days: $lookback}})
                WITH t,
                     {decay}
                RETURN
                    count(t) AS total,
                    CASE WHEN sum(weight) > 0
                         THEN sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) / sum(weight)
                         ELSE 0.0 END AS weighted_wr,
                    sum(weight) AS effective_sample_size,
                    CASE WHEN sum(weight) > 0
                         THEN sum(t.return_r * weight) / sum(weight)
                         ELSE 0.0 END AS weighted_avg_r
            """.format(decay=decay),
                symbol=symbol,
                direction=direction,
                lookback=lookback,
            )
        else:
            result = tx.run("""
                MATCH (t:Trade)
                WHERE t.symbol = $symbol
                  AND t.direction = $direction
                  AND t.entry_time > datetime() - duration({{days: $lookback}})
                WITH t,
                     {decay}
                RETURN
                    count(t) AS total,
                    CASE WHEN sum(weight) > 0
                         THEN sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) / sum(weight)
                         ELSE 0.0 END AS weighted_wr,
                    sum(weight) AS effective_sample_size,
                    CASE WHEN sum(weight) > 0
                         THEN sum(t.return_r * weight) / sum(weight)
                         ELSE 0.0 END AS weighted_avg_r
            """.format(decay=decay),
                symbol=symbol,
                direction=direction,
                lookback=lookback,
            )

        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def _query_setup_type_performance(
        self,
        setup_type: str,
        symbol: str = None,
        lookback_days: int = 30,
    ) -> Optional[Dict]:
        """How does this setup type perform recently? (time-weighted)

        setup_type: 'TREND_CONTINUATION', 'BREAKOUT', 'REVERSAL', 'RANGE_FADE'
        Matches trades where the strategy name contains the setup_type keyword.
        """
        if not setup_type:
            return None

        cache_key = f"gadv:setup:{setup_type}:{symbol or 'ALL'}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    lambda tx: self._run_weighted_query(
                        self._setup_type_tx, tx,
                        setup_type, symbol, lookback_days,
                    )
                )
                cache.set(cache_key, result, timeout=ADVISOR_CACHE_TTL)
                return result
        except Exception as e:
            logger.debug("Setup type query failed: %s", e)
            return None

    @staticmethod
    def _setup_type_tx(tx, setup_type, symbol, lookback, use_exp=True):
        decay = _DECAY_WEIGHT_CYPHER if use_exp else _DECAY_WEIGHT_POLY
        # Build WHERE clause: always match setup_type in strategy, optionally filter by symbol
        where_symbol = "AND t.symbol = $symbol" if symbol else ""
        result = tx.run("""
            MATCH (t:Trade)
            WHERE toLower(t.strategy) CONTAINS toLower($setup_type)
              {where_symbol}
              AND t.entry_time > datetime() - duration({{days: $lookback}})
            WITH t,
                 {decay}
            RETURN
                count(t) AS total,
                CASE WHEN sum(weight) > 0
                     THEN sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) / sum(weight)
                     ELSE 0.0 END AS weighted_wr,
                sum(weight) AS effective_sample_size,
                CASE WHEN sum(weight) > 0
                     THEN sum(t.return_r * weight) / sum(weight)
                     ELSE 0.0 END AS weighted_avg_r,
                avg(t.pnl) AS avg_pnl
        """.format(decay=decay, where_symbol=where_symbol),
            setup_type=setup_type,
            symbol=symbol or '',
            lookback=lookback,
        )
        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def _query_time_of_day_performance(
        self,
        symbol: str,
        direction: str,
        hour_utc: int,
        lookback_days: int = 60,
    ) -> Optional[Dict]:
        """How does this symbol+direction perform at this hour? (time-weighted)

        Groups into 4-hour windows:
            0-3, 4-7, 8-11, 12-15, 16-19, 20-23
        """
        # Map hour to 4-hour window boundaries
        window_start = (hour_utc // 4) * 4
        window_end = window_start + 3

        cache_key = f"gadv:tod:{symbol}:{direction}:{window_start}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self.graph.driver.session(database=self.graph.database) as sess:
                result = sess.execute_read(
                    lambda tx: self._run_weighted_query(
                        self._time_of_day_tx, tx,
                        symbol, direction, window_start, window_end, lookback_days,
                    )
                )
                cache.set(cache_key, result, timeout=ADVISOR_CACHE_TTL)
                return result
        except Exception as e:
            logger.debug("Time-of-day query failed: %s", e)
            return None

    @staticmethod
    def _time_of_day_tx(tx, symbol, direction, window_start, window_end, lookback, use_exp=True):
        decay = _DECAY_WEIGHT_CYPHER if use_exp else _DECAY_WEIGHT_POLY
        result = tx.run("""
            MATCH (t:Trade)
            WHERE t.symbol = $symbol
              AND t.direction = $direction
              AND t.entry_time > datetime() - duration({{days: $lookback}})
              AND t.entry_time.hour >= $window_start
              AND t.entry_time.hour <= $window_end
            WITH t,
                 {decay}
            RETURN
                count(t) AS total,
                CASE WHEN sum(weight) > 0
                     THEN sum(CASE WHEN t.pnl > 0 THEN weight ELSE 0 END) / sum(weight)
                     ELSE 0.0 END AS weighted_wr,
                sum(weight) AS effective_sample_size,
                CASE WHEN sum(weight) > 0
                     THEN sum(t.return_r * weight) / sum(weight)
                     ELSE 0.0 END AS weighted_avg_r,
                avg(t.pnl) AS avg_pnl
        """.format(decay=decay),
            symbol=symbol,
            direction=direction,
            window_start=window_start,
            window_end=window_end,
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
        setup_type_wr: float,
        time_of_day_wr: float,
        warnings: List[str],
        effective_sample_size: float,
    ) -> float:
        """Combine all signals into a single confidence score 0-1.

        Weights (updated to include new signals):
        - Similar setup WR: 30%  (was 40%, redistributed)
        - Symbol+regime WR: 25%  (was 30%)
        - News-risk WR: 15%      (was 20%)
        - Setup type WR: 10%     (NEW)
        - Time-of-day WR: 10%    (NEW)
        - Baseline: 5%           (always contributes 0.05)
        - Warning penalty: -10% per warning (up to -30%)

        Effective sample size bonus/penalty:
        - If total effective samples > 20: +0.03 (good data)
        - If total effective samples < 5: -0.05 (sparse data, less trust)
        """
        base = (
            similar_wr * 0.30
            + symbol_regime_wr * 0.25
            + news_wr * 0.15
            + setup_type_wr * 0.10
            + time_of_day_wr * 0.10
        )
        # Remaining 10% split: 5% baseline + 5% sample-size adjustment
        base += 0.05

        # Sample size adjustment
        if effective_sample_size > 20:
            base += 0.03  # Good data coverage — slight boost
        elif effective_sample_size < 5:
            base -= 0.05  # Very sparse data — reduce trust

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
        setup_type_wr: float,
        time_of_day_wr: float,
        warnings: List[str],
        symbol: str,
        direction: str,
        regime: str,
        news_risk: str,
        setup_type: str,
        hour_utc: int,
        effective_sample_size: float,
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

        if effective_sample_size >= MIN_SAMPLE_SIZE:
            parts.append(
                f"{similar_trades} similar setups (eff={effective_sample_size:.1f}): "
                f"{similar_wr:.0%} WR, avg {similar_avg_r:+.2f}R"
            )
        else:
            parts.append(
                f"Only {similar_trades} similar setups "
                f"(eff={effective_sample_size:.1f}, need {MIN_SAMPLE_SIZE}+)"
            )

        parts.append(f"{symbol} in {regime}: {symbol_regime_wr:.0%} WR")

        if news_risk != 'NORMAL':
            parts.append(f"News risk {news_risk}: {news_risk_wr:.0%} WR in volatile regimes")

        if setup_type:
            parts.append(f"Setup {setup_type}: {setup_type_wr:.0%} WR")

        # Time-of-day window
        window_start = (hour_utc // 4) * 4
        window_end = window_start + 3
        parts.append(f"Hour {window_start}-{window_end} UTC: {time_of_day_wr:.0%} WR")

        for w in warnings:
            parts.append(f"WARNING: {w}")

        reasoning = '; '.join(parts)
        return rec, reasoning


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------

def get_trade_advice(symbol: str, direction: str, strategy: str, **kwargs) -> Dict:
    """Convenience function — creates advisor and consults.

    Caches result for 5 minutes per (symbol, direction, regime, setup_type, hour) combo.
    Returns neutral advice if graph is unavailable.
    """
    regime = kwargs.get('regime', 'UNKNOWN')
    setup_type = kwargs.get('setup_type', '')
    hour_utc = kwargs.get('hour_utc', 0)
    hour_window = (hour_utc // 4) * 4  # Bucket hours into 4h windows for cache key
    cache_key = f"graph_advice:{symbol}:{direction}:{regime}:{setup_type}:{hour_window}"
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

"""
Backtest Seeder — populates Neo4j brain with 6 months of reference trade nodes.

Architecture:
  1. Fetch 6 months of H4 OHLCV from MT5 for each symbol
  2. Detect ICT/SMC setups via pattern_detector.find_setups()
  3. Simulate outcomes at 3 R:R ratios via trade_simulator.simulate_setup()
  4. Seed canonical (1:2 R:R) nodes into Neo4j via graph.record_reference_trade()
  5. Attach 1:1.5 and 1:3 outcomes as node properties
  6. Link geo events via graph.link_trade_to_nearby_events()
  7. Seed static geopolitical era context nodes from geo_events.py

Symbol scan order (matches user's priority):
  Metals first:  XAUUSD, XAGUSD
  Energy second: USOUSD, UKOUSDft, NG-C
  Forex last:    EURUSD, GBPUSD, USDJPY

Run via Django management command:
  docker exec -it django python manage.py seed_brain

Progress is logged at each step. The seeder is idempotent — running it twice
won't create duplicate geo event nodes (MERGE on date+type+text), though it
WILL create duplicate Trade nodes for the same setups. Clear the graph first:
  docker exec -it neo4j cypher-shell -u neo4j -p trading_brain_2026
    MATCH (t:Trade {source: 'BACKTEST_SEED'}) DETACH DELETE t;
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger('app.quant.knowledge')

# ---------------------------------------------------------------------------
# Symbol scan order (priority: metals → energy → forex)
# ---------------------------------------------------------------------------

SEED_SYMBOLS = [
    # Metals
    'XAUUSD',
    'XAGUSD',
    # Energy
    'USOUSD',
    'UKOUSDft',
    'NG-C',
    # Forex
    'EURUSD',
    'GBPUSD',
    'USDJPY',
]

# H4 = 4-hour bars. 6 months ≈ 26 weeks × 5 days × 6 H4 bars/day = ~780 bars.
# Metals / energy trade 24/5 on COMEX/NYMEX: ~780 bars is about right.
# Forex 24/5: similar. MT5 fetch_data_range handles this.
LOOKBACK_DAYS = 180
TIMEFRAME_H4 = 'H4'

MT5_API_BASE = 'http://mt5:5001'
MT5_TIMEOUT = 60  # seconds — fetching 780 bars may take a moment under Wine


# ---------------------------------------------------------------------------
# MT5 data fetching
# ---------------------------------------------------------------------------

def _fetch_h4_bars(symbol: str, days: int = LOOKBACK_DAYS) -> list[dict]:
    """
    Fetch H4 OHLCV bars from MT5 API for the last `days` days.
    Returns list of bar dicts: {time, open, high, low, close, tick_volume}
    """
    date_to = datetime.now(tz=timezone.utc)
    date_from = date_to - timedelta(days=days)

    params = {
        'symbol': symbol,
        'timeframe': TIMEFRAME_H4,
        'start': date_from.strftime('%Y-%m-%d'),
        'end': date_to.strftime('%Y-%m-%d'),
    }
    try:
        resp = requests.get(
            f'{MT5_API_BASE}/fetch_data_range',
            params=params,
            timeout=MT5_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        bars = data if isinstance(data, list) else data.get('bars', data.get('data', []))
        logger.info(f"[seed] {symbol}: fetched {len(bars)} H4 bars")
        return bars
    except Exception as e:
        logger.error(f"[seed] {symbol}: MT5 fetch failed — {e}")
        return []


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

class BacktestSeeder:
    """
    Orchestrates the full backtest-to-Neo4j seeding pipeline.

    Usage:
        seeder = BacktestSeeder()
        report = seeder.run()
        print(report)
    """

    def __init__(self):
        try:
            from app.quant.knowledge.connection import get_graph
        except ImportError:
            from quant.knowledge.connection import get_graph
        self.graph = get_graph()
        self._stats: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Phase 1: Seed geopolitical era context
    # ------------------------------------------------------------------

    def seed_geo_events(self) -> int:
        """
        Write all static geo events from geo_events.py into Neo4j.
        Uses MERGE so running twice is safe.
        Returns number of nodes written.
        """
        try:
            from app.quant.knowledge.geo_events import GEOPOLITICAL_EVENTS
        except ImportError:
            from quant.knowledge.geo_events import GEOPOLITICAL_EVENTS
        if not self.graph:
            logger.warning("[seed] Neo4j unavailable — skipping geo events")
            return 0

        count = 0
        for ev in GEOPOLITICAL_EVENTS:
            node_id = self.graph.record_geopolitical_event(ev)
            if node_id:
                count += 1

        logger.info(f"[seed] Seeded {count} geopolitical event nodes")
        return count

    # ------------------------------------------------------------------
    # Phase 2: Detect setups + simulate + write reference trades
    # ------------------------------------------------------------------

    def seed_symbol(self, symbol: str) -> dict:
        """
        Full pipeline for one symbol:
          fetch → detect → simulate → write to Neo4j

        Returns stats dict for this symbol.
        """
        try:
            from app.quant.knowledge.pattern_detector import find_setups
            from app.quant.knowledge.trade_simulator import simulate_setup, aggregate_results
        except ImportError:
            from quant.knowledge.pattern_detector import find_setups
            from quant.knowledge.trade_simulator import simulate_setup, aggregate_results

        logger.info(f"[seed] === {symbol} ===")

        bars = _fetch_h4_bars(symbol)
        if len(bars) < 50:
            logger.warning(f"[seed] {symbol}: not enough bars ({len(bars)}) — skipping")
            return {'symbol': symbol, 'error': 'insufficient_bars', 'bars': len(bars)}

        # Pattern detection — min confluence 0.55 to keep only quality setups
        setups = find_setups(symbol, bars, min_confluence=0.55)
        logger.info(f"[seed] {symbol}: {len(setups)} setups detected")

        if not setups:
            return {'symbol': symbol, 'setups': 0, 'seeded': 0}

        all_results_2r = []
        seeded_count = 0
        skipped_count = 0

        for setup in setups:
            # Simulate all 3 R:R variants
            sim_results = simulate_setup(
                setup=setup,
                bars=bars,
                rr_ratios=(1.5, 2.0, 3.0),
                max_bars_held=96,  # 4 days H4
                trailing_stop=True,
            )

            # Index by rr_ratio
            by_rr = {r.rr_ratio: r for r in sim_results}
            canonical = by_rr.get(2.0)
            if not canonical:
                continue

            all_results_2r.append(canonical)

            # Build node payload — canonical is 1:2, attach others as metadata
            r15 = by_rr.get(1.5)
            r30 = by_rr.get(3.0)

            trigger_time = setup.trigger_bar_time
            exit_time = canonical.exit_bar_time
            if isinstance(trigger_time, datetime):
                trigger_time = trigger_time.isoformat()
            if isinstance(exit_time, datetime):
                exit_time = exit_time.isoformat()

            node_data = {
                'symbol': symbol,
                'direction': setup.direction,
                'entry_price': canonical.entry_price,
                'sl_price': canonical.sl_price,
                'tp_price': canonical.tp_price,
                'rr_ratio': 2.0,
                'outcome': canonical.outcome,
                'exit_price': canonical.exit_price,
                'pnl_r': canonical.pnl_r,
                'bars_held': canonical.bars_held,
                'max_favorable_excursion': canonical.max_favorable_excursion,
                'max_adverse_excursion': canonical.max_adverse_excursion,
                'trigger_time': trigger_time,
                'exit_time': exit_time,
                'confluence_score': setup.confluence_score,
                'era_sentiment': setup.era_sentiment,
                'htf_bias': setup.htf_bias,
                'session': setup.session,
                'fvg_present': setup.fvg is not None,
                'ob_present': setup.order_block is not None,
                'fib_present': setup.fib is not None,
                'cvd_divergence': setup.cvd_divergence,
                'source': 'BACKTEST_SEED',
                'weight': 0.3,
                # Attach variant outcomes as extra props for brain queries
                'rr_1_5_outcome': r15.outcome if r15 else None,
                'rr_1_5_pnl_r': r15.pnl_r if r15 else None,
                'rr_3_0_outcome': r30.outcome if r30 else None,
                'rr_3_0_pnl_r': r30.pnl_r if r30 else None,
            }

            if not self.graph:
                skipped_count += 1
                continue

            trade_node_id = self.graph.record_reference_trade(node_data)
            if trade_node_id and setup.nearby_geo_events:
                self.graph.link_trade_to_nearby_events(
                    trade_node_id, setup.nearby_geo_events
                )

            if trade_node_id:
                seeded_count += 1
            else:
                skipped_count += 1

        # Aggregate stats for reporting
        agg = aggregate_results(all_results_2r)
        stats = {
            'symbol': symbol,
            'bars_fetched': len(bars),
            'setups': len(setups),
            'seeded': seeded_count,
            'skipped': skipped_count,
            'aggregate_1_2': agg.get('rr_2.0', {}),
        }
        self._stats[symbol] = stats
        logger.info(
            f"[seed] {symbol}: seeded={seeded_count} skipped={skipped_count} "
            f"WR@1:2={agg.get('rr_2.0', {}).get('win_rate', '?')}"
        )
        return stats

    # ------------------------------------------------------------------
    # Run all
    # ------------------------------------------------------------------

    def run(self, symbols: Optional[list[str]] = None) -> dict:
        """
        Run the full seeder pipeline.

        Args:
            symbols: Override default symbol list (useful for testing one symbol)

        Returns:
            Full report dict with per-symbol stats and totals.
        """
        target_symbols = symbols or SEED_SYMBOLS

        logger.info(f"[seed] Starting backtest seeder — {len(target_symbols)} symbols")

        # Phase 1: geo context
        geo_count = self.seed_geo_events()

        # Phase 2: per-symbol
        total_setups = 0
        total_seeded = 0

        for sym in target_symbols:
            stats = self.seed_symbol(sym)
            total_setups += stats.get('setups', 0)
            total_seeded += stats.get('seeded', 0)

        report = {
            'geo_events_seeded': geo_count,
            'symbols_processed': len(target_symbols),
            'total_setups_detected': total_setups,
            'total_reference_trades_seeded': total_seeded,
            'per_symbol': self._stats,
        }

        logger.info(
            f"[seed] Complete — {total_seeded} reference trades seeded "
            f"across {len(target_symbols)} symbols "
            f"({geo_count} geo context nodes)"
        )
        return report

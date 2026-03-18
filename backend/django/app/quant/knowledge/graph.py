"""
Forex Knowledge Graph — Neo4j Trading Brain

Adapted from QuantHub's knowledge_graph.py for forex/metals/energy trading.
Every public method is guarded with a connected check and returns a safe default
if Neo4j is unavailable. Trading continues normally without the graph.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

logger = logging.getLogger('app.quant.knowledge')

SYMBOL_MARKET_TYPE = {
    # MT5 Forex
    'EURUSD': 'FOREX', 'GBPUSD': 'FOREX', 'USDJPY': 'FOREX',
    'AUDUSD': 'FOREX', 'NZDUSD': 'FOREX', 'USDCAD': 'FOREX',
    'USDCHF': 'FOREX', 'EURGBP': 'FOREX', 'USDCNH': 'FOREX',
    'USDSEK': 'FOREX',
    # MT5 Metals & Energy
    'XAUUSD': 'METAL', 'XAGUSD': 'METAL',
    'USOUSD': 'ENERGY', 'UKOUSDft': 'ENERGY', 'NG-C': 'ENERGY',
    # Lighter DEX — Crypto
    'BTC': 'CRYPTO', 'ETH': 'CRYPTO', 'SOL': 'CRYPTO',
    'DOGE': 'CRYPTO', 'XRP': 'CRYPTO', 'LINK': 'CRYPTO',
    'AVAX': 'CRYPTO', 'NEAR': 'CRYPTO', 'DOT': 'CRYPTO',
    'TON': 'CRYPTO', 'SUI': 'CRYPTO', 'HYPE': 'CRYPTO',
    'BNB': 'CRYPTO', 'AAVE': 'CRYPTO', 'ADA': 'CRYPTO',
    'ARB': 'CRYPTO', 'OP': 'CRYPTO',
    # Lighter DEX — Metals & Commodities (different from MT5 symbols)
    'XAU': 'METAL_DEX', 'XAG': 'METAL_DEX', 'PAXG': 'METAL_DEX',
    'WTI': 'ENERGY_DEX',
    # Lighter DEX — Stocks & ETFs
    'TSLA': 'STOCK', 'NVDA': 'STOCK', 'AAPL': 'STOCK',
    'AMZN': 'STOCK', 'MSFT': 'STOCK', 'GOOGL': 'STOCK',
    'META': 'STOCK', 'SPY': 'ETF', 'QQQ': 'ETF',
}

SESSION_MAP = {
    range(22, 24): 'ASIAN', range(0, 7): 'ASIAN',
    range(8, 12): 'LONDON',
    range(12, 17): 'OVERLAP',
    range(17, 22): 'NY',
}


def _get_session(hour_utc: int) -> str:
    for hours, session in SESSION_MAP.items():
        if hour_utc in hours:
            return session
    return 'OFF'


class ForexKnowledgeGraph:
    """
    Knowledge graph for forex trading intelligence.

    Stores trades, market conditions, regime transitions, and news events
    as connected nodes in Neo4j. Enables pattern recognition via graph queries.
    """

    def __init__(self, uri='bolt://neo4j:7687', user='neo4j', password='',
                 database='neo4j'):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.driver = None
        self.connected = False

    def connect(self) -> bool:
        try:
            self.driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self.driver.verify_connectivity()
            self.connected = True
            self._create_schema()
            logger.info("Connected to Neo4j at %s", self.uri)
            return True
        except (ServiceUnavailable, AuthError, Exception) as e:
            logger.error("Failed to connect to Neo4j: %s", e)
            self.connected = False
            return False

    def disconnect(self):
        if self.driver:
            self.driver.close()
            self.connected = False

    def _create_schema(self):
        with self.driver.session(database=self.database) as session:
            constraints = [
                "CREATE CONSTRAINT symbol_id IF NOT EXISTS FOR (s:Symbol) REQUIRE s.id IS UNIQUE",
                "CREATE CONSTRAINT trade_id IF NOT EXISTS FOR (t:Trade) REQUIRE t.id IS UNIQUE",
                "CREATE CONSTRAINT strategy_name IF NOT EXISTS FOR (s:Strategy) REQUIRE s.name IS UNIQUE",
                "CREATE CONSTRAINT news_id IF NOT EXISTS FOR (n:NewsEvent) REQUIRE n.id IS UNIQUE",
                "CREATE CONSTRAINT regime_id IF NOT EXISTS FOR (r:Regime) REQUIRE r.id IS UNIQUE",
                "CREATE CONSTRAINT causal_chain_id IF NOT EXISTS FOR (cc:CausalChain) REQUIRE cc.id IS UNIQUE",
                "CREATE CONSTRAINT trade_reasoning_id IF NOT EXISTS FOR (tr:TradeReasoning) REQUIRE tr.id IS UNIQUE",
            ]
            indexes = [
                "CREATE INDEX trade_entry_time IF NOT EXISTS FOR (t:Trade) ON (t.entry_time)",
                "CREATE INDEX trade_symbol IF NOT EXISTS FOR (t:Trade) ON (t.symbol)",
                "CREATE INDEX trade_regime IF NOT EXISTS FOR (t:Trade) ON (t.regime_at_entry)",
                "CREATE INDEX trade_strategy IF NOT EXISTS FOR (t:Trade) ON (t.strategy)",
                "CREATE INDEX trade_venue IF NOT EXISTS FOR (t:Trade) ON (t.venue)",
                "CREATE INDEX trade_domain IF NOT EXISTS FOR (t:Trade) ON (t.domain)",
                "CREATE INDEX trade_era IF NOT EXISTS FOR (t:Trade) ON (t.trading_era)",
                "CREATE INDEX trade_mtf_bias IF NOT EXISTS FOR (t:Trade) ON (t.mtf_bias)",
                "CREATE INDEX trade_sl_source IF NOT EXISTS FOR (t:Trade) ON (t.sl_source)",
                "CREATE INDEX trade_graph_rec IF NOT EXISTS FOR (t:Trade) ON (t.graph_recommendation)",
                "CREATE INDEX regime_symbol IF NOT EXISTS FOR (r:Regime) ON (r.symbol)",
                "CREATE INDEX news_timestamp IF NOT EXISTS FOR (n:NewsEvent) ON (n.timestamp)",
                "CREATE INDEX condition_symbol IF NOT EXISTS FOR (mc:MarketCondition) ON (mc.symbol)",
                "CREATE INDEX causal_chain_created IF NOT EXISTS FOR (cc:CausalChain) ON (cc.created_at)",
                "CREATE INDEX trade_reasoning_symbol IF NOT EXISTS FOR (tr:TradeReasoning) ON (tr.symbol)",
                "CREATE INDEX trade_reasoning_setup IF NOT EXISTS FOR (tr:TradeReasoning) ON (tr.setup_type)",
            ]
            for stmt in constraints + indexes:
                try:
                    session.run(stmt)
                except Exception as e:
                    logger.debug("Schema stmt skipped: %s", e)

            logger.info("Graph schema initialized")

    # ========================================================================
    # WRITE METHODS (Phase 1 — passive recording)
    # ========================================================================

    def record_trade(self, trade_data: Dict[str, Any]) -> Optional[str]:
        """
        Record a closed trade with full context into the graph.

        Args:
            trade_data: Dict with keys from the Trade model + TradeFeature
        """
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_trade_tx, trade_data)
                logger.info("Recorded trade %s in graph", result)
                return result
        except Exception as e:
            logger.error("Failed to record trade: %s", e)
            return None

    @staticmethod
    def _create_trade_tx(tx, d: Dict[str, Any]) -> str:
        trade_id = str(d.get('trade_id', uuid.uuid4()))
        symbol = d.get('symbol', 'UNKNOWN')
        market_type = SYMBOL_MARKET_TYPE.get(symbol, 'FOREX')
        hour_utc = d.get('hour_utc', 0)
        session_name = d.get('session', _get_session(hour_utc))

        query = """
        MERGE (sym:Symbol {id: $symbol})
          ON CREATE SET sym.market_type = $market_type, sym.created_at = datetime()

        CREATE (t:Trade {
            id: $trade_id,
            django_trade_id: $django_id,
            symbol: $symbol,
            direction: $direction,
            venue: $venue,
            domain: $domain,
            entry_time: datetime($entry_time),
            close_time: datetime($close_time),
            entry_price: $entry_price,
            close_price: $close_price,
            pnl: $pnl,
            return_r: $return_r,
            entry_atr: $entry_atr,
            strategy: $strategy,
            closing_reason: $closing_reason,
            confluence_score: $confluence_score,
            regime_at_entry: $regime_at_entry,
            regime_confidence: $regime_confidence,
            session: $session,
            hour_utc: $hour_utc,
            day_of_week: $day_of_week,
            duration_minutes: $duration_minutes,
            trading_era: $trading_era,
            mtf_bias: $mtf_bias,
            mtf_confidence: $mtf_confidence,
            mtf_alignment: $mtf_alignment,
            mtf_alignment_score: $mtf_alignment_score,
            sl_source: $sl_source,
            tp_source: $tp_source,
            sl_tp_rr: $sl_tp_rr,
            graph_confidence: $graph_confidence,
            graph_recommendation: $graph_recommendation,
            graph_size_modifier: $graph_size_modifier,
            news_risk_at_entry: $news_risk_at_entry
        })
        CREATE (t)-[:TRADED_SYMBOL]->(sym)

        MERGE (strat:Strategy {name: $strategy})
        CREATE (t)-[:EXECUTED_BY]->(strat)

        RETURN t.id as trade_id
        """

        entry_time = d.get('entry_time', datetime.utcnow())
        close_time = d.get('close_time', datetime.utcnow())
        if hasattr(entry_time, 'isoformat'):
            entry_time = entry_time.isoformat()
        if hasattr(close_time, 'isoformat'):
            close_time = close_time.isoformat()

        entry_price = d.get('entry_price', 0)
        close_price = d.get('close_price', 0)
        entry_atr = d.get('entry_atr', 0) or 0.0001
        pnl = d.get('pnl', 0)

        # Compute R-multiple
        try:
            risk_per_unit = entry_atr * 1.8  # SL_ATR_MULTIPLIER
            return_r = round(pnl / (risk_per_unit * 100) if risk_per_unit > 0 else 0, 3)
        except (TypeError, ZeroDivisionError):
            return_r = 0.0

        # Compute duration
        try:
            et = d.get('entry_time', datetime.utcnow())
            ct = d.get('close_time', datetime.utcnow())
            if hasattr(et, 'timestamp') and hasattr(ct, 'timestamp'):
                duration_minutes = round((ct.timestamp() - et.timestamp()) / 60, 1)
            else:
                duration_minutes = 0
        except Exception:
            duration_minutes = 0

        # Determine venue: MT5 (forex broker) or LIGHTER (DEX) or HYPERLIQUID
        venue = d.get('venue', 'MT5')
        # Domain groups: FOREX_MT5, CRYPTO_DEX, METAL_DEX, etc.
        domain = f"{market_type}_{venue}"

        result = tx.run(
            query,
            trade_id=trade_id,
            django_id=d.get('django_id', 0),
            symbol=symbol,
            market_type=market_type,
            venue=venue,
            domain=domain,
            direction=d.get('direction', 'BUY'),
            entry_time=entry_time,
            close_time=close_time,
            entry_price=float(entry_price or 0),
            close_price=float(close_price or 0),
            pnl=float(pnl or 0),
            return_r=return_r,
            entry_atr=float(entry_atr or 0),
            strategy=d.get('strategy', 'unknown'),
            closing_reason=d.get('closing_reason', ''),
            confluence_score=int(d.get('confluence_score', 0) or 0),
            regime_at_entry=d.get('regime_at_entry', 'UNKNOWN'),
            regime_confidence=float(d.get('regime_confidence', 0) or 0),
            session=session_name,
            hour_utc=hour_utc,
            day_of_week=d.get('day_of_week', 0),
            duration_minutes=duration_minutes,
            trading_era=d.get('trading_era', 'BRAIN_V1'),
            mtf_bias=d.get('mtf_bias', 'UNKNOWN'),
            mtf_confidence=float(d.get('mtf_confidence', 0) or 0),
            mtf_alignment=d.get('mtf_alignment', 'UNKNOWN'),
            mtf_alignment_score=float(d.get('mtf_alignment_score', 0) or 0),
            sl_source=d.get('sl_source', 'ATR'),
            tp_source=d.get('tp_source', 'ATR'),
            sl_tp_rr=float(d.get('sl_tp_rr', 0) or 0),
            graph_confidence=float(d.get('graph_confidence', 0.5) or 0.5),
            graph_recommendation=d.get('graph_recommendation', 'NORMAL'),
            graph_size_modifier=float(d.get('graph_size_modifier', 1.0) or 1.0),
            news_risk_at_entry=d.get('news_risk', 'NORMAL'),
        )
        record = result.single()
        return record['trade_id'] if record else trade_id

    def record_trade_open(self, trade_data: Dict[str, Any]) -> Optional[str]:
        """
        Record a trade OPEN into the graph (no close_time/pnl yet).
        Creates a Trade node with status='OPEN'. On close, update_trade_close()
        fills in the closing fields.
        """
        if not self.connected:
            return None
        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_trade_open_tx, trade_data)
                logger.info("Recorded trade open %s in graph", result)
                return result
        except Exception as e:
            err = str(e)
            if 'already exists' in err or 'ConstraintValidation' in err:
                logger.debug("Trade open %s already in graph (duplicate)", trade_data.get('trade_id'))
                return trade_data.get('trade_id')
            logger.error("Failed to record trade open: %s", e)
            return None

    @staticmethod
    def _create_trade_open_tx(tx, d: Dict[str, Any]) -> str:
        trade_id = str(d.get('trade_id', uuid.uuid4()))
        symbol = d.get('symbol', 'UNKNOWN')
        market_type = SYMBOL_MARKET_TYPE.get(symbol, 'FOREX')
        hour_utc = d.get('hour_utc', 0)
        session_name = d.get('session', _get_session(hour_utc))
        venue = d.get('venue', 'MT5')
        domain = d.get('domain', f"{market_type}_{venue}")

        entry_time = d.get('entry_time', datetime.utcnow())
        if hasattr(entry_time, 'isoformat'):
            entry_time = entry_time.isoformat()

        query = """
        MERGE (sym:Symbol {id: $symbol})
          ON CREATE SET sym.market_type = $market_type, sym.created_at = datetime()
        CREATE (t:Trade {
            id: $trade_id,
            django_trade_id: $django_id,
            symbol: $symbol,
            direction: $direction,
            venue: $venue,
            domain: $domain,
            entry_time: datetime($entry_time),
            entry_price: $entry_price,
            strategy: $strategy,
            session: $session,
            hour_utc: $hour_utc,
            day_of_week: $day_of_week,
            trading_era: $trading_era,
            status: 'OPEN'
        })
        CREATE (t)-[:TRADED_SYMBOL]->(sym)
        MERGE (strat:Strategy {name: $strategy})
        CREATE (t)-[:EXECUTED_BY]->(strat)
        RETURN t.id as trade_id
        """
        result = tx.run(
            query,
            trade_id=trade_id,
            django_id=d.get('django_id', 0),
            symbol=symbol,
            direction=d.get('direction', 'BUY'),
            venue=venue,
            domain=domain,
            market_type=market_type,
            entry_time=entry_time,
            entry_price=float(d.get('entry_price', 0)),
            strategy=d.get('strategy', 'unknown'),
            session=session_name,
            hour_utc=hour_utc,
            day_of_week=d.get('day_of_week', 0),
            trading_era=d.get('trading_era', 'BRAIN_V1'),
        )
        record = result.single()
        return record['trade_id'] if record else trade_id

    def update_trade_close(self, trade_data: Dict[str, Any]) -> Optional[str]:
        """
        Update an existing OPEN trade node with closing data.
        If the trade node doesn't exist, falls back to record_trade (full create).
        """
        if not self.connected:
            return None
        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._update_trade_close_tx, trade_data)
                if result:
                    logger.info("Updated trade close %s in graph", result)
                    return result
                # Node didn't exist — fall back to full create
                logger.debug("Trade %s not found for update, creating full record",
                             trade_data.get('trade_id'))
                return self.record_trade(trade_data)
        except Exception as e:
            logger.error("Failed to update trade close: %s", e)
            return None

    @staticmethod
    def _update_trade_close_tx(tx, d: Dict[str, Any]) -> Optional[str]:
        trade_id = str(d.get('trade_id', ''))
        if not trade_id:
            return None

        close_time = d.get('close_time', datetime.utcnow())
        if hasattr(close_time, 'isoformat'):
            close_time = close_time.isoformat()

        query = """
        MATCH (t:Trade {id: $trade_id})
        SET t.close_time = datetime($close_time),
            t.close_price = $close_price,
            t.pnl = $pnl,
            t.closing_reason = $closing_reason,
            t.status = 'CLOSED'
        RETURN t.id as trade_id
        """
        result = tx.run(
            query,
            trade_id=trade_id,
            close_time=close_time,
            close_price=float(d.get('close_price', 0)),
            pnl=float(d.get('pnl', 0)),
            closing_reason=d.get('closing_reason', ''),
        )
        record = result.single()
        return record['trade_id'] if record else None

    def record_trade_reasoning(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Record WHY a trade was taken as a separate TradeReasoning node.

        Stores the multi-timeframe context, entry logic, confirmations,
        graph advisor state, SL/TP reasoning, and a human-readable summary.
        Linked to the Trade node via REASONING_FOR relationship.

        Args:
            data: Dict with reasoning fields collected at trade entry time.
        """
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_trade_reasoning_tx, data)
                logger.info("Recorded trade reasoning %s for trade %s",
                            result, data.get('trade_id'))
                return result
        except Exception as e:
            logger.error("Failed to record trade reasoning: %s", e)
            return None

    @staticmethod
    def _create_trade_reasoning_tx(tx, d: Dict[str, Any]) -> str:
        reasoning_id = f"reasoning_{d.get('trade_id', uuid.uuid4())}"
        trade_id = d.get('trade_id', '')

        # Build the trade_id reference used to link to Trade node.
        # CVD entry stores Trade.id (int), graph stores "trade_{id}".
        trade_node_id = f"trade_{trade_id}" if not str(trade_id).startswith('trade_') else trade_id

        tx.run("""
            CREATE (tr:TradeReasoning {
                id: $reasoning_id,
                trade_id: $trade_id,
                symbol: $symbol,
                direction: $direction,

                htf_trend: $htf_trend,
                htf_phase: $htf_phase,
                ltf_trend: $ltf_trend,
                ltf_phase: $ltf_phase,
                mtf_alignment: $mtf_alignment,
                mtf_alignment_score: $mtf_alignment_score,
                mtf_bias: $mtf_bias,
                mtf_confidence: $mtf_confidence,

                setup_type: $setup_type,
                entry_zone: $entry_zone,
                entry_zone_price: $entry_zone_price,
                entry_source: $entry_source,

                vwap_bias: $vwap_bias,
                orderbook_bias: $orderbook_bias,
                news_risk: $news_risk,
                news_size_mult: $news_size_mult,
                llm_decision: $llm_decision,
                llm_confidence: $llm_confidence,

                graph_confidence: $graph_confidence,
                graph_recommendation: $graph_recommendation,
                similar_setups_wr: $similar_setups_wr,
                similar_setups_count: $similar_setups_count,

                sl_source: $sl_source,
                tp_source: $tp_source,
                sl_reasoning: $sl_reasoning,
                tp_reasoning: $tp_reasoning,
                rr_ratio: $rr_ratio,

                confluence_score: $confluence_score,
                confluence_band: $confluence_band,
                regime_at_entry: $regime_at_entry,
                regime_confidence: $regime_confidence,

                size_multiplier: $size_multiplier,
                strategy: $strategy,

                reasoning_text: $reasoning_text,
                created_at: datetime()
            })
            WITH tr
            OPTIONAL MATCH (t:Trade {id: $trade_node_id})
            FOREACH (_ IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
                CREATE (tr)-[:REASONING_FOR]->(t)
            )
        """,
            reasoning_id=reasoning_id,
            trade_id=str(trade_id),
            trade_node_id=trade_node_id,
            symbol=d.get('symbol', 'UNKNOWN'),
            direction=d.get('direction', 'UNKNOWN'),

            htf_trend=d.get('htf_trend', 'UNKNOWN'),
            htf_phase=d.get('htf_phase', 'UNKNOWN'),
            ltf_trend=d.get('ltf_trend', 'UNKNOWN'),
            ltf_phase=d.get('ltf_phase', 'UNKNOWN'),
            mtf_alignment=d.get('mtf_alignment', 'UNKNOWN'),
            mtf_alignment_score=float(d.get('mtf_alignment_score', 0) or 0),
            mtf_bias=d.get('mtf_bias', 'UNKNOWN'),
            mtf_confidence=float(d.get('mtf_confidence', 0) or 0),

            setup_type=d.get('setup_type', 'UNKNOWN'),
            entry_zone=d.get('entry_zone', 'UNKNOWN'),
            entry_zone_price=float(d.get('entry_zone_price', 0) or 0),
            entry_source=d.get('entry_source', 'UNKNOWN'),

            vwap_bias=d.get('vwap_bias', 'NEUTRAL'),
            orderbook_bias=d.get('orderbook_bias', 'NEUTRAL'),
            news_risk=d.get('news_risk', 'NORMAL'),
            news_size_mult=float(d.get('news_size_mult', 1.0) or 1.0),
            llm_decision=d.get('llm_decision', ''),
            llm_confidence=float(d.get('llm_confidence', 0) or 0),

            graph_confidence=float(d.get('graph_confidence', 0.5) or 0.5),
            graph_recommendation=d.get('graph_recommendation', 'NORMAL'),
            similar_setups_wr=float(d.get('similar_setups_wr', 0) or 0),
            similar_setups_count=int(d.get('similar_setups_count', 0) or 0),

            sl_source=d.get('sl_source', 'ATR'),
            tp_source=d.get('tp_source', 'ATR'),
            sl_reasoning=d.get('sl_reasoning', ''),
            tp_reasoning=d.get('tp_reasoning', ''),
            rr_ratio=float(d.get('rr_ratio', 0) or 0),

            confluence_score=int(d.get('confluence_score', 0) or 0),
            confluence_band=d.get('confluence_band', ''),
            regime_at_entry=d.get('regime_at_entry', 'UNKNOWN'),
            regime_confidence=float(d.get('regime_confidence', 0) or 0),

            size_multiplier=float(d.get('size_multiplier', 1.0) or 1.0),
            strategy=d.get('strategy', 'unknown'),

            reasoning_text=d.get('reasoning_text', ''),
        )

        return reasoning_id

    def record_market_condition(self, symbol: str, condition: Dict[str, Any]) -> Optional[str]:
        """Record current market condition snapshot for a symbol."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                return session.execute_write(
                    self._create_condition_tx, symbol, condition
                )
        except Exception as e:
            logger.error("Failed to record condition for %s: %s", symbol, e)
            return None

    @staticmethod
    def _create_condition_tx(tx, symbol: str, c: Dict[str, Any]) -> str:
        mc_id = str(uuid.uuid4())
        hour_utc = datetime.utcnow().hour
        regime = c.get('label', c.get('regime', 'UNKNOWN'))

        # Create MarketCondition
        tx.run("""
            MERGE (sym:Symbol {id: $symbol})
            CREATE (mc:MarketCondition {
                id: $mc_id,
                symbol: $symbol,
                timestamp: datetime(),
                regime: $regime,
                direction: $direction,
                adx: $adx,
                bb_width: $bb_width,
                atr_ratio: $atr_ratio,
                confidence: $confidence,
                hmm_state: $hmm_state,
                session: $session,
                hour_utc: $hour_utc,
                day_of_week: $day_of_week
            })
        """,
            mc_id=mc_id,
            symbol=symbol,
            regime=regime,
            direction=c.get('direction', 'NEUTRAL'),
            adx=float(c.get('adx', 0) or 0),
            bb_width=float(c.get('bb_width', 0) or 0),
            atr_ratio=float(c.get('atr_ratio', 0) or 0),
            confidence=float(c.get('confidence', 0) or 0),
            hmm_state=int(c.get('state', 0) or 0),
            session=_get_session(hour_utc),
            hour_utc=hour_utc,
            day_of_week=datetime.utcnow().weekday(),
        )

        # Also maintain a Regime node (MERGE = deduplicate)
        regime_id = f"{symbol}_{regime}_{datetime.utcnow().strftime('%Y%m%d%H')}"
        tx.run("""
            MERGE (r:Regime {id: $regime_id})
              ON CREATE SET
                r.symbol = $symbol,
                r.label = $regime,
                r.direction = $direction,
                r.confidence = $confidence,
                r.adx = $adx,
                r.bb_width = $bb_width,
                r.atr_ratio = $atr_ratio,
                r.hmm_state = $hmm_state,
                r.recorded_at = datetime()
              ON MATCH SET
                r.confidence = $confidence,
                r.adx = $adx,
                r.direction = $direction
            MERGE (sym:Symbol {id: $symbol})
            MERGE (r)-[:FOR_SYMBOL]->(sym)
        """,
            regime_id=regime_id,
            symbol=symbol,
            regime=regime,
            direction=c.get('direction', 'NEUTRAL'),
            confidence=float(c.get('confidence', 0) or 0),
            adx=float(c.get('adx', 0) or 0),
            bb_width=float(c.get('bb_width', 0) or 0),
            atr_ratio=float(c.get('atr_ratio', 0) or 0),
            hmm_state=int(c.get('state', 0) or 0),
        )

        return mc_id

    def record_regime_transition(self, symbol: str, from_regime: str,
                                  to_regime: str, meta: Dict[str, Any] = None) -> Optional[str]:
        """Record a regime change event."""
        if not self.connected:
            return None

        meta = meta or {}
        try:
            with self.driver.session(database=self.database) as session:
                rt_id = str(uuid.uuid4())
                session.execute_write(
                    self._create_transition_tx, rt_id, symbol,
                    from_regime, to_regime, meta
                )
                logger.info("Regime transition: %s %s → %s", symbol, from_regime, to_regime)
                return rt_id
        except Exception as e:
            logger.error("Failed to record transition: %s", e)
            return None

    @staticmethod
    def _create_transition_tx(tx, rt_id, symbol, from_regime, to_regime, meta):
        tx.run("""
            MERGE (sym:Symbol {id: $symbol})
            CREATE (rt:RegimeTransition {
                id: $rt_id,
                symbol: $symbol,
                from_regime: $from_regime,
                to_regime: $to_regime,
                occurred_at: datetime(),
                confidence_before: $conf_before,
                confidence_after: $conf_after
            })
            CREATE (rt)-[:TRANSITION_ON]->(sym)
        """,
            rt_id=rt_id,
            symbol=symbol,
            from_regime=from_regime,
            to_regime=to_regime,
            conf_before=float(meta.get('confidence_before', 0)),
            conf_after=float(meta.get('confidence_after', 0)),
        )

    def record_news(self, articles: List[Dict[str, Any]]) -> int:
        """Batch-record news articles. Returns count of new articles created."""
        if not self.connected or not articles:
            return 0

        try:
            with self.driver.session(database=self.database) as session:
                count = session.execute_write(self._create_news_batch_tx, articles)
                return count
        except Exception as e:
            logger.error("Failed to record news: %s", e)
            return 0

    @staticmethod
    def _create_news_batch_tx(tx, articles: List[Dict[str, Any]]) -> int:
        count = 0
        for article in articles[:20]:  # Cap at 20 per batch
            headline = article.get('headline', '')
            if not headline:
                continue

            # Use headline hash as ID for dedup
            news_id = str(hash(headline[:60]))

            tx.run("""
                MERGE (n:NewsEvent {id: $news_id})
                  ON CREATE SET
                    n.headline = $headline,
                    n.source = $source,
                    n.timestamp = datetime($timestamp),
                    n.category = $category,
                    n.url = $url
            """,
                news_id=news_id,
                headline=headline,
                source=article.get('source', ''),
                timestamp=datetime.utcnow().isoformat(),
                category=article.get('category', 'forex'),
                url=article.get('url', ''),
            )
            count += 1

        return count

    def record_rejected_signal(self, data: Dict[str, Any]) -> Optional[str]:
        """Record a signal that was detected but rejected by a filter layer."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_rejected_signal_tx, data)
                logger.info("Recorded rejected signal %s (%s)", result, data.get('rejection_layer'))
                return result
        except Exception as e:
            logger.error("Failed to record rejected signal: %s", e)
            return None

    @staticmethod
    def _create_rejected_signal_tx(tx, d: Dict[str, Any]) -> str:
        rs_id = str(uuid.uuid4())
        symbol = d.get('symbol', 'UNKNOWN')

        tx.run("""
            MERGE (sym:Symbol {id: $symbol})
            CREATE (rs:RejectedSignal {
                id: $rs_id,
                symbol: $symbol,
                direction: $direction,
                timestamp: datetime(),
                rejection_layer: $rejection_layer,
                rejection_reason: $rejection_reason,
                confluence_score: $confluence_score,
                regime_at_rejection: $regime_at_rejection,
                signal_strength: $signal_strength,
                would_have_won: $would_have_won
            })
            CREATE (rs)-[:ON_SYMBOL]->(sym)
        """,
            rs_id=rs_id,
            symbol=symbol,
            direction=d.get('direction', 'BUY'),
            rejection_layer=d.get('rejection_layer', 'unknown'),
            rejection_reason=d.get('rejection_reason', ''),
            confluence_score=int(d.get('confluence_score', 0) or 0),
            regime_at_rejection=d.get('regime_at_rejection', 'UNKNOWN'),
            signal_strength=float(d.get('signal_strength', 0) or 0),
            would_have_won=d.get('would_have_won', None),
        )

        return rs_id

    def record_exit_event(self, data: Dict[str, Any]) -> Optional[str]:
        """Record position manager phase transitions."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_exit_event_tx, data)
                logger.info("Recorded exit event %s (phase=%s)", result, data.get('phase'))
                return result
        except Exception as e:
            logger.error("Failed to record exit event: %s", e)
            return None

    @staticmethod
    def _create_exit_event_tx(tx, d: Dict[str, Any]) -> str:
        ee_id = str(uuid.uuid4())
        trade_id = d.get('trade_id', '')

        tx.run("""
            CREATE (ee:ExitEvent {
                id: $ee_id,
                trade_id: $trade_id,
                symbol: $symbol,
                phase: $phase,
                trigger_value: $trigger_value,
                action: $action,
                pnl_at_event: $pnl_at_event,
                minutes_in_trade: $minutes_in_trade,
                timestamp: datetime()
            })
            WITH ee
            OPTIONAL MATCH (t:Trade {id: $trade_id})
            FOREACH (_ IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
                CREATE (ee)-[:EXIT_FOR]->(t)
            )
        """,
            ee_id=ee_id,
            trade_id=trade_id,
            symbol=d.get('symbol', 'UNKNOWN'),
            phase=d.get('phase', 'UNKNOWN'),
            trigger_value=float(d.get('trigger_value', 0) or 0),
            action=d.get('action', ''),
            pnl_at_event=float(d.get('pnl_at_event', 0) or 0),
            minutes_in_trade=float(d.get('minutes_in_trade', 0) or 0),
        )

        return ee_id

    def record_confluence_breakdown(self, data: Dict[str, Any]) -> Optional[str]:
        """Record individual confluence factor scores for analysis."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_confluence_breakdown_tx, data)
                logger.info("Recorded confluence breakdown %s (total=%s)",
                            result, data.get('total_score'))
                return result
        except Exception as e:
            logger.error("Failed to record confluence breakdown: %s", e)
            return None

    @staticmethod
    def _create_confluence_breakdown_tx(tx, d: Dict[str, Any]) -> str:
        cb_id = str(uuid.uuid4())

        tx.run("""
            CREATE (cb:ConfluenceBreakdown {
                id: $cb_id,
                symbol: $symbol,
                direction: $direction,
                total_score: $total_score,
                htf_score: $htf_score,
                sweep_score: $sweep_score,
                cvd_score: $cvd_score,
                kill_zone_score: $kill_zone_score,
                fvg_score: $fvg_score,
                ob_score: $ob_score,
                regime_score: $regime_score,
                displacement_score: $displacement_score,
                timestamp: datetime(),
                resulted_in_trade: $resulted_in_trade
            })
        """,
            cb_id=cb_id,
            symbol=d.get('symbol', 'UNKNOWN'),
            direction=d.get('direction', 'BUY'),
            total_score=int(d.get('total_score', 0) or 0),
            htf_score=int(d.get('htf_score', 0) or 0),
            sweep_score=int(d.get('sweep_score', 0) or 0),
            cvd_score=int(d.get('cvd_score', 0) or 0),
            kill_zone_score=int(d.get('kill_zone_score', 0) or 0),
            fvg_score=int(d.get('fvg_score', 0) or 0),
            ob_score=int(d.get('ob_score', 0) or 0),
            regime_score=int(d.get('regime_score', 0) or 0),
            displacement_score=int(d.get('displacement_score', 0) or 0),
            resulted_in_trade=d.get('resulted_in_trade', False),
        )

        return cb_id

    def record_ict_partial(self, data: Dict[str, Any]) -> Optional[str]:
        """Record incomplete ICT 5-step chains for analysis."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_ict_partial_tx, data)
                logger.info("Recorded ICT partial %s (steps=%s, failed_at=%s)",
                            result, data.get('steps_completed'), data.get('failed_at_step'))
                return result
        except Exception as e:
            logger.error("Failed to record ICT partial: %s", e)
            return None

    @staticmethod
    def _create_ict_partial_tx(tx, d: Dict[str, Any]) -> str:
        ip_id = str(uuid.uuid4())
        symbol = d.get('symbol', 'UNKNOWN')

        tx.run("""
            MERGE (sym:Symbol {id: $symbol})
            CREATE (ip:ICTPartial {
                id: $ip_id,
                symbol: $symbol,
                direction: $direction,
                steps_completed: $steps_completed,
                failed_at_step: $failed_at_step,
                step1_bias: $step1_bias,
                step2_sweep: $step2_sweep,
                step3_mss: $step3_mss,
                step4_fvg: $step4_fvg,
                step5_price: $step5_price,
                timestamp: datetime()
            })
            CREATE (ip)-[:ON_SYMBOL]->(sym)
        """,
            ip_id=ip_id,
            symbol=symbol,
            direction=d.get('direction', 'BUY'),
            steps_completed=int(d.get('steps_completed', 0) or 0),
            failed_at_step=int(d.get('failed_at_step', 0) or 0),
            step1_bias=d.get('step1_bias', ''),
            step2_sweep=d.get('step2_sweep', False),
            step3_mss=d.get('step3_mss', ''),
            step4_fvg=d.get('step4_fvg', False),
            step5_price=d.get('step5_price', False),
        )

        return ip_id

    def record_htf_bias(self, data: Dict[str, Any]) -> Optional[str]:
        """Record H4 bias snapshot for a symbol."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_htf_bias_tx, data)
                logger.info("Recorded HTF bias %s (%s %s)",
                            result, data.get('symbol'), data.get('bias'))
                return result
        except Exception as e:
            logger.error("Failed to record HTF bias: %s", e)
            return None

    @staticmethod
    def _create_htf_bias_tx(tx, d: Dict[str, Any]) -> str:
        hb_id = str(uuid.uuid4())
        symbol = d.get('symbol', 'UNKNOWN')

        tx.run("""
            MERGE (sym:Symbol {id: $symbol})
            CREATE (hb:HTFBias {
                id: $hb_id,
                symbol: $symbol,
                bias: $bias,
                confidence: $confidence,
                ema_direction: $ema_direction,
                swing_structure: $swing_structure,
                premium_discount: $premium_discount,
                timestamp: datetime()
            })
            CREATE (hb)-[:FOR_SYMBOL]->(sym)
        """,
            hb_id=hb_id,
            symbol=symbol,
            bias=d.get('bias', 'NEUTRAL'),
            confidence=float(d.get('confidence', 0) or 0),
            ema_direction=d.get('ema_direction', 'FLAT'),
            swing_structure=d.get('swing_structure', 'UNKNOWN'),
            premium_discount=d.get('premium_discount', 'EQUILIBRIUM'),
        )

        return hb_id

    def record_performance_snapshot(self, data: Dict[str, Any]) -> Optional[str]:
        """Record daily performance stats."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_performance_snapshot_tx, data)
                logger.info("Recorded performance snapshot %s", result)
                return result
        except Exception as e:
            logger.error("Failed to record performance snapshot: %s", e)
            return None

    @staticmethod
    def _create_performance_snapshot_tx(tx, d: Dict[str, Any]) -> str:
        ps_id = d.get('id', datetime.utcnow().strftime('%Y-%m-%d'))

        tx.run("""
            MERGE (ps:PerformanceSnapshot {id: $ps_id})
              SET ps.date = $date,
                  ps.total_trades = $total_trades,
                  ps.wins = $wins,
                  ps.losses = $losses,
                  ps.win_rate = $win_rate,
                  ps.total_pnl = $total_pnl,
                  ps.sharpe = $sharpe,
                  ps.max_drawdown = $max_drawdown,
                  ps.best_trade_pnl = $best_trade_pnl,
                  ps.worst_trade_pnl = $worst_trade_pnl,
                  ps.timestamp = datetime()
        """,
            ps_id=ps_id,
            date=d.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
            total_trades=int(d.get('total_trades', 0) or 0),
            wins=int(d.get('wins', 0) or 0),
            losses=int(d.get('losses', 0) or 0),
            win_rate=float(d.get('win_rate', 0) or 0),
            total_pnl=float(d.get('total_pnl', 0) or 0),
            sharpe=float(d.get('sharpe', 0) or 0),
            max_drawdown=float(d.get('max_drawdown', 0) or 0),
            best_trade_pnl=float(d.get('best_trade_pnl', 0) or 0),
            worst_trade_pnl=float(d.get('worst_trade_pnl', 0) or 0),
        )

        return ps_id

    # ========================================================================
    # CAUSAL CHAINS — Claude-analyzed event→price patterns
    # ========================================================================

    def record_causal_chain(self, data: Dict[str, Any]) -> int:
        """Record causal chains from Claude's news analysis into the graph.

        Each chain becomes a CausalChain node linked to affected Symbol nodes
        via PREDICTS_IMPACT relationships. Chains are also linked to any
        matching NewsEvent nodes present in the graph.

        Args:
            data: Dict with keys:
                - chains: list of chain strings ("event → effect → price impact")
                - impacts: dict mapping symbol -> {direction, confidence, reason}
                - risk_level: 'NORMAL', 'ELEVATED', 'EXTREME'
                - overall_sentiment: 'RISK_ON', 'RISK_OFF', 'MIXED'

        Returns:
            Number of chains recorded.
        """
        if not self.connected:
            return 0

        chains = data.get('chains', [])
        if not chains:
            return 0

        try:
            with self.driver.session(database=self.database) as session:
                count = session.execute_write(
                    self._create_causal_chains_tx, data
                )
                logger.info("Recorded %d causal chains (risk=%s, sentiment=%s)",
                            count, data.get('risk_level'), data.get('overall_sentiment'))
                return count
        except Exception as e:
            logger.error("Failed to record causal chains: %s", e)
            return 0

    @staticmethod
    def _create_causal_chains_tx(tx, data: Dict[str, Any]) -> int:
        chains = data.get('chains', [])
        impacts = data.get('impacts', {})
        risk_level = data.get('risk_level', 'NORMAL')
        overall_sentiment = data.get('overall_sentiment', 'MIXED')
        count = 0

        for chain_text in chains[:10]:  # Cap at 10 chains per batch
            if not chain_text or not isinstance(chain_text, str):
                continue

            chain_id = f"cc_{uuid.uuid4().hex[:12]}"

            # Parse chain into individual events by splitting on arrow variants
            events = [
                e.strip() for e in re.split(r'\s*(?:→|->|=>)\s*', chain_text)
                if e.strip()
            ]

            # Create the CausalChain node
            tx.run("""
                CREATE (cc:CausalChain {
                    id: $chain_id,
                    chain_text: $chain_text,
                    events: $events,
                    source: $source,
                    created_at: datetime(),
                    risk_level: $risk_level,
                    overall_sentiment: $overall_sentiment
                })
            """,
                chain_id=chain_id,
                chain_text=chain_text,
                events=events,
                source='CLAUDE_HAIKU',
                risk_level=risk_level,
                overall_sentiment=overall_sentiment,
            )

            # Link to affected symbols via PREDICTS_IMPACT
            for symbol, impact in impacts.items():
                if not isinstance(impact, dict):
                    continue
                direction = impact.get('direction', 'NEUTRAL')
                confidence = float(impact.get('confidence', 0.5) or 0.5)
                reason = impact.get('reason', '')

                tx.run("""
                    MATCH (cc:CausalChain {id: $chain_id})
                    MERGE (s:Symbol {id: $symbol})
                    CREATE (cc)-[:PREDICTS_IMPACT {
                        direction: $direction,
                        confidence: $confidence,
                        reason: $reason
                    }]->(s)
                """,
                    chain_id=chain_id,
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    reason=reason,
                )

            count += 1

        return count

    def query_causal_history(
        self,
        symbol: str,
        lookback_days: int = 7,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Query recent causal chains that predict impact on a symbol.

        Args:
            symbol: Trading instrument (e.g. 'XAUUSD')
            lookback_days: How far back to look (default 7 days)
            limit: Max chains to return (default 5)

        Returns:
            List of dicts with keys: chain_text, direction, confidence,
            risk_level, overall_sentiment, created_at
        """
        if not self.connected:
            return []

        cache_key = f"causal_history:{symbol}:{lookback_days}"
        from django.core.cache import cache
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_read(
                    self._query_causal_history_tx,
                    symbol, lookback_days, limit,
                )
                cache.set(cache_key, result, timeout=600)  # 10 minute cache
                return result
        except Exception as e:
            logger.debug("Causal history query failed for %s: %s", symbol, e)
            return []

    @staticmethod
    def _query_causal_history_tx(
        tx, symbol: str, lookback_days: int, limit: int,
    ) -> List[Dict[str, Any]]:
        result = tx.run("""
            MATCH (cc:CausalChain)-[p:PREDICTS_IMPACT]->(s:Symbol {id: $symbol})
            WHERE cc.created_at > datetime() - duration({days: $lookback_days})
            RETURN cc.chain_text AS chain_text,
                   p.direction AS direction,
                   p.confidence AS confidence,
                   cc.risk_level AS risk_level,
                   cc.overall_sentiment AS overall_sentiment,
                   cc.created_at AS created_at
            ORDER BY cc.created_at DESC
            LIMIT $limit
        """,
            symbol=symbol,
            lookback_days=lookback_days,
            limit=limit,
        )

        chains = []
        for record in result:
            created_at = record['created_at']
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            chains.append({
                'chain_text': record['chain_text'],
                'direction': record['direction'],
                'confidence': record['confidence'],
                'risk_level': record['risk_level'],
                'overall_sentiment': record['overall_sentiment'],
                'created_at': str(created_at),
            })
        return chains

    # ========================================================================
    # ERA TRACKING — Brain vs Rule-Based trade classification
    # ========================================================================

    def record_era_transition(self, era_data: Dict[str, Any]) -> Optional[str]:
        """Record a transition between trading eras.

        Creates a TradingEra node that marks when the system upgraded.
        Old trades link to 'RULE_BASED' era, new trades to 'BRAIN_V1'.
        """
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._create_era_transition_tx, era_data)
                logger.info("Recorded era transition to %s", era_data.get('era_name'))
                return result
        except Exception as e:
            logger.error("Failed to record era transition: %s", e)
            return None

    @staticmethod
    def _create_era_transition_tx(tx, d: Dict[str, Any]) -> str:
        era_name = d.get('era_name', 'UNKNOWN')
        started_at = d.get('started_at', datetime.utcnow().isoformat())
        if hasattr(started_at, 'isoformat'):
            started_at = started_at.isoformat()

        # Capabilities is a list of strings
        capabilities = d.get('capabilities', [])
        if not isinstance(capabilities, list):
            capabilities = []

        tx.run("""
            MERGE (e:TradingEra {name: $era_name})
            ON CREATE SET
                e.started_at = datetime($started_at),
                e.description = $description,
                e.capabilities = $capabilities,
                e.previous_era = $previous_era
        """,
            era_name=era_name,
            started_at=started_at,
            description=d.get('description', ''),
            capabilities=capabilities,
            previous_era=d.get('previous_era', ''),
        )

        # If there is a previous era, create a SUCCEEDED_BY relationship
        previous_era = d.get('previous_era', '')
        if previous_era:
            tx.run("""
                MATCH (prev:TradingEra {name: $previous_era})
                MATCH (curr:TradingEra {name: $era_name})
                MERGE (prev)-[:SUCCEEDED_BY]->(curr)
            """,
                previous_era=previous_era,
                era_name=era_name,
            )

        return era_name

    def backfill_trading_era(self) -> int:
        """Tag all existing trades without a trading_era as RULE_BASED.

        Returns the count of updated trades.
        """
        if not self.connected:
            return 0

        try:
            with self.driver.session(database=self.database) as session:
                result = session.execute_write(self._backfill_era_tx)
                logger.info("Backfilled %d trades as RULE_BASED", result)
                return result
        except Exception as e:
            logger.error("Failed to backfill trading era: %s", e)
            return 0

    @staticmethod
    def _backfill_era_tx(tx) -> int:
        result = tx.run("""
            MATCH (t:Trade) WHERE t.trading_era IS NULL
            SET t.trading_era = 'RULE_BASED',
                t.sl_source = 'ATR',
                t.tp_source = 'ATR',
                t.graph_confidence = 0.5,
                t.graph_recommendation = 'NORMAL'
            RETURN count(t) as updated
        """)
        record = result.single()
        return record['updated'] if record else 0

    # ========================================================================
    # READ METHODS (Phase 2 — activated after sufficient data)
    # ========================================================================

    def find_similar_conditions(self, symbol: str, regime: str,
                                 adx: float, bb_width: float,
                                 session_name: str, hour_utc: int,
                                 tolerance: float = 0.2,
                                 limit: int = 20) -> Optional[Dict]:
        """Find historical trades in similar market conditions."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_read(
                    self._similar_conditions_query,
                    symbol, regime, adx, bb_width, session_name,
                    hour_utc, tolerance, limit
                )
        except Exception as e:
            logger.debug("Similar conditions query failed: %s", e)
            return None

    @staticmethod
    def _similar_conditions_query(tx, symbol, regime, adx, bb_width,
                                   session_name, hour_utc, tolerance, limit):
        result = tx.run("""
            MATCH (t:Trade {symbol: $symbol, regime_at_entry: $regime})
            WHERE t.session = $session
              AND t.hour_utc >= $hour - 1 AND t.hour_utc <= $hour + 1
            WITH t
            ORDER BY t.entry_time DESC
            LIMIT $limit
            RETURN
                count(t) as total,
                sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
                    CASE WHEN count(t) > 0 THEN count(t) ELSE 1 END as win_rate,
                avg(t.return_r) as avg_r,
                avg(t.confluence_score) as avg_confluence
        """,
            symbol=symbol, regime=regime, session=session_name,
            hour=hour_utc, limit=limit
        )
        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def get_strategy_regime_performance(self, strategy_name: str,
                                         regime: str,
                                         lookback_days: int = 90) -> Optional[Dict]:
        """Get a strategy's historical performance in a specific regime."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_read(
                    self._strategy_regime_query,
                    strategy_name, regime, lookback_days
                )
        except Exception as e:
            logger.debug("Strategy regime query failed: %s", e)
            return None

    @staticmethod
    def _strategy_regime_query(tx, strategy_name, regime, lookback_days):
        result = tx.run("""
            MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy {name: $strategy})
            WHERE t.regime_at_entry = $regime
              AND t.entry_time > datetime() - duration({days: $days})
            RETURN
                count(t) as total,
                sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
                    CASE WHEN count(t) > 0 THEN count(t) ELSE 1 END as win_rate,
                avg(t.return_r) as avg_r,
                avg(t.pnl) as avg_pnl
        """,
            strategy=strategy_name, regime=regime, days=lookback_days
        )
        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def get_symbol_regime_history(self, symbol: str, regime: str,
                                   lookback_days: int = 90) -> Optional[Dict]:
        """Get how a symbol performs in a specific regime historically."""
        if not self.connected:
            return None

        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_read(
                    self._symbol_regime_query, symbol, regime, lookback_days
                )
        except Exception as e:
            logger.debug("Symbol regime query failed: %s", e)
            return None

    @staticmethod
    def _symbol_regime_query(tx, symbol, regime, lookback_days):
        result = tx.run("""
            MATCH (t:Trade {symbol: $symbol, regime_at_entry: $regime})
            WHERE t.entry_time > datetime() - duration({days: $days})
            RETURN
                count(t) as total,
                sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
                    CASE WHEN count(t) > 0 THEN count(t) ELSE 1 END as win_rate,
                avg(t.confluence_score) as avg_confluence,
                avg(t.return_r) as avg_r
        """,
            symbol=symbol, regime=regime, days=lookback_days
        )
        record = result.single()
        if record and record['total'] > 0:
            return dict(record)
        return None

    def get_graph_summary(self) -> Dict[str, Any]:
        """Get node counts and overall stats for the dashboard."""
        if not self.connected:
            return {'connected': False}

        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_read(self._summary_query)
        except Exception as e:
            logger.debug("Summary query failed: %s", e)
            return {'connected': False, 'error': str(e)}

    @staticmethod
    def _summary_query(tx):
        result = tx.run("""
            MATCH (t:Trade)
            WITH count(t) as trades,
                 sum(t.pnl) as total_pnl,
                 CASE WHEN count(t) > 0
                      THEN sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 / count(t)
                      ELSE 0 END as win_rate
            OPTIONAL MATCH (s:Symbol)
            WITH trades, total_pnl, win_rate, count(s) as symbols
            OPTIONAL MATCH (st:Strategy)
            WITH trades, total_pnl, win_rate, symbols, count(st) as strategies
            OPTIONAL MATCH (r:Regime)
            WITH trades, total_pnl, win_rate, symbols, strategies, count(r) as regimes
            OPTIONAL MATCH (n:NewsEvent)
            WITH trades, total_pnl, win_rate, symbols, strategies, regimes, count(n) as news
            OPTIONAL MATCH (mc:MarketCondition)
            RETURN trades, total_pnl, win_rate, symbols, strategies,
                   regimes, news, count(mc) as conditions
        """)
        record = result.single()
        if record:
            d = dict(record)
            d['connected'] = True
            return d
        return {'connected': True, 'trades': 0}

    def record_reference_trade(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Seed a synthetic/backtested reference trade node into the brain.

        These nodes carry weight=0.3 (vs live trades weight=1.0) so live trades
        progressively dominate as they accumulate. The weight field lets the brain's
        similarity queries discount synthetic evidence without discarding it entirely.

        Expected keys in data:
          symbol, direction, entry_price, sl_price, tp_price, rr_ratio,
          outcome (WIN/LOSS/TRAILING_EXIT/EXPIRED), exit_price, pnl_r,
          bars_held, max_favorable_excursion, max_adverse_excursion,
          trigger_time (ISO str), exit_time (ISO str),
          confluence_score, era_sentiment,
          htf_bias, session, fvg_present (bool), ob_present (bool),
          fib_present (bool), cvd_divergence (bool),
          nearby_geo_events (list of dicts),
          source ('BACKTEST_SEED'), weight (float, default 0.3)
        """
        if not self.connected:
            return None
        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_write(self._create_reference_trade_tx, data)
        except Exception as e:
            logger.warning(f"record_reference_trade failed: {e}")
            return None

    @staticmethod
    def _create_reference_trade_tx(tx, d: Dict[str, Any]) -> str:
        import uuid
        node_id = str(uuid.uuid4())
        symbol = d.get('symbol', 'UNKNOWN')
        market_type = SYMBOL_MARKET_TYPE.get(symbol, 'UNKNOWN')
        weight = d.get('weight', 0.3)
        source = d.get('source', 'BACKTEST_SEED')

        cypher = """
        MERGE (s:Symbol {name: $symbol})
        ON CREATE SET s.market_type = $market_type

        CREATE (t:Trade {
            id:                     $node_id,
            symbol:                 $symbol,
            market_type:            $market_type,
            direction:              $direction,
            entry_price:            $entry_price,
            sl_price:               $sl_price,
            tp_price:               $tp_price,
            rr_ratio:               $rr_ratio,
            outcome:                $outcome,
            exit_price:             $exit_price,
            pnl_r:                  $pnl_r,
            bars_held:              $bars_held,
            mfe:                    $mfe,
            mae:                    $mae,
            trigger_time:           $trigger_time,
            exit_time:              $exit_time,
            confluence_score:       $confluence_score,
            era_sentiment:          $era_sentiment,
            htf_bias:               $htf_bias,
            session:                $session,
            fvg_present:            $fvg_present,
            ob_present:             $ob_present,
            fib_present:            $fib_present,
            cvd_divergence:         $cvd_divergence,
            source:                 $source,
            weight:                 $weight,
            is_winner:              $is_winner,
            created_at:             $now
        })

        MERGE (t)-[:ON_SYMBOL]->(s)

        WITH t
        MATCH (era:TradingEra {name: 'BRAIN_V1'})
        MERGE (t)-[:IN_ERA]->(era)

        RETURN t.id AS node_id
        """

        result = tx.run(
            cypher,
            node_id=node_id,
            symbol=symbol,
            market_type=market_type,
            direction=d.get('direction', ''),
            entry_price=float(d.get('entry_price', 0)),
            sl_price=float(d.get('sl_price', 0)),
            tp_price=float(d.get('tp_price', 0)),
            rr_ratio=float(d.get('rr_ratio', 2.0)),
            outcome=d.get('outcome', 'UNKNOWN'),
            exit_price=float(d.get('exit_price', 0)),
            pnl_r=float(d.get('pnl_r', 0)),
            bars_held=int(d.get('bars_held', 0)),
            mfe=float(d.get('max_favorable_excursion', 0)),
            mae=float(d.get('max_adverse_excursion', 0)),
            trigger_time=d.get('trigger_time', ''),
            exit_time=d.get('exit_time', ''),
            confluence_score=float(d.get('confluence_score', 0)),
            era_sentiment=d.get('era_sentiment', 'neutral'),
            htf_bias=d.get('htf_bias', 'neutral'),
            session=d.get('session', 'UNKNOWN'),
            fvg_present=bool(d.get('fvg_present', False)),
            ob_present=bool(d.get('ob_present', False)),
            fib_present=bool(d.get('fib_present', False)),
            cvd_divergence=bool(d.get('cvd_divergence', False)),
            source=source,
            weight=float(weight),
            is_winner=d.get('outcome') == 'WIN',
            now=datetime.utcnow().isoformat(),
        )
        row = result.single()
        return row['node_id'] if row else node_id

    def record_geopolitical_event(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Seed a geopolitical event as a context node.

        Trade nodes recorded during ±24h of an event will be linked to it via
        NEAR_EVENT relationship, allowing queries like:
        "Does FVG_BOUNCE on XAUUSD have higher WR during active conflict periods?"

        Expected keys: date (ISO str), type, event, affected_classes, sentiment, intensity
        """
        if not self.connected:
            return None
        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_write(self._create_geo_event_tx, event)
        except Exception as e:
            logger.warning(f"record_geopolitical_event failed: {e}")
            return None

    @staticmethod
    def _create_geo_event_tx(tx, ev: Dict[str, Any]) -> str:
        import uuid
        node_id = str(uuid.uuid4())
        cypher = """
        MERGE (g:GeopoliticalEvent {
            event_date: $event_date,
            event_type: $event_type,
            event_text: $event_text
        })
        ON CREATE SET
            g.id               = $node_id,
            g.affected_classes = $affected_classes,
            g.sentiment        = $sentiment,
            g.intensity        = $intensity,
            g.created_at       = $now
        RETURN g.id AS node_id
        """
        result = tx.run(
            cypher,
            node_id=node_id,
            event_date=str(ev.get('date', '')),
            event_type=str(ev.get('type', '')),
            event_text=str(ev.get('event', '')),
            affected_classes=ev.get('affected_classes', []),
            sentiment=str(ev.get('sentiment', 'neutral')),
            intensity=float(ev.get('intensity', 0.5)),
            now=datetime.utcnow().isoformat(),
        )
        row = result.single()
        return row['node_id'] if row else node_id

    def link_trade_to_nearby_events(self, trade_node_id: str, nearby_events: List[Dict]) -> int:
        """
        Create NEAR_EVENT relationships between a trade node and nearby geo events.
        Called by backtest_seeder after seeding each reference trade.
        Returns number of relationships created.
        """
        if not self.connected or not nearby_events:
            return 0
        try:
            with self.driver.session(database=self.database) as sess:
                return sess.execute_write(
                    self._link_events_tx, trade_node_id, nearby_events
                )
        except Exception as e:
            logger.warning(f"link_trade_to_nearby_events failed: {e}")
            return 0

    @staticmethod
    def _link_events_tx(tx, trade_node_id: str, events: List[Dict]) -> int:
        count = 0
        for ev in events:
            result = tx.run(
                """
                MATCH (t:Trade {id: $trade_id})
                MATCH (g:GeopoliticalEvent {
                    event_date: $event_date,
                    event_text: $event_text
                })
                MERGE (t)-[r:NEAR_EVENT]->(g)
                ON CREATE SET r.created_at = $now
                RETURN r
                """,
                trade_id=trade_node_id,
                event_date=str(ev.get('date', '')),
                event_text=str(ev.get('event', '')),
                now=datetime.utcnow().isoformat(),
            )
            if result.single():
                count += 1
        return count

    def health_check(self) -> Dict[str, Any]:
        """Quick health probe."""
        if not self.connected:
            return {'connected': False, 'status': 'disconnected'}

        try:
            with self.driver.session(database=self.database) as sess:
                sess.run("RETURN 1")
            return {'connected': True, 'status': 'healthy'}
        except Exception as e:
            return {'connected': False, 'status': 'error', 'error': str(e)}


# ============================================================================
# ONE-TIME ERA MIGRATION
# Run via Django shell inside the django container:
#
#   docker exec -it django python manage.py shell
#
# Then paste:
#
#   from app.quant.knowledge.connection import get_graph
#   graph = get_graph()
#   if graph:
#       # 1. Backfill all existing trades as RULE_BASED
#       updated = graph.backfill_trading_era()
#       print(f"Backfilled {updated} trades as RULE_BASED")
#
#       # 2. Create the RULE_BASED era node
#       graph.record_era_transition({
#           'era_name': 'RULE_BASED',
#           'started_at': '2026-03-01T00:00:00',
#           'description': 'Static rule-based trading with hardcoded ATR SL/TP, '
#                          'fixed confluence gates, no MTF alignment, no graph advisor.',
#           'capabilities': [
#               'ATR-based SL/TP',
#               'confluence_scorer (0-14)',
#               'HMM regime detection',
#               'circuit breakers',
#               'news sentiment sizing',
#           ],
#           'previous_era': '',
#       })
#       print("Created RULE_BASED era node")
#
#       # 3. Create the BRAIN_V1 era node
#       graph.record_era_transition({
#           'era_name': 'BRAIN_V1',
#           'started_at': '2026-03-17T00:00:00',
#           'description': 'Autonomous trading brain with structure-based SL/TP, '
#                          'MTF context alignment, Neo4j pattern advisor pre-trade '
#                          'consultation, and news sentiment integration.',
#           'capabilities': [
#               'structure-based SL/TP (swing points, FVGs, OBs)',
#               'MTF bias + alignment scoring',
#               'Neo4j graph pre-trade advisor',
#               'news sentiment integration',
#               'dynamic graph-confidence sizing',
#               'ATR-based SL/TP (fallback)',
#               'confluence_scorer (0-14)',
#               'HMM regime detection',
#               'circuit breakers',
#           ],
#           'previous_era': 'RULE_BASED',
#       })
#       print("Created BRAIN_V1 era node")
#   else:
#       print("Could not connect to Neo4j")
# ============================================================================

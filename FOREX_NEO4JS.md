# Forex Neo4j Knowledge Graph — Queries & Brain State

> The brain's memory. Every query below runs live against `bolt://localhost:7687` (neo4j / trading_brain_2026)

---

## Current Brain State

| Node Type | Count | Description |
|-----------|-------|-------------|
| Trade | 310 | All recorded trades (236 RULE_BASED + 74 BRAIN_V1) |
| TradeReasoning | 18 | WHY each brain trade was taken |
| CausalChain | 0 (building) | Claude's event→impact chains |
| ICTPartial | 2,870 | ICT scanner attempts |
| RejectedSignal | 575 | Signals that didn't pass filters |
| ExitEvent | 444 | Position close events |
| Strategy | 34 | Strategy definitions |
| Symbol | 20 | Tradeable instruments |
| TradingEra | 2 | RULE_BASED → BRAIN_V1 |

| Relationship | Count | Connects |
|-------------|-------|----------|
| ON_SYMBOL | 3,445 | ICTPartial/RejectedSignal → Symbol |
| TRADED_SYMBOL | 310 | Trade → Symbol |
| EXECUTED_BY | 310 | Trade → Strategy |
| REASONING_FOR | 8 | TradeReasoning → Trade |
| SUCCEEDED_BY | 1 | RULE_BASED → BRAIN_V1 |
| PREDICTS_IMPACT | 0 (building) | CausalChain → Symbol |

### Era Performance

| Era | Trades | Wins | PnL |
|-----|--------|------|-----|
| RULE_BASED | 236 | 87 (37%) | -$134.58 |
| BRAIN_V1 | 74 | 41 (55%) | -$13.40 |

---

## Essential Queries

### 1. Full Brain Overview
See everything connected to everything:
```cypher
MATCH (n)-[r]->(m)
WHERE NOT n:ICTPartial AND NOT m:ICTPartial
  AND NOT n:RejectedSignal AND NOT m:RejectedSignal
RETURN n, r, m
```

### 2. Trading Eras
```cypher
MATCH (e:TradingEra)
OPTIONAL MATCH (e)-[s:SUCCEEDED_BY]->(next:TradingEra)
RETURN e.name, e.started_at, e.description, e.capabilities, next.name AS next_era
```

### 3. Brain vs Rule Performance
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL
RETURN
    COALESCE(t.trading_era, 'RULE_BASED') AS era,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    sum(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) AS losses,
    round(sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / count(t)) AS win_rate_pct,
    round(sum(t.pnl) * 100) / 100 AS total_pnl,
    round(avg(t.pnl) * 100) / 100 AS avg_pnl
ORDER BY era
```

---

## Strategy Analysis

### 4. Strategy Performance (All Time)
```cypher
MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy)
WHERE t.pnl IS NOT NULL
RETURN
    s.name AS strategy,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / count(t)) AS wr_pct,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY pnl DESC
```

### 5. Strategy Performance by Era
```cypher
MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy)
WHERE t.pnl IS NOT NULL
RETURN
    COALESCE(t.trading_era, 'RULE_BASED') AS era,
    s.name AS strategy,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY era, pnl DESC
```

### 6. Best Strategy Per Symbol
```cypher
MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy)
MATCH (t)-[:TRADED_SYMBOL]->(sym:Symbol)
WHERE t.pnl IS NOT NULL AND t.trading_era = 'BRAIN_V1'
RETURN
    sym.id AS symbol,
    s.name AS strategy,
    count(t) AS trades,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY symbol, pnl DESC
```

---

## Symbol Analysis

### 7. Symbol Performance
```cypher
MATCH (t:Trade)-[:TRADED_SYMBOL]->(s:Symbol)
WHERE t.pnl IS NOT NULL
RETURN
    s.id AS symbol,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / count(t)) AS wr_pct,
    round(sum(t.pnl) * 100) / 100 AS pnl,
    round(avg(CASE WHEN t.pnl > 0 THEN t.pnl END) * 100) / 100 AS avg_win,
    round(avg(CASE WHEN t.pnl <= 0 THEN t.pnl END) * 100) / 100 AS avg_loss
ORDER BY pnl DESC
```

### 8. Symbol by Direction
```cypher
MATCH (t:Trade)-[:TRADED_SYMBOL]->(s:Symbol)
WHERE t.pnl IS NOT NULL
RETURN
    s.id AS symbol,
    t.direction AS direction,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY symbol, direction
```

---

## Time Analysis

### 9. Performance by Hour (UTC)
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.hour_utc IS NOT NULL
RETURN
    t.hour_utc AS hour,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY hour
```

### 10. Performance by Session
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.hour_utc IS NOT NULL
WITH t,
    CASE
        WHEN t.hour_utc >= 0 AND t.hour_utc < 7 THEN 'Asian (00-07)'
        WHEN t.hour_utc >= 7 AND t.hour_utc < 12 THEN 'London (07-12)'
        WHEN t.hour_utc >= 12 AND t.hour_utc < 17 THEN 'NY (12-17)'
        ELSE 'Late NY (17-24)'
    END AS session
RETURN
    session,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY session
```

### 11. Performance by Day of Week
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.day_of_week IS NOT NULL
WITH t,
    CASE t.day_of_week
        WHEN 0 THEN 'Monday' WHEN 1 THEN 'Tuesday' WHEN 2 THEN 'Wednesday'
        WHEN 3 THEN 'Thursday' WHEN 4 THEN 'Friday'
        ELSE 'Weekend'
    END AS day_name
RETURN
    day_name,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY day_name
```

---

## Brain Intelligence Queries

### 12. Trade Reasoning — What Wins?
```cypher
MATCH (tr:TradeReasoning)-[:REASONING_FOR]->(t:Trade)
WHERE t.pnl > 0
RETURN
    tr.symbol,
    tr.direction,
    tr.setup_type,
    tr.entry_zone,
    tr.htf_trend,
    tr.mtf_alignment_score,
    tr.graph_confidence,
    tr.rr_ratio,
    t.pnl,
    tr.reasoning_text
ORDER BY t.pnl DESC
LIMIT 20
```

### 13. Trade Reasoning — What Loses?
```cypher
MATCH (tr:TradeReasoning)-[:REASONING_FOR]->(t:Trade)
WHERE t.pnl < 0
RETURN
    tr.symbol,
    tr.direction,
    tr.setup_type,
    tr.entry_zone,
    tr.htf_trend,
    tr.mtf_alignment_score,
    tr.graph_confidence,
    tr.rr_ratio,
    t.pnl,
    tr.reasoning_text
ORDER BY t.pnl ASC
LIMIT 20
```

### 14. Winning Patterns — What Setup Types Work?
```cypher
MATCH (tr:TradeReasoning)-[:REASONING_FOR]->(t:Trade)
WHERE t.pnl IS NOT NULL
RETURN
    tr.setup_type,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / count(t)) AS wr_pct,
    round(sum(t.pnl) * 100) / 100 AS pnl,
    round(avg(tr.rr_ratio) * 100) / 100 AS avg_rr
ORDER BY pnl DESC
```

### 15. What MTF Alignment Scores Win?
```cypher
MATCH (tr:TradeReasoning)-[:REASONING_FOR]->(t:Trade)
WHERE t.pnl IS NOT NULL AND tr.mtf_alignment_score IS NOT NULL
RETURN
    tr.mtf_alignment_score AS alignment_score,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY alignment_score
```

---

## Causal Chain Intelligence

### 16. Recent Causal Chains
```cypher
MATCH (cc:CausalChain)
OPTIONAL MATCH (cc)-[p:PREDICTS_IMPACT]->(s:Symbol)
RETURN
    cc.chain_text,
    cc.risk_level,
    cc.overall_sentiment,
    collect({symbol: s.id, direction: p.direction, confidence: p.confidence}) AS impacts,
    cc.created_at
ORDER BY cc.created_at DESC
LIMIT 10
```

### 17. Causal Chains for a Symbol
```cypher
MATCH (cc:CausalChain)-[p:PREDICTS_IMPACT]->(s:Symbol {id: 'XAUUSD'})
RETURN
    cc.chain_text,
    p.direction,
    p.confidence,
    cc.risk_level,
    cc.created_at
ORDER BY cc.created_at DESC
LIMIT 10
```

### 18. Did Causal Predictions Come True?
```cypher
MATCH (cc:CausalChain)-[p:PREDICTS_IMPACT]->(s:Symbol)
MATCH (t:Trade)-[:TRADED_SYMBOL]->(s)
WHERE t.entry_time > cc.created_at
    AND t.entry_time < cc.created_at + duration({hours: 24})
    AND t.pnl IS NOT NULL
WITH cc, p, t,
    CASE
        WHEN p.direction = 'BULLISH' AND t.direction = 'BUY' AND t.pnl > 0 THEN 'CORRECT'
        WHEN p.direction = 'BEARISH' AND t.direction = 'SELL' AND t.pnl > 0 THEN 'CORRECT'
        WHEN t.pnl > 0 THEN 'TRADE_WON_DIFFERENT_DIRECTION'
        ELSE 'INCORRECT'
    END AS prediction_result
RETURN
    cc.chain_text,
    p.direction AS predicted,
    t.direction AS traded,
    t.pnl,
    prediction_result
ORDER BY cc.created_at DESC
LIMIT 20
```

---

## Regime & Context

### 19. Performance by Regime
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.regime_at_entry IS NOT NULL
RETURN
    t.regime_at_entry AS regime,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY pnl DESC
```

### 20. Performance by SL/TP Source (Structure vs ATR)
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.sl_source IS NOT NULL
RETURN
    t.sl_source AS sl_type,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / count(t)) AS wr_pct,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY pnl DESC
```

### 21. News Risk Level vs Performance
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.news_risk_at_entry IS NOT NULL
RETURN
    t.news_risk_at_entry AS news_risk,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY news_risk
```

### 22. Graph Advisor Confidence vs Outcome
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NOT NULL AND t.graph_confidence IS NOT NULL
WITH t,
    CASE
        WHEN t.graph_confidence >= 0.7 THEN 'HIGH (0.7+)'
        WHEN t.graph_confidence >= 0.5 THEN 'MEDIUM (0.5-0.7)'
        WHEN t.graph_confidence >= 0.3 THEN 'LOW (0.3-0.5)'
        ELSE 'VERY LOW (<0.3)'
    END AS confidence_band
RETURN
    confidence_band,
    count(t) AS trades,
    sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
    round(sum(t.pnl) * 100) / 100 AS pnl
ORDER BY confidence_band
```

---

## ICT Scanner Analysis

### 23. ICT Success Rate by Symbol
```cypher
MATCH (i:ICTPartial)-[:ON_SYMBOL]->(s:Symbol)
RETURN
    s.id AS symbol,
    count(i) AS attempts,
    sum(CASE WHEN i.steps_completed >= 5 THEN 1 ELSE 0 END) AS full_chains,
    sum(CASE WHEN i.failed_at_step = 1 THEN 1 ELSE 0 END) AS fail_step1,
    sum(CASE WHEN i.failed_at_step = 2 THEN 1 ELSE 0 END) AS fail_step2,
    sum(CASE WHEN i.failed_at_step = 3 THEN 1 ELSE 0 END) AS fail_step3
ORDER BY full_chains DESC
```

### 24. Rejected Signals — Why Trades Were Blocked
```cypher
MATCH (r:RejectedSignal)-[:ON_SYMBOL]->(s:Symbol)
RETURN
    r.rejection_layer AS blocked_by,
    count(r) AS count,
    collect(DISTINCT s.id) AS symbols
ORDER BY count DESC
LIMIT 15
```

---

## Diagnostic Queries

### 25. Find Orphan Trades (in Neo4j but not matching DB)
```cypher
MATCH (t:Trade)
WHERE t.pnl IS NULL AND t.close_time IS NULL
RETURN t.symbol, t.direction, t.entry_time, t.trading_era
ORDER BY t.entry_time DESC
LIMIT 20
```

### 26. Sync Check — Count by Era
```cypher
MATCH (t:Trade)
RETURN
    COALESCE(t.trading_era, 'UNTAGGED') AS era,
    count(t) AS count
ORDER BY era
```

### 27. Recent Trades (Live Monitor)
```cypher
MATCH (t:Trade)
WHERE t.close_time IS NOT NULL
RETURN
    t.symbol,
    t.direction,
    round(t.pnl * 100) / 100 AS pnl,
    t.strategy,
    t.trading_era,
    t.close_time
ORDER BY t.close_time DESC
LIMIT 20
```

### 28. Full Brain Visualization (for Neo4j Browser)
```cypher
MATCH (t:Trade)-[r1:TRADED_SYMBOL]->(s:Symbol)
MATCH (t)-[r2:EXECUTED_BY]->(st:Strategy)
OPTIONAL MATCH (tr:TradeReasoning)-[r3:REASONING_FOR]->(t)
OPTIONAL MATCH (cc:CausalChain)-[r4:PREDICTS_IMPACT]->(s)
OPTIONAL MATCH (e1:TradingEra)-[r5:SUCCEEDED_BY]->(e2:TradingEra)
WHERE t.trading_era = 'BRAIN_V1'
RETURN t, s, st, tr, cc, e1, e2, r1, r2, r3, r4, r5
LIMIT 100
```

---

## Quick Reference

**Open Neo4j Browser:** http://localhost:7474
**Bolt:** bolt://localhost:7687
**Credentials:** neo4j / trading_brain_2026

**Run from terminal:**
```bash
docker exec neo4j cypher-shell -u neo4j -p trading_brain_2026 "YOUR QUERY HERE"
```

**Run from Python:**
```python
from app.quant.knowledge.connection import get_graph
graph = get_graph()
# Use graph.driver.session() for custom queries
```

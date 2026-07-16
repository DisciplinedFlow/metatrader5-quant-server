# Neo4j Backtest Reference — Forex Brain Queries

71 reference trade nodes seeded from 6 months of real MT5 H4 OHLCV data.
24 geopolitical era context nodes (Iran/Israel/US, Russia/Ukraine, Fed macro).
All reference nodes: `source: 'BACKTEST_SEED'`, `weight: 0.3`.

```bash
docker exec -it neo4j cypher-shell -u neo4j -p trading_brain_2026
```

---

## 1. Symbol Performance Breakdown

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
RETURN
  t.symbol AS symbol,
  count(t) AS total,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS wr_pct,
  round(avg(t.pnl_r), 3) AS avg_pnl_r,
  round(sum(t.pnl_r), 3) AS total_r,
  round(avg(t.mfe), 3) AS avg_mfe,
  round(avg(t.mae), 3) AS avg_mae
ORDER BY wr_pct DESC
```

**Seeding results (6 months H4, min confluence 0.55):**

| Symbol | WR@1:2 | E(R) |
|--------|--------|------|
| XAGUSD | 94.7% | 1.842 |
| XAUUSD | 90.9% | 1.727 |
| NG-C | 83.3% | 1.500 |
| UKOUSDft | 60.0% | 0.800 |
| GBPUSD | 44.4% | 0.333 |
| USOUSD | 40.0% | 0.200 |
| USDJPY | 30.0% | -0.100 |
| EURUSD | 0.0% | -1.000 |

---

## 2. Does Gold Perform Better During Geopolitical Escalations?

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED', symbol: 'XAUUSD'})-[:NEAR_EVENT]->(g:GeopoliticalEvent)
RETURN
  g.event_text AS event,
  g.sentiment AS geo_sentiment,
  t.direction AS direction,
  t.outcome AS outcome,
  t.pnl_r AS pnl_r,
  t.session AS session
ORDER BY g.intensity DESC
```

---

## 3. Escalation Era vs Neutral — Win Rate Comparison (Metals)

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
WHERE t.symbol IN ['XAUUSD', 'XAGUSD']
RETURN
  t.era_sentiment AS era,
  count(t) AS total,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS wr_pct,
  round(avg(t.pnl_r), 3) AS avg_pnl_r
ORDER BY wr_pct DESC
```

---

## 4. Session Performance — Which Session Has the Best WR?

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
RETURN
  t.session AS session,
  t.symbol AS symbol,
  count(t) AS total,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS wr_pct
ORDER BY symbol, wr_pct DESC
```

---

## 5. HTF Bias Alignment — With Trend vs Counter-Trend

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
WITH t,
  CASE WHEN t.htf_bias = t.direction THEN 'with_trend' ELSE 'counter_trend' END AS alignment
RETURN
  alignment,
  count(t) AS total,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS wr_pct,
  round(avg(t.pnl_r), 3) AS avg_pnl_r
ORDER BY wr_pct DESC
```

---

## 6. OB + FVG + CVD Divergence — Signal Combination WR

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
RETURN
  t.ob_present AS ob_present,
  t.fvg_present AS fvg_present,
  t.cvd_divergence AS cvd_div,
  count(t) AS total,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS wr_pct
ORDER BY wr_pct DESC
```

---

## 7. Confluence Score Threshold — Where Does WR Inflect?

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
WITH t,
  CASE
    WHEN t.confluence_score >= 0.8  THEN 'high (0.8+)'
    WHEN t.confluence_score >= 0.65 THEN 'medium (0.65-0.8)'
    ELSE 'base (0.55-0.65)'
  END AS conf_band
RETURN
  conf_band,
  count(t) AS total,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS wr_pct,
  round(avg(t.pnl_r), 3) AS avg_pnl_r
ORDER BY wr_pct DESC
```

---

## 8. Geopolitical Events with Nearby Reference Trades

```cypher
MATCH (g:GeopoliticalEvent)
OPTIONAL MATCH (t:Trade)-[:NEAR_EVENT]->(g)
RETURN
  g.event_date AS date,
  g.event_type AS type,
  g.event_text AS event,
  g.intensity AS intensity,
  count(t) AS nearby_trades,
  round(avg(t.pnl_r), 3) AS avg_pnl_near_event
ORDER BY g.event_date DESC
```

---

## 9. Full Reference Trade List — Ranked by R

```cypher
MATCH (t:Trade {source: 'BACKTEST_SEED'})
RETURN
  t.symbol AS sym,
  t.direction AS dir,
  t.session AS sess,
  t.htf_bias AS bias,
  t.outcome AS outcome,
  t.pnl_r AS r,
  t.bars_held AS bars,
  t.mfe AS mfe,
  t.mae AS mae,
  t.confluence_score AS conf,
  t.era_sentiment AS era,
  t.trigger_time AS time
ORDER BY t.pnl_r DESC
```

---

## 10. Live Advisor Query — Pre-Trade Historical Lookup

Called by `advisor.py` before every live entry. If `sample_size >= 3` and
`reference_wr >= 60`, boost sizing confidence. Blends with live trade nodes
(weight=1.0) as they accumulate — reference nodes (weight=0.3) fade out.

```cypher
MATCH (t:Trade)
WHERE t.symbol = $symbol
  AND t.direction = $direction
  AND t.htf_bias = $htf_bias
  AND t.era_sentiment = $era_sentiment
RETURN
  count(t) AS sample_size,
  sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) AS wins,
  round(100.0 * sum(CASE WHEN t.is_winner THEN 1 ELSE 0 END) / count(t), 1) AS reference_wr,
  round(avg(t.pnl_r), 3) AS reference_avg_r,
  round(avg(t.mfe), 3) AS avg_mfe,
  round(avg(t.mae), 3) AS avg_mae
```

---

## Re-seed After New Data

```bash
# All symbols
docker exec -it django python manage.py seed_brain --verbosity 2

# Single symbol
docker exec -it django python manage.py seed_brain --symbol XAUUSD --verbosity 2

# Geo events only
docker exec -it django python manage.py seed_brain --geo-only

# Clear reference trades before re-seeding
docker exec -it neo4j cypher-shell -u neo4j -p trading_brain_2026 \
  "MATCH (t:Trade {source: 'BACKTEST_SEED'}) DETACH DELETE t;"
```

# Crypto Brain — Neo4j Query Reference

> Neo4j Browser: http://localhost:7474
> Credentials: neo4j / trading_brain_2026

---

## Performance Overview

```cypher
MATCH (t:Trade) WHERE t.venue = 'LIGHTER' OR t.symbol IN ['BTC', 'ETH', 'SOL', 'XAU', 'DOGE', 'AVAX', 'LINK', 'SUI', 'EURUSD']
WITH t, CASE WHEN t.pnl > 0 THEN 'WIN' ELSE 'LOSS' END AS outcome
RETURN t.symbol AS symbol, t.direction AS direction,
       count(t) AS trades,
       sum(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS wins,
       round(100.0 * sum(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) / count(t), 1) AS win_rate,
       round(sum(t.pnl), 2) AS total_pnl,
       round(avg(t.pnl), 3) AS avg_pnl
ORDER BY trades DESC
```

## Win Rate by Hour

```cypher
MATCH (t:Trade) WHERE t.venue = 'LIGHTER'
WITH t, t.hour_utc AS hour, CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END AS win
RETURN hour,
       count(t) AS trades,
       sum(win) AS wins,
       round(100.0 * sum(win) / count(t), 1) AS win_rate,
       round(sum(t.pnl), 2) AS pnl
ORDER BY hour
```

## Strategy Performance

```cypher
MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy)
WHERE t.venue = 'LIGHTER'
RETURN s.name AS strategy,
       count(t) AS trades,
       round(100.0 * sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / count(t), 1) AS win_rate,
       round(sum(t.pnl), 2) AS total_pnl,
       round(avg(t.pnl), 3) AS avg_pnl
ORDER BY total_pnl DESC
```

## Symbol × Direction Heatmap

```cypher
MATCH (t:Trade)-[:TRADED_SYMBOL]->(sym:Symbol)
WHERE t.venue = 'LIGHTER'
RETURN sym.id AS symbol, t.direction AS dir,
       count(t) AS n,
       round(100.0 * sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / count(t), 1) AS wr,
       round(sum(t.pnl), 2) AS pnl
ORDER BY pnl DESC
```

## Trade Reasoning Memory

```cypher
MATCH (tr:TradeReasoning)-[:REASONING_FOR]->(t:Trade)
WHERE t.venue = 'LIGHTER'
RETURN t.symbol AS symbol, t.direction AS dir, t.pnl AS pnl,
       tr.setup_type AS setup, tr.entry_zone AS zone,
       tr.graph_recommendation AS graph_rec,
       tr.news_risk AS news,
       tr.reasoning_text AS reasoning
ORDER BY t.close_time DESC
LIMIT 20
```

## Losing Patterns

```cypher
MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy)
WHERE t.venue = 'LIGHTER' AND t.pnl < 0
WITH s.name AS strategy, t.symbol AS symbol, t.direction AS dir,
     t.hour_utc AS hour, t.day_of_week AS dow
RETURN strategy, symbol, dir,
       count(*) AS losses,
       round(sum(t.pnl), 2) AS total_loss,
       collect(DISTINCT hour) AS losing_hours
ORDER BY total_loss ASC
LIMIT 10
```

## Cross-Asset Intelligence (forex → crypto)

```cypher
MATCH (t:Trade)-[:TRADED_SYMBOL]->(sym:Symbol)
WHERE sym.market_type = 'CRYPTO'
WITH t.day_of_week AS dow, t.hour_utc AS hour,
     avg(t.pnl) AS crypto_avg_pnl, count(t) AS crypto_trades
MATCH (f:Trade)-[:TRADED_SYMBOL]->(fsym:Symbol)
WHERE fsym.market_type IN ['FOREX', 'METALS'] AND f.day_of_week = dow
WITH dow, hour, crypto_avg_pnl, crypto_trades,
     avg(f.pnl) AS forex_avg_pnl
RETURN dow, hour, round(crypto_avg_pnl, 3) AS crypto_pnl,
       round(forex_avg_pnl, 3) AS forex_pnl, crypto_trades
ORDER BY dow, hour
```

## Full Brain Graph (visual)

```cypher
MATCH (sym:Symbol)<-[r]-(n)
WHERE sym.id IN ['BTC', 'ETH', 'SOL', 'XAU', 'EURUSD']
RETURN sym, r, n
LIMIT 200
```

## Recent Rejected Signals

```cypher
MATCH (rs:RejectedSignal)-[:ON_SYMBOL]->(sym:Symbol)
WHERE sym.id IN ['BTC', 'ETH', 'SOL', 'XAU']
RETURN sym.id AS symbol, rs.direction AS dir,
       rs.rejection_reason AS reason,
       rs.rejection_layer AS layer,
       rs.confluence_score AS confluence,
       rs.timestamp AS time
ORDER BY rs.timestamp DESC
LIMIT 20
```

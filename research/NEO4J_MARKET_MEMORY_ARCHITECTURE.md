# Neo4j Market Memory Architecture

Here is the complete architecture document, ready to be saved to `/Users/rosaria/Desktop/metatrader5-quant-server-python/research/NEO4J_MARKET_MEMORY_ARCHITECTURE.md`:

---

```markdown
# Neo4j Market Memory Architecture
# Neo4j Market Memory — Design & Implementation Blueprint

**Document:** `research/NEO4J_MARKET_MEMORY_ARCHITECTURE.md`  
**Date:** 2026-03-17  
**Status:** Design Complete — Ready for Implementation  
**System:** MT5 Quant Server, Neo4j 5-community, bolt://neo4j:7687

---

## 1. Executive Context

### What Exists Today

The knowledge graph at `backend/django/app/quant/knowledge/` is already recording live trades with rich context: HMM regime, ATR, confluence score, session, direction, strategy name, PnL. The `graph.py` `_create_schema()` method creates a `NewsEvent` constraint and timestamp index, and `record_news()` already batch-writes headline stubs. The `enricher.py` pre-computes five graph-derived features into Redis every five minutes. The `run_graph_enrichment` Celery task and `record_to_graph` fire-and-forget task are wired and running.

What is **missing** is the connective tissue: `NewsEvent` nodes are written as disconnected islands (no symbol links, no price reaction measurement, no `AFFECTED` relationships). There is no `BacktestTrade` node type. There are no Cypher queries that answer "what happened last time Iran was in the news." The graph is a recording system without a memory.

This document specifies exactly how to grow it into a market memory.

### What This Architecture Adds

| Capability | Method |
|---|---|
| News events linked to symbols and market conditions | `AFFECTS` relationship on `NewsEvent` |
| Price reaction measured per news event | `PriceReaction` relationship + `TRIGGERED` rel |
| Historical backtest trades ingested as separate nodes | `BacktestTrade` node type |
| Pattern recognition Cypher queries | Four named query templates |
| Strategy router confidence modifier at entry time | `graph_news_reaction_wr` sixth enricher feature |

---

## 2. Existing Graph Schema (Baseline)

These nodes and relationships already exist and must not be redesigned — only extended.

### Existing Nodes

| Label | Unique Constraint | Key Properties |
|---|---|---|
| `Symbol` | `id` | `market_type` |
| `Trade` | `id` | `symbol`, `direction`, `pnl`, `regime_at_entry`, `confluence_score`, `session`, `strategy` |
| `Strategy` | `name` | — |
| `NewsEvent` | `id` (headline hash) | `headline`, `source`, `timestamp`, `category`, `url` |
| `Regime` | `id` | `symbol`, `label`, `direction`, `confidence`, `adx`, `bb_width` |
| `MarketCondition` | — (no unique) | `symbol`, `regime`, `adx`, `bb_width`, `atr_ratio`, `session` |
| `RegimeTransition` | `id` | `symbol`, `from_regime`, `to_regime` |
| `RejectedSignal` | `id` | `symbol`, `direction`, `rejection_layer`, `confluence_score` |
| `ExitEvent` | `id` | `trade_id`, `phase`, `action` |
| `ICTPartial` | `id` | `symbol`, `steps_completed`, `failed_at_step` |
| `HTFBias` | `id` | `symbol`, `bias`, `ema_direction` |
| `ConfluenceBreakdown` | `id` | `symbol`, `total_score`, per-factor scores |
| `PerformanceSnapshot` | `id` (date) | `win_rate`, `total_pnl`, `sharpe` |

### Existing Relationships

| Relationship | From → To | Notes |
|---|---|---|
| `TRADED_SYMBOL` | `Trade` → `Symbol` | Created by `_create_trade_tx` |
| `EXECUTED_BY` | `Trade` → `Strategy` | Created by `_create_trade_tx` |
| `FOR_SYMBOL` | `Regime` → `Symbol` | Via `_create_condition_tx` |
| `TRANSITION_ON` | `RegimeTransition` → `Symbol` | Via `_create_transition_tx` |
| `EXIT_FOR` | `ExitEvent` → `Trade` | Via `_create_exit_event_tx` |
| `ON_SYMBOL` | `RejectedSignal` → `Symbol` | — |
| `ON_SYMBOL` | `ICTPartial` → `Symbol` | — |
| `FOR_SYMBOL` | `HTFBias` → `Symbol` | — |

---

## 3. New Schema — Market Memory Extension

### 3.1 New Node Types

#### `NewsEvent` Extended Properties
The existing `NewsEvent` node is extended in place. No new node type is needed — properties are added on write.

```cypher
// Extended NewsEvent (additional properties on existing node)
MERGE (n:NewsEvent {id: $news_id})
ON CREATE SET
  n.headline      = $headline,
  n.source        = $source,
  n.timestamp     = datetime($timestamp),
  n.category      = $category,
  n.url           = $url,
  // NEW PROPERTIES
  n.keywords      = $keywords,          // List<String> e.g. ['iran', 'oil', 'sanctions']
  n.risk_level    = $risk_level,        // 'NORMAL' | 'ELEVATED' | 'EXTREME'
  n.sentiment_score = $sentiment_score, // Float: -1.0 (extreme fear) to +1.0 (extreme greed)
  n.high_impact_count = $high_count,    // Integer
  n.medium_impact_count = $medium_count,
  n.event_type    = $event_type,        // 'GEOPOLITICAL' | 'MONETARY_POLICY' | 'ECONOMIC_DATA' | 'GENERAL'
  n.ingestion_source = $ingestion_source // 'LIVE_RSS' | 'HISTORICAL_BACKFILL'
```

#### `PriceReaction` (New Node)
A measurement node capturing how a specific symbol's price moved after a specific news event. Made a node (not just a relationship property) so it can be queried independently.

```cypher
CREATE (pr:PriceReaction {
  id:             $pr_id,           // UUID
  symbol:         $symbol,
  news_event_id:  $news_event_id,
  measured_at:    datetime(),
  price_at_event: $price_at_event,  // Close price at news timestamp
  // Multi-horizon reactions
  change_1h_pct:  $change_1h_pct,   // % change 1 bar after (H1 close vs event close)
  change_4h_pct:  $change_4h_pct,   // % change 4 bars after
  change_24h_pct: $change_24h_pct,  // % change 24 bars after
  // Classification
  reaction_type:  $reaction_type,   // 'SPIKE_UP' | 'SPIKE_DOWN' | 'FADE_UP' | 'FADE_DOWN' | 'NO_REACTION'
  max_move_pct:   $max_move_pct,    // Largest absolute move in 24h window
  volatility_spike: $vol_spike,     // Boolean: ATR at event vs rolling 20-period ATR > 1.5x
  session:        $session          // Session when event occurred
})
```

Reaction classification thresholds:
- `SPIKE_UP`: `change_1h_pct > +0.3%`
- `SPIKE_DOWN`: `change_1h_pct < -0.3%`
- `FADE_UP`: `change_1h_pct < -0.2%` AND `change_4h_pct > +0.2%` (initial drop then recovery)
- `FADE_DOWN`: `change_1h_pct > +0.2%` AND `change_4h_pct < -0.2%`
- `NO_REACTION`: absolute `change_1h_pct < 0.1%`

These thresholds should be instrument-specific. XAUUSD 0.3% = ~$6 move. EURUSD 0.3% = 30 pips. A single constant `MIN_REACTION_PCT` per `market_type` is appropriate:

| Market Type | SPIKE threshold |
|---|---|
| METAL (XAUUSD, XAGUSD) | 0.25% |
| ENERGY (USOUSD) | 0.40% |
| FOREX (majors) | 0.15% |
| FOREX (minors) | 0.20% |

#### `BacktestTrade` (New Node)
Distinct from `Trade` (live). Enables side-by-side performance comparison.

```cypher
CREATE (bt:BacktestTrade {
  id:               $bt_id,           // UUID
  source:           $source,          // 'MT5_H1' | 'YFINANCE_1D' | 'CUSTOM_BACKTEST'
  strategy:         $strategy,        // Strategy name
  symbol:           $symbol,
  direction:        $direction,       // 'BUY' | 'SELL'
  entry_time:       datetime($entry_time),
  close_time:       datetime($close_time),
  entry_price:      $entry_price,
  close_price:      $close_price,
  pnl_pct:          $pnl_pct,         // % return (normalized — not USD)
  result:           $result,          // 'WIN' | 'LOSS'
  sl_atr_mult:      $sl_atr_mult,     // SL multiplier used in backtest
  tp_atr_mult:      $tp_atr_mult,     // TP multiplier
  rr_ratio:         $rr_ratio,        // R:R achieved
  regime_label:     $regime_label,    // HMM regime at simulated entry
  volatility_regime: $vol_regime,     // 'LOW' | 'NORMAL' | 'HIGH' (ATR ratio)
  confluence_score: $confluence_score,
  session:          $session,
  hour_utc:         $hour_utc,
  data_period_days: $data_period_days,
  backtest_run_id:  $run_id           // Groups trades from same backtest run
})
```

#### `BacktestRun` (New Node)
A container for grouping related backtest trades.

```cypher
CREATE (br:BacktestRun {
  id:           $run_id,            // UUID
  strategy:     $strategy,
  source:       $source,
  symbol:       $symbol,
  period_start: datetime($start),
  period_end:   datetime($end),
  total_trades: $total_trades,
  win_rate:     $win_rate,
  profit_factor: $profit_factor,
  total_pnl_pct: $total_pnl_pct,
  max_drawdown_pct: $max_dd_pct,
  ran_at:       datetime()
})
```

#### `EconomicEvent` (New Node)
Scheduled macro events (NFP, FOMC, CPI) as distinct from RSS news headlines. These have known times in advance and predictable instrument impact.

```cypher
MERGE (ee:EconomicEvent {id: $event_id})
ON CREATE SET
  ee.event_name    = $event_name,    // 'NFP' | 'FOMC' | 'CPI' | 'ECB_RATE' etc.
  ee.country       = $country,       // 'US' | 'EU' | 'UK' | 'JP'
  ee.scheduled_at  = datetime($scheduled_at),
  ee.actual_value  = $actual_value,  // null until released
  ee.forecast_value = $forecast_value,
  ee.previous_value = $prev_value,
  ee.surprise_pct  = $surprise_pct,  // (actual - forecast) / |forecast|, null until released
  ee.impact_tier   = $impact_tier    // 'HIGH' | 'MEDIUM' | 'LOW'
```

---

### 3.2 New Relationships

```cypher
// NewsEvent AFFECTS Symbol (when symbol mentioned in headline or keywords match)
CREATE (n:NewsEvent)-[:AFFECTS {
  confidence: $confidence,     // 0.0-1.0: how directly the news affects this symbol
  reason: $reason              // 'direct_mention' | 'keyword_match' | 'correlated'
}]->(s:Symbol)

// NewsEvent CONCURRENT_WITH MarketCondition (same timestamp window)
CREATE (n:NewsEvent)-[:CONCURRENT_WITH {
  time_delta_minutes: $delta   // How many minutes from news to condition snapshot
}]->(mc:MarketCondition)

// PriceReaction MEASURES (NewsEvent, Symbol) pair
CREATE (pr:PriceReaction)-[:MEASURES]->(n:NewsEvent)
CREATE (pr:PriceReaction)-[:FOR_SYMBOL]->(s:Symbol)

// BacktestTrade relationships
CREATE (bt:BacktestTrade)-[:BACKTESTED_SYMBOL]->(s:Symbol)
CREATE (bt:BacktestTrade)-[:BACKTESTED_BY]->(st:Strategy)
CREATE (bt:BacktestTrade)-[:IN_RUN]->(br:BacktestRun)

// BacktestRun comparison with live performance
CREATE (br:BacktestRun)-[:COMPARED_TO]->(ps:PerformanceSnapshot)

// EconomicEvent relationships
CREATE (ee:EconomicEvent)-[:IMPACTS_SYMBOL {
  historical_avg_move_pct: $avg_move,
  historical_reaction_type: $reaction_type
}]->(s:Symbol)
CREATE (pr:PriceReaction)-[:TRIGGERED_BY]->(ee:EconomicEvent)
CREATE (pr:PriceReaction)-[:TRIGGERED_BY]->(n:NewsEvent)

// Trade entered while news was active
CREATE (t:Trade)-[:ENTERED_DURING_NEWS {
  news_risk_level: $risk_level,
  news_keywords: $keywords
}]->(n:NewsEvent)
```

---

## 4. Data Ingestion Pipelines

### 4.1 Live News Enrichment Pipeline (Modifies Existing Flow)

**Current state:** `fetch_market_pulse` Celery task (every 2 minutes) fetches headlines and caches them in `market_pulse:news`. `check_news_sentiment` Celery task (every 5 minutes) calls `get_market_risk_level()` which fetches RSS feeds independently. The `record_to_graph` task writes bare `NewsEvent` stubs via `record_news()` — no symbol links, no properties beyond headline/source/url.

**Change required:** The existing `record_news()` method in `graph.py` must be extended to accept the enriched payload from `news_sentiment.py`. The `_create_news_batch_tx` transaction must:

1. Write the extended `NewsEvent` properties (keywords, risk_level, sentiment_score, event_type).
2. For each article, determine which `Symbol` nodes it affects based on keyword→symbol mapping.
3. Create `AFFECTS` relationships with confidence score.
4. Attempt to find the nearest `MarketCondition` node within a 10-minute window and create `CONCURRENT_WITH`.

**Symbol Affinity Mapping** (new constant in `graph.py` or a dedicated `news_router.py`):

```python
NEWS_SYMBOL_AFFINITY = {
    # XAUUSD / Gold
    'keywords': ['gold', 'xau', 'safe haven', 'risk off', 'iran', 'israel',
                 'nuclear', 'war', 'invasion', 'sanctions', 'ukraine', 'russia'],
    'symbols': ['XAUUSD', 'XAGUSD'],
    'confidence': 0.9,

    # Oil / Energy
    'keywords': ['oil', 'crude', 'opec', 'brent', 'wti', 'oil embargo',
                 'iran sanctions', 'strategic reserve'],
    'symbols': ['USOUSD', 'UKOUSDft'],
    'confidence': 0.9,

    # USD-sensitive (rate decisions, NFP, CPI, GDP)
    'keywords': ['fed rate', 'fomc', 'interest rate', 'nfp', 'non-farm',
                 'payroll', 'cpi', 'inflation', 'gdp', 'recession',
                 'debt ceiling', 'shutdown', 'dollar'],
    'symbols': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD',
                'USDCAD', 'USDCHF', 'XAUUSD'],
    'confidence': 0.7,

    # EUR-sensitive (ECB)
    'keywords': ['ecb', 'ecb rate', 'eurozone', 'eu economy', 'german'],
    'symbols': ['EURUSD', 'EURGBP'],
    'confidence': 0.8,

    # GBP-sensitive (BoE)
    'keywords': ['boe', 'boe rate', 'bank of england', 'uk economy',
                 'uk inflation', 'uk gdp'],
    'symbols': ['GBPUSD', 'EURGBP'],
    'confidence': 0.8,

    # JPY-sensitive (BoJ)
    'keywords': ['boj', 'bank of japan', 'japan', 'yen'],
    'symbols': ['USDJPY'],
    'confidence': 0.8,
}
```

This mapping lives as a module-level constant. The news enrichment logic iterates it, checks if any keyword appears in the headline+summary blob, and creates `AFFECTS` with the matching confidence. A single headline can affect multiple symbols.

**Integration point:** Inside `record_to_graph` Celery task in `tasks.py`, on `record_type == 'news'`, the existing `graph.record_news(payload.get('articles', []))` call is replaced with `graph.record_news_enriched(payload.get('articles', []))` which accepts the full enriched article dict including matched keywords and risk level.

The `check_news_sentiment` task already has matched_keywords and risk_level in its return dict. That payload needs to be forwarded to `record_to_graph.delay({'type': 'news', 'articles': enriched_articles})`.

---

### 4.2 Price Reaction Measurement Pipeline (New)

**Purpose:** After a `NewsEvent` is written, go back to the MT5 price history (via `fetch_data_pos`) and measure what each affected symbol actually did in the 1h, 4h, and 24h after the event.

**Trigger:** A new Celery task `measure_news_reactions` runs on the `analysis` queue every 30 minutes. It queries Neo4j for `NewsEvent` nodes that have `AFFECTS` relationships to `Symbol` nodes but no `PriceReaction` nodes yet, and that are old enough to have complete 24h price data.

**Algorithm per (NewsEvent, Symbol) pair:**

1. Get the `news_event.timestamp` and `symbol`.
2. Call `fetch_data_pos(symbol, MT5Timeframe.H1, count=30)` to get bars around the event.
3. Find the H1 bar whose open time is <= news timestamp.
4. Record `price_at_event` = that bar's close.
5. Find bar at `+1h`, `+4h`, `+24h` relative to the event bar.
6. Compute `change_1h_pct = (price_1h - price_at_event) / price_at_event * 100`.
7. Classify `reaction_type` using thresholds defined in section 3.1.
8. Create `PriceReaction` node.
9. Create `MEASURES` and `FOR_SYMBOL` relationships.

**Timing constraint:** The task only processes events that are at least 25 hours old (to ensure 24h data is available). This means live news reactions are measured with a one-day lag, which is acceptable for a memory system.

**Performance:** With 20 news articles per 2-minute cycle, ~14 symbols per event = 280 potential (event, symbol) pairs per cycle. At 30-minute measurement intervals, the backlog per run is at most 280 pairs. Each pair requires one `fetch_data_pos` call. This is acceptable. Rate limit: 10 pairs per second max, add 100ms sleep between calls.

---

### 4.3 Historical News Backfill Pipeline (New, One-Time)

**Purpose:** Build the memory from existing free news archives to give the graph historical patterns before live trading began.

**Sources:**

| Source | Coverage | Access Method |
|---|---|---|
| GDELT Project | 2010-present, global events | Free CSV downloads |
| NewsAPI.org | 30 days free on free tier | REST API |
| The Guardian API | Full archive, free | REST API with key |
| RSS feed historical cache | Local only if stored | Not available |

**Recommended approach:** Use The Guardian API free tier. Financial/business section only. Filter by keyword (gold, oil, Fed, ECB, NFP, war). Download in monthly batches going back 24 months. Write to a local JSONL file, then replay through the `record_news_enriched` path.

**One-time ingestion script** (not a Celery task — runs manually on the MacBook Pro, not the server):

Reads the JSONL backfill file, processes in batches of 50, calls `graph.record_news_enriched()` directly via Django shell. After all news is ingested, runs `measure_news_reactions` on all of them.

**Volume estimate:** 24 months × 30 days × ~5 relevant headlines/day = ~3,600 historical news nodes. At 14 symbols × 3,600 = ~50,000 `PriceReaction` measurements. At H1 resolution, this becomes the pattern database.

---

### 4.4 Backtest Result Ingestion Pipeline (New)

**Purpose:** Translate `BacktestResult` records from PostgreSQL into graph nodes so they can be correlated with news events and regimes.

**Source:** The `BacktestResult` model in `nexus/models.py` already stores `trades` as a JSON array, `win_rate`, `profit_factor`, `symbol_breakdown`. The `run_backtest` Celery task runs every 6 hours and creates these records.

**Trigger:** Add a post-save hook or extend `run_backtest` to call `record_to_graph.delay({'type': 'backtest_run', 'backtest_result_id': result.id})` after `BacktestResult.objects.create(...)` succeeds.

**Transform per `BacktestResult`:**

1. Create one `BacktestRun` node from the top-level stats.
2. Iterate `result.trades` (JSON array) — each element becomes one `BacktestTrade` node.
3. For each `BacktestTrade`, compute `regime_label` by checking what the HMM regime was for that symbol at that historical timestamp. Since we cannot replay HMM on historical data easily at ingestion time, set `regime_label = 'UNKNOWN'` initially and leave a flag `regime_computed = False`. A separate enrichment pass (same `run_graph_enrichment` task) can backfill these.
4. Link `BacktestTrade` → `Symbol` via `BACKTESTED_SYMBOL`.
5. Link `BacktestTrade` → `Strategy` via `BACKTESTED_BY`.
6. Link `BacktestTrade` → `BacktestRun` via `IN_RUN`.

**Live vs Backtest Comparison:** Once both `Trade` (live) and `BacktestTrade` (simulated) exist for the same `(strategy, symbol)` pair, the pattern recognition queries can compare them. The `BacktestRun-[:COMPARED_TO]->PerformanceSnapshot` relationship enables this.

---

### 4.5 Live Trade–News Linkage (New, Runs at Trade Close)

When `close.py` fires `record_to_graph.delay({'type': 'trade', ...})`, add a second fire-and-forget call that links the trade to any news events that were active during its entry:

```python
# In close.py, after record_to_graph.delay({'type': 'trade', ...})
record_to_graph.delay({
    'type': 'trade_news_link',
    'trade_id': closed_trade.id,
    'entry_time': closed_trade.entry_time.isoformat(),
    'symbol': closed_trade.symbol,
    'news_risk_level': cache.get('news:market_risk_level', {}).get('risk_level', 'NORMAL'),
})
```

The `record_to_graph` handler creates a `ENTERED_DURING_NEWS` relationship from the `Trade` node to any `NewsEvent` nodes whose `timestamp` falls within a 4-hour window before the trade entry.

---

## 5. Schema Constraints and Indexes

Complete Cypher to initialize the new schema components (added to `_create_schema()` in `graph.py`):

```cypher
-- New constraints
CREATE CONSTRAINT backtest_trade_id IF NOT EXISTS
  FOR (bt:BacktestTrade) REQUIRE bt.id IS UNIQUE;

CREATE CONSTRAINT backtest_run_id IF NOT EXISTS
  FOR (br:BacktestRun) REQUIRE br.id IS UNIQUE;

CREATE CONSTRAINT economic_event_id IF NOT EXISTS
  FOR (ee:EconomicEvent) REQUIRE ee.id IS UNIQUE;

CREATE CONSTRAINT price_reaction_id IF NOT EXISTS
  FOR (pr:PriceReaction) REQUIRE pr.id IS UNIQUE;

-- New indexes
CREATE INDEX news_risk_level IF NOT EXISTS
  FOR (n:NewsEvent) ON (n.risk_level);

CREATE INDEX news_event_type IF NOT EXISTS
  FOR (n:NewsEvent) ON (n.event_type);

CREATE INDEX price_reaction_symbol IF NOT EXISTS
  FOR (pr:PriceReaction) ON (pr.symbol);

CREATE INDEX price_reaction_type IF NOT EXISTS
  FOR (pr:PriceReaction) ON (pr.reaction_type);

CREATE INDEX backtest_trade_symbol IF NOT EXISTS
  FOR (bt:BacktestTrade) ON (bt.symbol);

CREATE INDEX backtest_trade_strategy IF NOT EXISTS
  FOR (bt:BacktestTrade) ON (bt.strategy);

CREATE INDEX backtest_trade_regime IF NOT EXISTS
  FOR (bt:BacktestTrade) ON (bt.regime_label);

CREATE INDEX economic_event_name IF NOT EXISTS
  FOR (ee:EconomicEvent) ON (ee.event_name);
```

---

## 6. Pattern Recognition Queries

These are the four queries specified in the feature request, plus two additional queries that directly feed the strategy router.

### Query 1: "What happened to gold last time Iran was in the news?"

```cypher
MATCH (n:NewsEvent)-[:AFFECTS]->(s:Symbol {id: 'XAUUSD'})
WHERE any(kw IN n.keywords WHERE kw IN ['iran', 'iran sanctions', 'iran nuclear'])
  AND n.ingestion_source IN ['LIVE_RSS', 'HISTORICAL_BACKFILL']
MATCH (pr:PriceReaction)-[:MEASURES]->(n)
  WHERE pr.symbol = 'XAUUSD'
RETURN
  n.headline                          AS headline,
  n.timestamp                         AS news_time,
  pr.reaction_type                    AS reaction,
  round(pr.change_1h_pct, 3)          AS change_1h_pct,
  round(pr.change_4h_pct, 3)          AS change_4h_pct,
  round(pr.change_24h_pct, 3)         AS change_24h_pct,
  pr.volatility_spike                 AS vol_spike,
  n.risk_level                        AS news_risk_level
ORDER BY n.timestamp DESC
LIMIT 10
```

**Aggregated version** (for dashboard summary):

```cypher
MATCH (n:NewsEvent)-[:AFFECTS]->(s:Symbol {id: 'XAUUSD'})
WHERE any(kw IN n.keywords WHERE kw IN ['iran', 'iran sanctions'])
MATCH (pr:PriceReaction)-[:MEASURES]->(n) WHERE pr.symbol = 'XAUUSD'
WITH pr
RETURN
  count(pr)                                          AS total_events,
  avg(pr.change_1h_pct)                              AS avg_1h_move,
  avg(pr.change_4h_pct)                              AS avg_4h_move,
  sum(CASE WHEN pr.reaction_type = 'SPIKE_UP' THEN 1 ELSE 0 END)   AS spike_up_count,
  sum(CASE WHEN pr.reaction_type = 'SPIKE_DOWN' THEN 1 ELSE 0 END) AS spike_down_count,
  sum(CASE WHEN pr.reaction_type = 'NO_REACTION' THEN 1 ELSE 0 END) AS no_reaction_count
```

---

### Query 2: "Which strategy performs best during high-volatility regimes?"

```cypher
// Combines live trades and backtest trades for the broadest sample
MATCH (t:Trade)-[:EXECUTED_BY]->(s:Strategy)
WHERE t.regime_at_entry IN ['VOLATILE', 'HIGH_VOLATILITY']
  AND t.entry_time > datetime() - duration({days: 180})
WITH s.name AS strategy,
     count(t) AS live_total,
     sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
       CASE WHEN count(t) > 0 THEN count(t) ELSE 1 END AS live_wr,
     avg(t.return_r) AS live_avg_r

OPTIONAL MATCH (bt:BacktestTrade)-[:BACKTESTED_BY]->(bs:Strategy {name: strategy})
WHERE bt.regime_label = 'VOLATILE'
WITH strategy, live_total, live_wr, live_avg_r,
     count(bt) AS bt_total,
     sum(CASE WHEN bt.result = 'WIN' THEN 1 ELSE 0 END) * 1.0 /
       CASE WHEN count(bt) > 0 THEN count(bt) ELSE 1 END AS bt_wr

RETURN strategy, live_total, round(live_wr, 4) AS live_win_rate,
       round(live_avg_r, 3) AS live_avg_r,
       bt_total, round(bt_wr, 4) AS backtest_win_rate
ORDER BY live_wr DESC
```

---

### Query 3: "What is the typical XAGUSD reaction to NFP releases?"

```cypher
// Uses EconomicEvent nodes (when Finnhub calendar is available) or
// NewsEvent keyword matching as fallback
MATCH (ee:EconomicEvent {event_name: 'NFP'})
MATCH (pr:PriceReaction)-[:TRIGGERED_BY]->(ee)
WHERE pr.symbol = 'XAGUSD'
RETURN
  ee.scheduled_at                AS nfp_date,
  ee.actual_value                AS actual,
  ee.forecast_value              AS forecast,
  ee.surprise_pct                AS surprise_pct,
  pr.reaction_type               AS reaction,
  round(pr.change_1h_pct, 3)    AS change_1h_pct,
  round(pr.change_4h_pct, 3)    AS change_4h_pct
ORDER BY ee.scheduled_at DESC
LIMIT 12

// Fallback when EconomicEvent nodes are sparse: keyword matching on NewsEvent
MATCH (n:NewsEvent)
WHERE any(kw IN n.keywords WHERE kw IN ['nfp', 'non-farm', 'payroll'])
MATCH (pr:PriceReaction)-[:MEASURES]->(n) WHERE pr.symbol = 'XAGUSD'
RETURN
  n.timestamp, n.headline, pr.reaction_type,
  pr.change_1h_pct, pr.change_4h_pct
ORDER BY n.timestamp DESC
LIMIT 12
```

---

### Query 4: "Show all winning trades during EXTREME news conditions"

```cypher
MATCH (t:Trade)-[:ENTERED_DURING_NEWS]->(n:NewsEvent)
WHERE n.risk_level = 'EXTREME'
  AND t.pnl > 0
RETURN
  t.symbol, t.direction, t.strategy,
  round(t.pnl, 2)             AS pnl_usd,
  round(t.return_r, 3)        AS return_r,
  t.confluence_score,
  t.regime_at_entry,
  t.session,
  n.headline                  AS news_at_entry,
  collect(n.keywords)         AS keywords_present
ORDER BY t.pnl DESC
LIMIT 50

// Aggregated: win rate and average R by symbol under EXTREME news
MATCH (t:Trade)-[:ENTERED_DURING_NEWS]->(n:NewsEvent {risk_level: 'EXTREME'})
RETURN
  t.symbol,
  count(t)                                                AS total,
  sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
    CASE WHEN count(t) > 0 THEN count(t) ELSE 1 END      AS win_rate,
  avg(t.return_r)                                         AS avg_r
ORDER BY win_rate DESC
```

---

### Query 5: Strategy Router Confidence Query (Used at Trade Entry)

This is the runtime query called before placing an order. It must return in under 50ms. It reads from pre-computed Redis cache (see section 7).

**Underlying graph query** (run by `run_graph_enrichment`, cached to Redis):

```cypher
// For a given (symbol, direction, news_risk_level) combination,
// what is the historical win rate?
MATCH (t:Trade)-[:ENTERED_DURING_NEWS]->(n:NewsEvent)
WHERE t.symbol = $symbol
  AND t.direction = $direction
  AND n.risk_level = $news_risk_level
  AND t.entry_time > datetime() - duration({days: $lookback_days})
RETURN
  count(t)                                                  AS sample_size,
  sum(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) * 1.0 /
    CASE WHEN count(t) > 0 THEN count(t) ELSE 1 END        AS win_rate,
  avg(t.return_r)                                           AS avg_r

// Minimum sample_size = 5 to be actionable
// Return None/neutral if sample_size < 5
```

---

### Query 6: Pattern Similarity (Pre-Entry Context Lookup)

"Before entering XAUUSD SELL, show me similar setups in the last 90 days and their outcomes."

```cypher
MATCH (t:Trade {symbol: $symbol, direction: $direction})
WHERE t.entry_time > datetime() - duration({days: $lookback_days})
  AND t.regime_at_entry = $current_regime
  AND abs(t.confluence_score - $current_confluence) <= 2
  AND t.session = $current_session
OPTIONAL MATCH (t)-[:ENTERED_DURING_NEWS]->(n:NewsEvent)
RETURN
  t.entry_time, t.pnl, t.return_r, t.closing_reason,
  t.confluence_score, t.regime_at_entry,
  n.risk_level AS news_risk_at_entry
ORDER BY t.entry_time DESC
LIMIT 20
```

---

## 7. Strategy Router Integration

### Current Integration

`enricher.py` computes five features every 5 minutes via `run_graph_enrichment`, caches them in Redis under `graph_features:{symbol}:{direction}`, and `enrich_features()` reads them at entry time (sub-millisecond, just a Redis GET). These five features feed into the XGBoost ML meta-filter as feature indices 41-45 (pending Phase 2 activation).

### Adding the Sixth Feature: News Reaction Win Rate

A sixth feature `graph_news_reaction_wr` is added to `DEFAULTS` in `enricher.py`:

```python
DEFAULTS = {
    'graph_similar_wr': 0.5,
    'graph_strategy_regime_wr': 0.5,
    'graph_news_sentiment': 0.0,
    'graph_time_wr': 0.5,
    'graph_symbol_regime_wr': 0.5,
    'graph_news_reaction_wr': 0.5,    # NEW: historical WR under current news risk level
}
```

In `compute_and_cache_features()`, add:

```python
# 6. News reaction win rate under current news risk level
from app.quant.indicators.news_sentiment import get_market_risk_level
news_state = get_market_risk_level()
current_risk = news_state.get('risk_level', 'NORMAL')

news_reaction = graph.get_news_reaction_wr(symbol, direction, current_risk, lookback_days=90)
if news_reaction and news_reaction.get('sample_size', 0) >= 5:
    features['graph_news_reaction_wr'] = round(news_reaction['win_rate'], 4)
```

The new `get_news_reaction_wr()` method in `graph.py` runs Query 5 above.

### Confidence Modifier Design

The `graph_news_reaction_wr` feature does not directly modify position sizing at the router level — it enters the XGBoost model as a feature and influences the ML score, which already gates entries. This is the cleanest integration: no separate sizing layer to maintain.

However, a standalone fast-path rule is also warranted for cases before the XGBoost model has enough data:

In `cvd/entry.py`, in the Market Context Gate layer (Layer 4), after the existing news risk level check, add:

```python
# Graph-derived news reaction check (requires GRAPH_FEATURES_ACTIVE=True)
if settings.GRAPH_FEATURES_ACTIVE:
    from app.quant.knowledge.enricher import enrich_features
    graph_feats = enrich_features(symbol, order_type, regime, hour_utc, session, strategy_name, confluence_score)
    news_wr = graph_feats.get('graph_news_reaction_wr', 0.5)
    if news_wr < 0.30 and news_state['risk_level'] == 'EXTREME':
        # Historical data says: this symbol, this direction, EXTREME news = <30% WR
        # Apply 50% size penalty rather than blocking entirely
        sizing_modifier *= 0.5
        logger.info(f"NEWS MEMORY: {symbol} {order_type} EXTREME news WR={news_wr:.1%} — size penalty applied")
```

The threshold 0.30 (below random chance 0.5) makes this a meaningful gate, not noise. The response is a size reduction rather than a block, because news reactions are noisy and a flat block would reduce sample collection.

This integration is gated behind `GRAPH_FEATURES_ACTIVE` env var (already false in .env), so it activates only when Phase 2 is switched on.

---

## 8. Implementation Phases

### Phase 1: News Enrichment (Complexity: Low — 3-4 hours)

**Goal:** Make existing `NewsEvent` nodes useful — add properties, create `AFFECTS` relationships.

**Files to modify:**

- `backend/django/app/quant/knowledge/graph.py` — Extend `_create_news_batch_tx` to write enriched properties. Add `NEWS_SYMBOL_AFFINITY` constant. Add `_create_affects_relationships()` helper.
- `backend/django/app/quant/knowledge/graph.py` — Add `_create_schema()` entries for new indexes (`news_risk_level`, `news_event_type`).
- `backend/django/app/quant/tasks.py` — In `record_to_graph` handler for `record_type == 'news'`, extract `matched_keywords`, `risk_level`, `high_impact_count` from the article dict and pass to new `record_news_enriched()` method.
- `backend/django/app/quant/tasks.py` — In `check_news_sentiment` task, after `get_market_risk_level()`, fire `record_to_graph.delay({'type': 'news', 'articles': enriched_articles})` with full context.

**New method signature:**

```python
def record_news_enriched(self, articles: List[Dict[str, Any]], 
                          global_risk_level: str = 'NORMAL',
                          matched_keywords: List[str] = None) -> int:
    """
    Write NewsEvent nodes with full enrichment + AFFECTS relationships.
    Replaces record_news() for the live pipeline.
    """
```

**Backward compatibility:** Keep `record_news()` as a thin wrapper that calls `record_news_enriched()` with defaults. Existing callers are not broken.

**Deliverable:** Every NewsEvent going forward has keywords, risk_level, event_type, and AFFECTS links to relevant Symbol nodes.

---

### Phase 2: Price Reaction Measurement (Complexity: Medium — 6-8 hours)

**Goal:** Create `PriceReaction` nodes for all (NewsEvent, Symbol) AFFECTS pairs. Build the core of the market memory.

**New Celery task** added to `tasks.py`:

```python
@shared_task(name='quant.tasks.measure_news_reactions', max_retries=0,
             soft_time_limit=120, time_limit=180)
def measure_news_reactions():
    """
    For NewsEvent nodes with AFFECTS relationships but no PriceReaction nodes,
    fetch H1 price data and measure reactions at 1h, 4h, 24h horizons.
    Only processes events older than 25 hours (ensures 24h data available).
    """
```

**New method in `graph.py`:**

```python
def get_unmeasured_news_events(self, min_age_hours: int = 25, 
                                limit: int = 50) -> List[Dict]:
    """
    Return (news_event_id, symbol, news_timestamp) tuples where
    AFFECTS relationship exists but no PriceReaction has been created.
    """
    query = """
    MATCH (n:NewsEvent)-[af:AFFECTS]->(s:Symbol)
    WHERE n.timestamp < datetime() - duration({hours: $min_age})
      AND NOT (n)<-[:MEASURES]-(:PriceReaction {symbol: s.id})
    RETURN n.id AS news_id, s.id AS symbol,
           n.timestamp AS news_time, af.confidence AS affinity
    ORDER BY n.timestamp DESC
    LIMIT $limit
    """

def record_price_reaction(self, reaction_data: Dict[str, Any]) -> Optional[str]:
    """Write a PriceReaction node and link it to its NewsEvent and Symbol."""
```

**Beat schedule entry** (add to `settings.py`):

```python
'measure-news-reactions': {
    'task': 'quant.tasks.measure_news_reactions',
    'schedule': 60.0 * 30,  # every 30 minutes — non-urgent, 24h lag anyway
},
```

Queue: `analysis` (not `critical` or `default`).

**Deliverable:** Pattern recognition queries (section 6) become answerable within 48 hours of deployment, growing richer over days.

---

### Phase 3: BacktestTrade Ingestion (Complexity: Medium — 4-6 hours)

**Goal:** Translate existing `BacktestResult` records and future backtest runs into graph nodes.

**Files to modify:**

- `backend/django/app/quant/knowledge/graph.py` — Add `record_backtest_run()` and `record_backtest_trades()` methods. Add schema statements for `BacktestTrade` and `BacktestRun`.
- `backend/django/app/quant/tasks.py` — In `run_multi_source_backtest` and `run_custom_backtest` tasks, after `BacktestResult.objects.create(...)`, fire `record_to_graph.delay({'type': 'backtest_run', 'backtest_result_id': result.id})`.
- `backend/django/app/quant/tasks.py` — In `record_to_graph` handler, add `elif record_type == 'backtest_run':` branch that reads `BacktestResult` by ID and calls `graph.record_backtest_run()` + `graph.record_backtest_trades()`.

**One-time backfill script** (run manually via `python manage.py shell`):

```python
# Reads all existing BacktestResult records and pushes them to graph
# Not a Celery task — runs once from Django shell
from app.nexus.models import BacktestResult
from app.quant.knowledge.connection import get_graph

graph = get_graph()
for br in BacktestResult.objects.all():
    graph.record_backtest_run({...})
```

This backfill is optional but enables immediate retrospective analysis.

**Deliverable:** Query 2 ("which strategy performs best in volatile regimes") becomes answerable with both live and simulated data.

---

### Phase 4: Historical News Backfill (Complexity: Low-Medium — 4-5 hours + data download time)

**Goal:** Populate the graph with 24 months of historical news + price reactions to build the pattern library before live data accumulates.

**Prerequisite:** Phase 2 must be complete (price reaction measurement logic exists).

**Steps:**

1. Download historical headlines from The Guardian API (free key). Endpoint: `https://content.guardianapis.com/search?section=business,world&from-date=2024-01-01&api-key=...`. Store to a local JSONL file.
2. Filter for forex-relevant keywords using `_score_headlines()` from `news_sentiment.py`.
3. Run a one-time Django management command `manage.py ingest_historical_news --file path.jsonl` that calls `graph.record_news_enriched()` in batches.
4. After ingestion, the `measure_news_reactions` task will naturally process the historical events over subsequent runs (it processes 50 events per 30-minute cycle).

**Alternative** (no API key needed): The GDELT Project provides free event data in CSV format. The `ACTOR1COUNTRYCODE` + `EventCode` columns can be mapped to news categories. More complex to parse but covers events back to 1979.

**Deliverable:** "What happened to gold when Iran was in the news?" query has data going back 24 months immediately after backfill completes, not just from deployment date.

---

### Phase 5: EconomicEvent Ingestion and Reaction Linkage (Complexity: Medium — 5-7 hours)

**Goal:** Create `EconomicEvent` nodes for scheduled macro events (NFP, FOMC, CPI) with actual vs forecast values. Link `PriceReaction` nodes to specific economic events rather than generic news headlines.

**Constraint:** The Finnhub economic calendar endpoint returns HTTP 403 on the free plan. Alternative sources:

| Source | Access | Content |
|---|---|---|
| ForexFactory (scraping) | Free, fragile | Full calendar |
| TradingEconomics | Free tier (100 req/month) | Key events |
| FRED API | Free, API key | US data only |
| Hardcoded NFP dates | Manual CSV, very stable | US only |

**Recommended approach for Phase 5:** Build a hardcoded CSV of upcoming NFP, FOMC, CPI, ECB dates. Update quarterly (10 minutes of work). The `fetch_market_pulse` task already reads this data from the event guard system in `macro_analyst.py` — reuse that.

Add a `record_economic_event()` method to `graph.py` that creates `EconomicEvent` nodes from the event guard's known events. After each event passes, a follow-up enrichment task queries the event outcome (actual vs forecast) from a free data source (FRED for US data) and updates the `actual_value` and `surprise_pct` properties.

**Deliverable:** Query 3 ("typical XAGUSD reaction to NFP") becomes answerable with clean economic event attribution rather than fuzzy keyword matching.

---

### Phase 6: Dashboard Integration (Complexity: Low — 3-4 hours)

**Goal:** Surface market memory insights in the Vue 3 dashboard.

**New REST endpoint** at `nexus/views.py` or a dedicated `graph_views.py`:

```
GET /v1/graph/news-reactions/?symbol=XAUUSD&keywords=iran
GET /v1/graph/strategy-regime-performance/?strategy=ICT+FVG&regime=VOLATILE
GET /v1/graph/upcoming-event-context/?symbol=XAUUSD&event=NFP
GET /v1/graph/pattern-summary/          (summary stats for the memory panel)
```

Each endpoint calls the corresponding query from section 6 and returns JSON.

**Dashboard component:** A new "Market Memory" tab in the existing Vue dashboard with:
- News event timeline with price reactions shown as sparklines
- Strategy heatmap: WR by (strategy × regime) combining live + backtest data
- Pre-event context panel: before NFP, show historical XAGUSD/XAUUSD reactions

This panel uses the existing `usePolling` composable with a 60-second interval (not real-time — memory data changes slowly).

---

## 9. Integration Map — Where Each Pipeline Connects

```
EXISTING CODE                           NEW CODE POINTS
---------------------------------------------------------------------
tasks.py:check_news_sentiment           Phase 1: Pass enriched articles to
  └─ get_market_risk_level()                    record_news_enriched()

tasks.py:fetch_market_pulse             Phase 1: Market pulse articles already
  └─ cache market_pulse:news                    contain headlines — pipe to graph

tasks.py:record_to_graph                Phase 1: Add 'news_enriched' type
  └─ graph.record_news()                        Add 'backtest_run' type (Phase 3)
                                                Add 'trade_news_link' type (Phase 1)

close.py:close_algorithm()              Phase 1: After trade record, fire
  └─ record_to_graph.delay(trade)               'trade_news_link' payload

tasks.py:run_custom_backtest()          Phase 3: After BacktestResult.create()
tasks.py:run_backtest()                          fire 'backtest_run' payload
tasks.py:run_multi_source_backtest()

graph.py:_create_schema()               Phase 1+2+3: Add constraints/indexes
graph.py:record_news()                  Phase 1: Extend → record_news_enriched()

enricher.py:compute_and_cache_features  Phase 4 (activation): Add 6th feature
enricher.py:DEFAULTS                             graph_news_reaction_wr

cvd/entry.py:Market Context Gate        Phase 4 (activation): Add sizing modifier
                                                 based on graph_news_reaction_wr

settings.py:CELERY_BEAT_SCHEDULE        Phase 2: Add measure-news-reactions task
settings.py:CELERY_BEAT_SCHEDULE        Phase 3: Add run-graph-enrichment (already exists)
```

---

## 10. Data Flow — Complete Picture

```
LIVE NEWS FLOW (every 2-5 min)
  fetch_market_pulse (tasks.py)
    → RSS/Finnhub fetch
    → cache: market_pulse:news
    → record_to_graph.delay('news', enriched_articles)
          → graph.record_news_enriched()
                → NewsEvent node (enriched properties)
                → AFFECTS → Symbol nodes (per NEWS_SYMBOL_AFFINITY)
                → CONCURRENT_WITH → MarketCondition (nearest snapshot)

PRICE REACTION MEASUREMENT (every 30 min, 25h lag)
  measure_news_reactions (tasks.py)  [NEW]
    → graph.get_unmeasured_news_events()
    → for each (news_id, symbol): fetch_data_pos(symbol, H1, 30 bars)
    → compute change_1h_pct, change_4h_pct, change_24h_pct
    → classify reaction_type
    → graph.record_price_reaction()
          → PriceReaction node
          → MEASURES → NewsEvent
          → FOR_SYMBOL → Symbol

TRADE CLOSE FLOW (every 15s check)
  close.py: close detected
    → record_to_graph.delay('trade', trade_data)          [EXISTING]
    → record_to_graph.delay('trade_news_link', link_data)  [NEW Phase 1]
          → graph: ENTERED_DURING_NEWS → NewsEvent (4h lookback window)

BACKTEST RUN FLOW (every 6h)
  run_backtest / run_custom_backtest
    → BacktestResult.objects.create()
    → record_to_graph.delay('backtest_run', result_id)   [NEW Phase 3]
          → graph.record_backtest_run()
          → graph.record_backtest_trades() (iterates trades JSON)
                → BacktestRun node
                → BacktestTrade nodes (one per simulated trade)
                → BACKTESTED_SYMBOL, BACKTESTED_BY, IN_RUN rels

ENRICHMENT FLOW (every 5 min)
  run_graph_enrichment (tasks.py)
    → enricher.compute_and_cache_features(symbol, regime_detail)
          → graph.find_similar_conditions()              [EXISTING]
          → graph.get_symbol_regime_history()            [EXISTING]
          → graph.get_news_reaction_wr()                 [NEW Phase 4]
          → cache: graph_features:{symbol}:{direction}
                  (6 features, 6-min TTL)

ENTRY FLOW (every 60s + real-time CVD trigger)
  cvd_entry_algorithm()
    → Layer 7: ML meta-filter
          → enrich_features()
                → cache.get('graph_features:{symbol}:{direction}')
                → returns 6 graph features to XGBoost
    → Layer 4: Market Context Gate (Phase 4 activation)
          → graph_news_reaction_wr < 0.30 + EXTREME → 0.5× size
```

---

## 11. Critical Design Decisions

### Decision 1: PriceReaction as a Node, Not a Relationship Property

`PriceReaction` could be modeled as a property on the `AFFECTS` relationship: `(NewsEvent)-[:AFFECTS {change_1h: ...}]->(Symbol)`. This is simpler. However, making it a node enables:
- Querying all reactions for a symbol independently of news events
- Adding a `volatility_spike` boolean as an independent filter
- Future extension (e.g., adding M15 reaction measurement)
- The `TRIGGERED_BY` relationship pointing to either `NewsEvent` or `EconomicEvent`

The node approach is chosen. Trade-off: slightly more complex write path.

### Decision 2: Separate BacktestTrade from Trade

`BacktestTrade` could reuse the `Trade` node type with a flag `is_backtest: true`. This is simpler but conflates live execution with simulation in every win rate query. Every query would need `WHERE NOT t.is_backtest`. Making them distinct node types means:
- Pattern recognition queries on `Trade` implicitly refer to live performance
- Comparison queries explicitly join `Trade` and `BacktestTrade`
- The schema is self-documenting

Separate node types are chosen.

### Decision 3: Symbol Affinity as Static Config, Not ML Classification

News-to-symbol affinity could be learned from historical correlations (e.g., how often does an "Iran" headline precede a gold move >0.3%?). That requires the price reaction data to already exist — a chicken-and-egg problem at the start. Static affinity rules are used initially (Phase 1), and after Phase 2 generates enough `PriceReaction` data, a separate enrichment pass can update `AFFECTS.confidence` dynamically using Cypher aggregations. This is a Phase 5+ enhancement.

### Decision 4: 25-Hour Minimum Age for Reaction Measurement

Some news events may have market-moving follow-ups within 24 hours (a headline at 2pm, then escalation at 8pm). Waiting 25 hours ensures the 24h price window is complete and not contaminated by the same session's subsequent moves. The trade-off is a one-day lag in memory updates, which is acceptable for a strategic memory system.

### Decision 5: No Async Neo4j Driver

The existing system uses the synchronous `neo4j` driver. All graph writes happen via Celery tasks (fire-and-forget), so blocking the task worker for ~5ms Neo4j round-trip is acceptable. Introducing the async driver would require a second connection pool and complicate the singleton pattern in `connection.py`. The synchronous approach is kept. The `soft_time_limit=10` on `record_to_graph` provides the safety net.

---

## 12. Complexity Estimates

| Phase | Scope | Estimated Hours | Risk |
|---|---|---|---|
| Phase 1: News Enrichment | Extend `record_news()`, add AFFECTS rels, add trade-news links in `close.py` | 3-4h | Low. Additive changes to existing methods. No new Celery tasks. |
| Phase 2: Price Reaction Measurement | New `measure_news_reactions` task, `PriceReaction` node, measurement logic | 6-8h | Medium. New task, new MT5 fetch loop, edge cases on missing bars. |
| Phase 3: BacktestTrade Ingestion | New node types, extend `run_backtest` tasks, one-time backfill | 4-6h | Low-Medium. Trade JSON format is well-known. |
| Phase 4: Historical News Backfill | Data download + management command + batch ingestion | 4-5h + data | Low. Pure ETL, no runtime complexity. |
| Phase 5: EconomicEvent | Hardcoded calendar, FRED lookup, reaction linkage | 5-7h | Medium. External data dependency. |
| Phase 6: Dashboard Integration | 4 REST endpoints, Vue panel, usePolling integration | 3-4h | Low. Standard DRF + Vue pattern. |
| **Total** | | **25-34h** | |

---

## 13. Rollout Order

The recommended build sequence:

1. Phase 1 (News Enrichment) — deploy first, starts building the enriched news record immediately
2. Phase 2 (Price Reaction) — deploy second, within a week of Phase 1
3. Phase 4 (Historical Backfill) — run once on the MacBook Pro after Phase 2 is stable
4. Phase 3 (BacktestTrade) — run alongside Phase 4 (backfill while backtest data is being created)
5. Phase 5 (EconomicEvent) — run after backfill, once 2+ NFP cycles have been measured
6. Phase 6 (Dashboard) — last, once sufficient data exists to make the panels non-trivial

Phases 1 and 2 together form the minimum viable market memory. Phases 3-5 deepen it. Phase 6 makes it visible.

---

## 14. Testing Considerations

### Graph Write Tests

Every new `graph.py` method follows the existing pattern: the method body is `if not self.connected: return None` with a try/except wrapper. Test by mocking `get_graph()` to return `None` — all callers must handle this silently.

For integration tests, spin up a local Neo4j instance via `neo4j:5-community` Docker container. The existing `_create_schema()` method creates all indexes idempotently — safe to call on a fresh database.

### Price Reaction Edge Cases

- News event with timestamp outside MT5 trading hours (weekend): `fetch_data_pos` will return bars from the next session open. The reaction window then measures session-gap candles. Tag these with `reaction_note = 'WEEKEND_GAP'` to exclude from standard aggregations.
- Symbol not available in MT5 (e.g., `NG-C` during maintenance): wrap in try/except, set `reaction_type = 'UNAVAILABLE'`.
- News event from historical backfill + price data only available 10 months back: attempt measurement, if bars are unavailable set `reaction_type = 'NO_DATA'`.

### Query Performance

All four pattern recognition queries rely on the indexes defined in section 5. Verify with `EXPLAIN` prefix before deployment. Expected query plans:

- Query 1: NodeIndexScan on `NewsEvent(timestamp)` + filter on `keywords`, then expand to `PriceReaction` — sub-5ms for <10,000 news nodes.
- Query 5 (runtime): `NodeIndexScan on Trade(symbol)` + filter `direction + entry_time` — sub-3ms with proper composite index.

Add a composite index `FOR (t:Trade) ON (t.symbol, t.direction)` if Query 5 latency exceeds 10ms in production.

---

## 15. Feature Flag Integration

The existing `.env` approach for `GRAPH_FEATURES_ACTIVE` and `GRAPH_ROUTER_SIGNAL_ACTIVE` applies directly:

| Flag | Controls |
|---|---|
| `GRAPH_FEATURES_ACTIVE=false` | enricher.py returns defaults; graph_news_reaction_wr not used in XGBoost |
| `GRAPH_FEATURES_ACTIVE=true` | enricher.py computes all 6 features; XGBoost uses them (requires model retrain after activation) |
| `GRAPH_ROUTER_SIGNAL_ACTIVE=false` | No sizing modifier in cvd/entry.py Layer 4 |
| `GRAPH_ROUTER_SIGNAL_ACTIVE=true` | 0.5× sizing modifier active when graph_news_reaction_wr < 0.30 + EXTREME news |

These flags are checked via `getattr(settings, 'GRAPH_FEATURES_ACTIVE', False)`. No code changes needed to the flag mechanism.

The paper trading run (March 15-31) continues without activating these flags. After the run ends and the XGBoost model is trained on the collected data, `GRAPH_FEATURES_ACTIVE=true` can be set and the model retrained to include the graph features.
```

---
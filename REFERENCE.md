# MT5 Quant Server — Reference Document
> Created Mar 18, 2026 after full codebase audit. Source of truth for what was built and why we're starting clean.

---

## What Was Built (Git History Summary)

| Phase | Commits | What Was Added | Verdict |
|-------|---------|----------------|---------|
| Foundation | `29b19d1`–`cafc163` | Django + Vue dashboard + MT5 Flask API | ✅ KEEP |
| CVD Signal | `a52ddfc` | CVD Lack of Participants + Absorption strategies | ✅ KEEP (the edge) |
| Multi-domain | `960d310` | Crypto + Hyperliquid + strategy builder UI | ⚠️ Partial |
| Risk layer | `bee667d`, `1ca56ce` | Risk-based sizing, circuit breaker, reconciliation | ✅ KEEP |
| ML Phase 1 | `4a7d982`, `5cb1ea5` | XGBoost, position manager, adaptive sizing | ❌ Data wiped 3×, useless |
| 8-phase brain | `5c088c8` | HMM, confluence, ICT chain, SMC, position manager | ❌ Overengineered, no data |
| Neo4j | `46f7683`–`1c26fe9` | Knowledge graph, pattern matching, Haiku labeling | ❌ Phase 1 only, passive recording |
| Lighter DEX | `8549c85` | Crypto DEX trading via signer proxy on macOS port 5555 | ❌ Lost $30 test budget |

**Conclusion:** Two weeks of building on top of data that was wiped 3+ times. The ML/HMM/Neo4j layers have no data foundation to justify them. The execution layer (Flask MT5 API, position sizing, trailing stop, close reconciliation) is solid and stays.

---

## The Only Real Edge: CVD Lack of Participants

### Pure Signal Math
```
BEARISH (sell setup):
  price makes higher high AND cvd makes lower high
  → buyers exhausted, price unsupported

BULLISH (buy setup):
  price makes lower low AND cvd makes higher low
  → sellers exhausted, price unconfirmed
```

**CVD calculation (bar-based proxy):**
```python
delta = volume * (2*close - high - low) / (high - low)
cvd = cumsum(delta)  # running total
```

**Implementation:** `backend/django/app/quant/indicators/cvd.py` lines 102–130

**Historical performance:**
- CVD LoP: +€23, 46.2% WR (only profitable strategy in live testing)
- CVD Absorption: -€34, 23.8% WR (disabled)
- Everything else: net loser

### Supporting Filters (the ones that actually matter)
1. **HTF Bias** — EMA(8) vs EMA(34) on H4. Signal must align or be neutral.
2. **Unmitigated FVG** — 3-bar imbalance within 2×ATR of current price. Entry precision.
3. **Session** — London (07:00–10:00 UTC) + London-NY overlap (13:00–17:00 UTC) ONLY.
4. **Circuit breaker** — 5 consecutive losses → 30min pause per symbol.

### Risk Parameters
```python
CAPITAL_PER_TRADE = 2000      # EUR
SL_ATR_MULTIPLIER = 1.8       # SL = 1.8 × ATR(14)
TP_ATR_MULTIPLIER = 3.6       # TP = 3.6 × ATR(14) = 1:2 R:R exact

# Energy symbols (NG-C, USOUSD, UKOUSDft)
ENERGY_CAPITAL = 300
ENERGY_SL = 2.0               # Wider SL for energy
ENERGY_TP = 4.0               # Still 1:2 R:R
```

---

## What to KEEP (Execution Layer)

### MT5 Flask API — `backend/mt5/app/routes/`
| File | Endpoints | Notes |
|------|-----------|-------|
| `order.py` | POST /order, /order_check, GET /order_calc_margin, /order_calc_profit | Core execution |
| `position.py` | POST /close_position, /close_all_positions, /modify_sl_tp, GET /get_positions | Position mgmt |
| `data.py` | GET /fetch_data_pos, /fetch_data_range, /fetch_ticks, POST /fetch_data_pos_batch | OHLCV + ticks |
| `account.py` | GET /account_info | Balance/equity |
| `history.py` | GET /history_deals_get, /get_deal_from_ticket | Trade history |
| `symbol.py` | GET /symbol_info/{sym}, /symbol_info_tick/{sym}, /symbols_get | Metadata |
| `health.py` | GET /health | Healthcheck |
| `error.py` | Error handlers | Error handling |

### Django Utils — `backend/django/app/utils/`
| File | Key Functions | Notes |
|------|---------------|-------|
| `api/order.py` | `send_market_order()`, `modify_sl_tp()`, `close_full()`, `close_partial()` | Wraps Flask API. R:R gate (min 2.0) |
| `api/positions.py` | `get_positions()` | Returns DataFrame of open positions |
| `api/data.py` | `fetch_data_pos()`, `fetch_data_pos_batch()`, `fetch_ticks()`, `fetch_data_range()` | OHLCV + tick data |
| `api/account.py` | `get_account_info()`, `check_margin_for_order()`, `check_order()` | Account + dry-run |
| `api/ticket.py` | `history_deals_get()`, `get_deal_from_ticket()` | Deal history for close reconciliation |
| `arithmetics.py` | `calculate_risk_based_lots()`, `get_price_at_pnl()`, `get_pnl_at_price()` | Pure math, no logic |
| `constants.py` | `MT5Timeframe` enum | Timeframe constants |

### Celery Tasks to KEEP — `backend/django/app/quant/tasks.py`
| Task | Frequency | Queue | Purpose |
|------|-----------|-------|---------|
| `run_quant_trailing_stop_algorithm` | every 2s | critical | Trails SL/TP on open positions |
| `run_quant_close_algorithm` | every 15s | critical | Detects closed positions, updates DB |
| `run_position_reconciliation` | every 30s | critical | Syncs Django Trade records with MT5 |
| `check_tick_consumer_health` | every 5m | default | Monitors Redis tick stream |
| `fetch_market_pulse` | every 1h | default | News sentiment (Finnhub RSS) |
| `record_daily_performance` | daily | default | Daily P&L snapshot |

### Algorithm Files to KEEP
| File | Lines | Purpose |
|------|-------|---------|
| `algorithms/position_manager.py` | 1,204 | 6-phase trailing: breakeven→partial→swing trail→profit protect |
| `algorithms/close/close.py` | ~200 | Detects closes, updates Trade records, releases PairLocks |
| `algorithms/cvd/config.py` | ~80 | Risk parameters (SL/TP multipliers, capital per trade) |
| `indicators/cvd.py` | ~200 | Bar-based CVD divergence detection (THE SIGNAL) |
| `indicators/cvd_realtime.py` | ~300 | Tick-level CVD via Redis pub/sub |
| `tick_consumer.py` | ~400 | Redis pub/sub tick processor → RealtimeCVD cache |

### Database Schema to KEEP
| Table | Keep? | Reason |
|-------|-------|--------|
| `nexus_strategyconfig` | ✅ Schema + data | Strategy definitions, is_active flags |
| `nexus_customstrategy` | ✅ Schema + data | JSON strategy definitions |
| `nexus_trade` | ✅ Schema only | Trade records (TRUNCATE data) |
| `nexus_pairlock` | ✅ Schema only | Symbol locks (TRUNCATE data) |
| `nexus_tradefeature` | ✅ Schema only | ML training data (TRUNCATE, restart clean) |
| `nexus_mlmodel` | ❌ TRUNCATE | Old model versions with no data |
| `nexus_marketregime` | ❌ TRUNCATE | Cached HMM states (stale) |
| `nexus_backtestresult` | ❌ TRUNCATE | Old backtests |
| `nexus_rotationlog` | ❌ TRUNCATE | Strategy rotation history |

### CLI Tool
`tools/trade_cli.py` — standalone Python CLI for manual market analysis and order placement. Pure math, hits MT5 Flask API directly. Keep as-is.

---

## What to DELETE (Complexity Bloat)

### Tier 1 — Full Directories (DELETE)
```
backend/django/app/quant/knowledge/          # Neo4j graph — 3,737 lines, no data
backend/django/app/quant/ml/                 # HMM + XGBoost + LLM — 4,631 lines, no data
backend/django/app/quant/intelligence/       # Claude Haiku labeler — async, non-blocking, pointless without data
backend/django/app/quant/algorithms/scalping/      # Dead (disabled)
backend/django/app/quant/algorithms/mean_reversion/ # Dead (disabled)
```

### Tier 2 — Individual Files (DELETE)
```
backend/django/app/quant/algorithms/brain_entry.py  # Replace with clean entry.py
backend/django/app/quant/backtester.py
backend/django/app/quant/backtester_generic.py
backend/django/app/quant/backtester_mr.py
backend/django/app/quant/data_fetcher.py
backend/django/app/quant/strategy_orchestrator.py
```

### Tier 3 — Indicators (SLIM DOWN — delete unused)
```
DELETE: energy.py, scalping.py, gold_silver_ratio.py, donchian.py, vwap.py,
        zone_mapper.py, support_resistance.py, news_sentiment.py, displacement.py,
        smc.py, smc_detector.py, session_levels.py, session_range.py

KEEP:   cvd.py, cvd_realtime.py, market_structure.py, mtf_context.py, session_hybrid.py,
        kill_zones.py, momentum.py (EMA functions only)
```

### Tier 4 — Celery Tasks (REMOVE from tasks.py)
```
run_remote_training          # No training machine running
run_multi_source_backtest    # No backtesting
record_to_graph              # Neo4j phase 1, passive, pointless without data
run_graph_enrichment         # Neo4j enrichment
check_graph_health           # Neo4j health check
run_weekly_edge_review       # Haiku weekly scan
update_brain_pattern         # Haiku post-close labeling
run_brain_entry              # Replace with clean entry task
```

---

## Clean Architecture (Fresh Start)

### Forex Bot — New Entry Algorithm
```
File: backend/django/app/quant/algorithms/entry.py (~150 lines)

Every 5 minutes (Celery beat):
  1. Skip if circuit breaker active (5 losses → 30min pause)
  2. Skip if max positions reached (5 open)
  3. Fetch H4 bars for each symbol (batch endpoint)
  4. For each symbol:
     a. Detect CVD LoP signal (pure divergence math)
     b. Confirm HTF bias alignment (EMA 8/34 on H4)
     c. Find unmitigated FVG within 2×ATR
     d. Check session (London or London-NY only)
     e. ALL must align → execute
  5. Calculate lots (risk-based: €2000 capital, 1.8×ATR SL)
  6. Place order → trailing stop takes over
```

### Symbols to Trade (Forex)
```python
SCAN_SYMBOLS = [
    'XAUUSD',                          # Gold — highest brain WR historically
    'EURUSD', 'GBPUSD', 'USDJPY',     # Major forex — liquid, tight spreads
    'NG-C', 'USOUSD', 'UKOUSDft',     # Energy — separate risk tier
    # REMOVED: XAGUSD — spread 4.8% of ATR (killed account)
]
```

---

## Database Wipe Commands

```bash
# 1. PostgreSQL — wipe trade data, keep configs
docker exec postgres psql -U admin -d postgres -c "
TRUNCATE nexus_trade CASCADE;
TRUNCATE nexus_tradefeature CASCADE;
TRUNCATE nexus_tradeclosepricesmutation CASCADE;
TRUNCATE nexus_backtestresult CASCADE;
TRUNCATE nexus_marketregime CASCADE;
TRUNCATE nexus_mlmodel CASCADE;
TRUNCATE nexus_rotationlog CASCADE;
TRUNCATE nexus_pairlock CASCADE;
TRUNCATE nexus_trainingrun CASCADE;
"

# 2. Redis — flush all 3 databases
docker exec redis redis-cli FLUSHALL

# 3. Neo4j — wipe entire graph
docker exec neo4j cypher-shell -u neo4j -p trading_brain_2026 "MATCH (n) DETACH DELETE n;"
```

---

## Source of Truth Priority

1. **MT5 Broker history** — ground truth, never wiped (VNC → Account History)
2. **`python3 tools/trade_cli.py status`** — live positions direct from MT5 API
3. **MT5 Flask API** (`http://localhost:5001`) — raw broker data
4. **Django DB** — derived, can have gaps if Celery missed a close event
5. **Dashboard** — tertiary, pulls from Django DB

**Never trust the dashboard alone for P&L. Always verify against MT5 history.**

---

## Key Technical Constraints (Never Forget)

- **MT5 source NOT volume-mounted** — code baked into Docker image. `docker cp` for hot-patch, rebuild for permanent.
- **Order field:** `type` (not `order_type`). Filling: `ORDER_FILLING_IOC` only (Vantage broker).
- **Account currency:** EUR (not USD). `trade_tick_value` returns EUR values already.
- **`comment` field:** MT5 under Wine rejects non-empty comment strings. OMIT entirely from `request_data`.
- **`order_send()` result:** Key is `order` (not `ticket`) for the order number.
- **`get_positions()` returns:** `{"positions": [...]}` dict — extract with `.get("positions", [])`.
- **Batch endpoint timeframe:** Send as string `"H4"` not integer `16388`.
- **Bar `time` field:** Returns as GMT string, not unix timestamp.
- **Git push remote:** `disciplined` (not `origin` — no push access there).

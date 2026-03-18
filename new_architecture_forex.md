# New Forex Architecture — Brain-Driven Trading

**Date:** March 2026
**Status:** Built, deployed, bot paused until paper trading confirms profitability

---

## The Philosophy Shift

**Old system:** Start with every trade, build a wall of filters to block bad ones.
**New system:** Start with nothing. The brain selects trades based on what has actually worked.

The difference is a selector vs a filter. A filter is defensive and complex.
A selector is confident and simple. Elite discretionary traders are selectors.

---

## What Got Removed

| File | Lines | What it did |
|------|-------|-------------|
| `cvd/entry.py` | 2,348 | 12-layer filter pipeline |
| `algorithms/strategy_router.py` | ~300 | 11 strategies mapped to HMM regimes |
| `algorithms/confluence_scorer.py` | ~250 | 0–14 point gate |
| `macro_analyst.py` | ~180 | LLM news gating |
| `strategy_evolver.py` | ~200 | Unused strategy evolution |
| Most of `advisor.py` | ~1,100 | Complex query engine |

**Net removed: ~4,400 lines of Python logic.**

The 12 layers that used to gate trades:
```
Time filter → Circuit breaker → Symbol WR filter → Market context (LLM) →
Strategy Router → Group tendency → ML meta-filter → Signal detection →
Anti-churn → Confluence gate → Margin pre-check → Risk sizing
```

Most of these layers were blocking profitable trades without adding real edge.
The research: complex systems show 73% median Sharpe degradation from backtest to live.
Simple systems don't. The brain replaces all of it with one Neo4j query.

---

## New Architecture

```
Every 5 minutes:
─────────────────────────────────────────────────────────────────────
MT5 H4 OHLCV (50 bars)
    │
    ▼
Signal Detector  (pure math, ~100 lines, zero latency)
  - FVG present? (3-bar imbalance gap within 2×ATR of current price)
  - CVD direction? (money flow vote: last 5 bars cumulative delta)
  - HTF bias? (EMA 8 vs EMA 34 on H4)
  - Session? (ASIA / LONDON / NY_OVERLAP / NY / EVENING)
    │
    ▼
Build condition fingerprint:
  "XAUUSD_bullish_fvg_present+htf_aligned+session_london"
    │
    ▼
Neo4j Brain Query  (<20ms, single Cypher)
  MATCH (p:StrategyPattern {symbol, direction, active: true})
  WHERE conditions overlap ≥ 2 AND WR ≥ 58% AND sample ≥ 3
  ORDER BY WR × weight × match_depth DESC
    │
    ├─ Match found → Execute: BUY/SELL + ATR SL/TP
    └─ No match    → Skip. No trade. No FOMO.
─────────────────────────────────────────────────────────────────────

After trade closes:
    │
    ▼
update_brain_pattern (Celery, async)
  - Update StrategyPattern node: wins++, total++, recalculate WR
  - Live trades → weight = 1.0 (reference data weight = 0.3)
    │
    ▼
Haiku label (async, ~$0.001)
  Reads symbol + conditions + outcome → writes human label onto pattern node
  "XAUUSD bullish FVG bounce London open with OB confirmation"
```

---

## The Brain: StrategyPattern Nodes

Each node is a **pattern that has actually worked** (or failed). Not a hardcoded rule.
Derived from 6 months of real MT5 H4 data via backtest seeder, updated by every live trade.

### Live Pattern Table (35 nodes, March 2026)

**Metals — High confidence**

| Symbol | Direction | WR | n | E(R) | Conditions |
|--------|-----------|-----|---|------|------------|
| XAUUSD | bullish | **100%** | 6 | 2.00 | fvg + htf_aligned + ob + london |
| XAUUSD | bullish | **100%** | 4 | 2.00 | fvg + htf_aligned + ob + ny_overlap |
| XAUUSD | bullish | **100%** | 2 | 2.00 | fvg + htf_aligned + ob + asia |
| XAUUSD | bullish | 80% | 10 | 1.78 | cvd + fvg + htf_aligned + ob + ny_overlap |
| XAGUSD | bullish | **100%** | 4 | 2.00 | fvg + htf_aligned + ob + asia |
| XAGUSD | bullish | **100%** | 3 | 2.00 | fvg + htf_aligned + ob + ny_overlap |
| XAGUSD | bullish | **100%** | 3 | 2.00 | fvg + htf_aligned + ob + ny |
| XAGUSD | bullish | **100%** | 3 | 2.00 | cvd + fvg + htf_aligned + ob + ny_overlap |
| XAGUSD | bullish | **100%** | 2 | 2.00 | fvg + htf_aligned + ob + london |

**Energy — Selective**

| Symbol | Direction | WR | n | E(R) | Conditions |
|--------|-----------|-----|---|------|------------|
| NG-C | bearish | **100%** | 3 | 2.00 | fib + fvg + htf_aligned + ob + london |
| NG-C | bearish | **100%** | 2 | 2.00 | fvg + htf_aligned + ob + ny_overlap |
| UKOUSDft | bullish | 60% | 5 | 1.48 | fvg + htf_aligned + ob + london |

**Forex — Avoid until more data**

| Symbol | Direction | WR | n | Note |
|--------|-----------|-----|---|------|
| GBPUSD | bearish | **100%** | 2 | asia session only |
| USDJPY | bullish | 50% | 4 | insufficient sample |
| EURUSD | bearish | 0% | 1 | skip — no edge detected |

**Brain's verdict from 6 months of real data:**
- Metals during elevated geopolitical risk = strongest edge in the market
- Natural gas structure = clean, reliable
- JPY = avoid (carry trade reversals make FVG patterns unreliable)
- EUR = avoid until more data

---

## Learning Loop

```
Week 1 (now):
  35 patterns, avg WR 63.3%. Mostly from backtest reference data (weight 0.3).
  Brain is cautious — requires WR ≥ 58% + sample ≥ 3.

Month 1:
  ~20 live trades close. Live trades override reference data (weight 1.0).
  Brain starts saying "I've seen this 8 times live, 7 worked."

Month 3:
  100+ live trades. Reference data has faded (0.3 weight).
  Haiku has labeled every pattern. Brain has discovered setups not in any textbook.
  Patterns with < 35% WR over 8+ samples auto-deactivated weekly.

Month 6:
  Brain is trading its own learned patterns, not anyone else's rules.
```

---

## Risk Management (stays in Python — not in the brain)

The brain decides WHETHER to trade and which direction.
Python handles the numbers:

| Parameter | Forex/Metals | Energy |
|-----------|-------------|--------|
| Capital per trade | €2,000 | €300 |
| SL | 1.8 × ATR | 2.0 × ATR |
| TP | 3.6 × ATR | 4.0 × ATR |
| R:R | 1:2 exact | 1:2 exact |
| Max open positions | 5 global | — |
| Circuit breaker | 5 losses → 30min pause | — |
| Symbol cooldown | 5min after entry | — |

**Position manager** (unchanged): M15→H1→H4 trailing stop escalation, partial close at 1.5R.
This is what turns 50% WR into profitability — never let a winner turn into a loser.

---

## Claude Haiku Integration (€100 credits)

**Not for news. Not for trade gating. Pure brain enrichment.**

| Use | Trigger | Cost | Annual budget |
|-----|---------|------|---------------|
| `label_trade_pattern()` | Every trade close | ~$0.001 | ~$0.20 on 200 trades |
| `weekly_edge_review()` | Every Monday 06:00 UTC | ~$0.05 | ~$2.60/year |

At these rates, €100 credits covers **10+ years** of bot operation.

The weekly review is the key self-improvement loop:
- Haiku reads all active StrategyPattern nodes
- Flags patterns losing edge (WR trending down)
- Identifies emerging patterns worth promoting
- Auto-deactivation: WR < 35% over 8+ samples → pattern set `active: false`

---

## Raspberry Pi Role

Pi is an async enrichment layer — it never blocks or gates trades.

**What Pi does:**
- Fetches news APIs periodically → pushes lightweight `(:MacroEvent)` nodes into Neo4j
- Trains XGBoost model when 200+ ICC trades accumulate (offloaded from Mac mini)
- Runs `qwen2.5:1.5b` via Hailo NPU for lightweight local pattern analysis

**What Pi does NOT do:**
- Pi does not gate trades in real time
- No RSS sentiment scoring in the entry loop
- Macro events are context enrichment on outcome nodes, not blockers

**MacroEvent nodes** use the same NEAR_EVENT relationship we built for geopolitical events.
The brain can later query: "do XAUUSD FVG patterns perform differently near Fed decisions?"
without that being a hard gate on every trade.

---

## File Map

```
quant/
├── algorithms/
│   ├── brain_entry.py        ← NEW: the entire entry algorithm (~220 lines)
│   ├── position_manager.py   ← UNCHANGED: trailing stop, partial close
│   └── close/close.py        ← MODIFIED: fires update_brain_pattern after close
│
├── knowledge/
│   ├── graph.py              ← EXTENDED: StrategyPattern CRUD + brain query
│   ├── pattern_detector.py   ← FVG, CVD proxy, HTF bias, session detection
│   ├── trade_simulator.py    ← Multi-R:R simulation for seeder
│   ├── backtest_seeder.py    ← Populates reference patterns from MT5 history
│   └── geo_events.py         ← 24 static geopolitical events (Iran/Israel/Russia/Fed)
│
├── intelligence/
│   └── claude_analyst.py     ← REPURPOSED: label_trade_pattern + weekly_edge_review
│
└── tasks.py                  ← run_brain_entry (5min) + update_brain_pattern + weekly review
```

**Dead files removed:**
- `algorithms/strategy_router.py`
- `algorithms/confluence_scorer.py`
- `macro_analyst.py`
- `strategy_evolver.py`

---

## Activating the Bot

The bot is currently paused. Before turning it on:

```bash
# 1. Verify StrategyPattern nodes are populated
docker exec -it neo4j cypher-shell -u neo4j -p trading_brain_2026 \
  "MATCH (p:StrategyPattern {active: true}) RETURN p.symbol, p.direction, p.win_rate, p.total ORDER BY p.win_rate DESC"

# 2. Run a dry scan (logs only, no orders placed — bot is paused)
docker exec -it django python manage.py shell -c "
from app.quant.algorithms.brain_entry import brain_entry_algorithm
brain_entry_algorithm()
"

# 3. Unpause when ready
# Dashboard → Bot Controls → Resume
```

**When to unpause:** After confirming the brain query finds valid patterns during London session
and the signal detection correctly identifies FVGs on live XAUUSD/XAGUSD bars.

---

## What the Brain Still Needs to Learn

The current 35 pattern nodes are derived from **backtest simulation** (weight 0.3).
They need live confirmation to graduate to full confidence (weight 1.0).

Priority patterns to confirm live:
1. `XAUUSD_bullish_fvg_present+htf_aligned+ob_present+session_london` — 100% WR n=6, most important
2. `XAGUSD_bullish_fvg_present+htf_aligned+ob_present+session_ny_overlap` — 100% WR n=3
3. `NG-C_bearish_fib_present+fvg_present+htf_aligned+ob_present+session_london` — 100% WR n=3

Each live confirmation moves these from reference (0.3) to live weight (1.0).
At ~20 live trades the brain starts trusting itself over the backtest data.

---

## Neo4j Management Queries

```cypher
// All active patterns ranked by score
MATCH (p:StrategyPattern {active: true})
RETURN p.symbol, p.direction, p.win_rate, p.total, p.avg_r, p.label, p.source
ORDER BY p.win_rate * p.weight * p.total DESC

// Deactivate patterns manually
MATCH (p:StrategyPattern {fingerprint: $fp})
SET p.active = false

// Re-seed patterns from backtest data after adding new symbols
docker exec -it django python manage.py shell -c "
from app.quant.knowledge.connection import get_graph
g = get_graph()
g.build_patterns_from_reference_trades()
"

// Trigger weekly review manually
docker exec -it django python manage.py shell -c "
from app.quant.tasks import run_weekly_edge_review
run_weekly_edge_review()
"
```

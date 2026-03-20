# Trading Logic Evolution — Complete History

> Generated 2026-03-19 from git history analysis (85 commits, Mar 7 -- Mar 18, 2026)

---

## Table of Contents

1. [Timeline Overview](#timeline-overview)
2. [Phase 1: Foundation (Mar 7--8)](#phase-1-foundation-mar-78)
3. [Phase 2: First Live Trades & Bugs (Mar 9--10)](#phase-2-first-live-trades--bugs-mar-910)
4. [Phase 3: The -$687 Drawdown & Tightening (Mar 11)](#phase-3-the-687-drawdown--tightening-mar-11)
5. [Phase 4: ML Training Mode & Filter Loosening (Mar 12)](#phase-4-ml-training-mode--filter-loosening-mar-12)
6. [Phase 5: Anti-Churn, SL/TP Tuning, ML Retrain (Mar 13)](#phase-5-anti-churn-sltp-tuning-ml-retrain-mar-13)
7. [Phase 6: Paper Trading Launch & Sunday Disaster (Mar 14--16)](#phase-6-paper-trading-launch--sunday-disaster-mar-1416)
8. [Phase 7: The Brain Era (Mar 17)](#phase-7-the-brain-era-mar-17)
9. [Phase 8: Brain Replacement & Simplification (Mar 18)](#phase-8-brain-replacement--simplification-mar-18)
10. [The Crypto / Lighter.xyz Side](#the-crypto--lighterxyz-side)
11. [What Worked](#what-worked)
12. [What Did Not Work](#what-did-not-work)
13. [Backtest vs Live Comparison](#backtest-vs-live-comparison)
14. [Current State of the Codebase](#current-state-of-the-codebase)
15. [Key Lessons Learned](#key-lessons-learned)
16. [Strategy Performance Scorecard](#strategy-performance-scorecard)

---

## Timeline Overview

```
Mar 7-8    Foundation: dashboard, backtester, CVD indicator, multi-domain models
Mar 9      Lighter.xyz bot, USDJPY lot fix, first entry/position manager code
Mar 10     Macro analyst, session filter, strategy evolver, live performance gate
Mar 11     -$687 DRAWDOWN → tighten everything → 8-phase brain plan → confluence scorer
Mar 12     TRAINING_MODE on → loosen filters → commodity trading → Polymarket removed
Mar 13     Anti-churn, SL 1.2→1.8 ATR, TP 2.5→3.5 ATR, XGBoost retrain, tick consumer
Mar 14     Multi-venue crypto, tick streamer in Docker
Mar 15     PAPER TRADING LAUNCH (all gates active)
Mar 16     SUNDAY DISASTER: 11 trades, 1W/10L, -$116 → circuit breaker saves the day
           Risk-based sizing replaces capital×leverage, MT5↔DB reconciliation
Mar 17     BRAIN ERA: Neo4j advisor, structure reader, MTF context, Claude API,
           Pi NPU FinBERT, WebSocket, DOM orderbook, autonomous structure scanner
Mar 18     BRAIN CLEANUP: 12-layer pipeline → brain_entry.py (220 lines replaces 2,348)
           entry_forex.py (MTF-driven), entry_crypto.py (CVD + structure)
           Deleted: strategy_router, confluence_scorer, macro_analyst, strategy_evolver,
           ict_entry, structure_entry, structure_levels, advisor.py (1,252 lines)
           R:R enforced at 1:2 across all strategies
```

---

## Phase 1: Foundation (Mar 7--8)

### Commits: `29b19d1` through `960d310`

**What was built:**
- Vue.js dashboard with forex/crypto/polymarket sections
- Yahoo Finance backtester with strategy management
- CVD (Cumulative Volume Delta) indicator: `delta = volume * (2*close - high - low) / (high - low)`
- Multi-domain strategy model: CustomStrategy with FOREX/CRYPTO/POLYMARKET domains
- Hyperliquid crypto trading bot (initial version)
- 7 CVD strategy definitions seeded via migration `0007_seed_cvd_strategies.py`

**Key design decisions:**
- GenericBacktester reads strategy definitions from DB (JSON format)
- Shared INDICATOR_REGISTRY between backtest and live trading
- Polymarket integration added (later removed -- illegal in Netherlands)

**Code that survived:** The CVD indicator formula, GenericBacktester, and the multi-domain model architecture are still in use.

---

## Phase 2: First Live Trades & Bugs (Mar 9--10)

### Commits: `e49bffe` through `d522c68`

**What was built:**
- Lighter.xyz DEX trading bot with split architecture (pure-Python reads, macOS proxy writes)
- Position manager with 6 phases: Scale-in, MFE acceleration, Breakeven, Partial close, Swing trail, Profit protection
- Macro analyst using Claude for news analysis
- Live performance gate: auto-disables strategies after 5 losses or -$50 drawdown
- Trading session filter: 07:00-21:00 UTC, block Sundays

**Critical bugs found and fixed:**
- `entry_atr` stored as `"MT5Timeframe.M15"` (string) instead of `"M15"` -- broke position manager entirely
- USDJPY lot sizing: dividing by exchange rate (158) instead of contract size (100,000) -- produced 0.001 lots rounded to 0.0, blocking all JPY trades
- MT5 order API: Django sent string `"BUY"`, Flask compared with `mt5.ORDER_TYPE_BUY` (int 0)
- Order URL was `/send_market_order` (404), correct was `/order`

**Lighter.xyz backtested:** 162 EMA/RSI combos tested, best: EMA 8/21 + RSI 14/30/65 at 53.3% WR, +41.36% PnL, 1.98 PF.

**Risk parameters at this point:**
- Capital: $5,000/trade
- SL: 1.5x ATR, TP: 2.5x ATR
- Max 10 open trades
- No confluence scoring, no ML filter

---

## Phase 3: The -$687 Drawdown & Tightening (Mar 11)

### Commits: `4a7d982` through `5c088c8`

This was the pivotal day. The bot lost $687 in a single session.

**125-trade analysis showed:**
- 10 trades at 09:00 UTC (London open) lost $743 combined
- Overtrading with $5,000/trade and 10 max positions
- No confluence gate -- any CVD signal with HTF alignment was taken
- Position manager MFE lock at 60% was too tight (choking winners)
- Flat trade exit at 20 minutes was too slow (losers average 70 minutes)

**Immediate response (`4223ff3`):**
- Capital: $5,000 -> $500/trade (10x reduction)
- SL: 1.5x -> 1.2x ATR (tighter stops)
- Max open: 10 -> 5
- Blocked 09:00 UTC entirely
- MFE lock: 60% -> 40% (give winners room)
- Flat trade exit: 20 -> 15 minutes
- Profit protection giveback: 50% -> 40%
- Disabled 4 strategies, kept only: CVD Lack of Participants (PF:1.41), EMA Momentum M15, Bollinger Mean Rev M5

**Strategy orchestrator added (`5cb1ea5`):**
- Regime-based strategy allocation (preferred/acceptable/hostile)
- Rolling performance auto-pause (WR < 25%)
- Capital scaled back up to $5,000/trade with $3k daily halt, $10k drawdown safety
- Kill switch: 8 -> 5 consecutive losses, drawdown threshold -$100 -> -$50

**Market Wizards principles added (`8f41ef4`):**
- O'Neil hard dollar loss ceiling: $50/trade absolute cap
- Livermore daily profit preservation: after +$50 daily, reduce to 50% sizing
- Livermore leader-weighted regime: EURUSD/GBPUSD get 2x voting weight

**8-phase "autonomous trading brain" built (`5c088c8`) -- the big one:**
- SMC detector: FVG, Order Block, BOS/CHoCH, liquidity sweeps
- 3-state HMM regime with cross-pair consensus
- Strategy router: 11 strategies mapped to regimes (preferred/acceptable/hostile)
- Confluence scorer: 8 factors, 0-11 points, bands: 0-2=skip, 3=50%, 4-7=full, 8-11=150%
- MTF analyzer: H4 bias via EMA(8/34) + swing + premium/discount zones
- ICT 5-step model: HTF -> Sweep -> MSS -> FVG -> Entry
- ML expanded to 41 features, 15 selected, XGBoost with walk-forward
- Position manager 3-tier partial close: 30% at 1.5R, 30% at 3R, trail 40%

**Net effect:** +9,161 lines of code in one commit. The entry pipeline went from simple CVD signal detection to a 12-layer filter chain.

---

## Phase 4: ML Training Mode & Filter Loosening (Mar 12)

### Commits: `6188048` through `3c836ad`

**Commodity trading added (`6188048`):**
- XAUUSD, XAGUSD, NG-C, UKOUSDft, USOUSD added to all systems
- Position sizing fixed for commodity CFDs
- Polymarket removed entirely (illegal in Netherlands)
- Strategy router enforced as hard gate (was advisory-only)
- Correlation group limits added (max 1 per metals/energy group)
- Capital: $500 -> $2,000/trade

**1:2 R:R gate enforced (`e20a686`):**
- All trades must have reward >= 2x risk or order is rejected
- Fixed scale-in orphan bug (partial positions left hanging)

**TRAINING_MODE enabled (`39cbbaf`):**
- Single flag bypasses all 11 filter layers
- Only hard guards remain: market closed, no tick data, insufficient bars
- GLOBAL_MAX: 10 -> 20 concurrent positions
- Daily loss limit: $300 -> $9,999 (effectively disabled)
- Goal: collect 1,000+ labeled trades for ML training

**Filters loosened (`5600e7c`):**
- VOLATILE regime min_confluence: 9 -> 6 (9 was impossible to reach with 11-point max)
- Symbol filter min WR: 35% -> 25%
- Symbol cooldown: 24h -> 2h
- ICT scanner expanded to 14 instruments

**Result:** Trade frequency increased dramatically but quality collapsed. This was intentional -- ML needed data.

---

## Phase 5: Anti-Churn, SL/TP Tuning, ML Retrain (Mar 13)

### Commits: `393fa28` through `f80f6a1`

**Energy risk management added (`393fa28`):**
- Energy capital: $300 (vs $2,000 forex) -- oil ATR is 3-5x normal
- Energy SL: 2x ATR, TP: 3x ATR (wider stops)
- Max 2 oil + 1 NG positions (WTI/Brent 0.95 correlated)
- Crisis regime detection: auto-halve size
- Energy session filter: block dead zone 21:00-01:59 UTC
- 5 new energy indicators (volatility regime, seasonal, squeeze, session, momentum)

**Position manager bug fixes (`f699530`, `7eb8071`):**
- R:R rejection loop: order rejected for R:R < 2.0, retried infinitely
- RangeIndex crash in trail calculations
- Breakeven flag was blocking ATR floor trail from activating
- XAUUSD TP removed to let trailing stop handle exits (later reverted)

**Anti-churn system (`7937fe8`):**
- 15min post-trade cooldown per symbol (later reduced to 30s)
- Signal consumption marking (one bar = one trade, prevents re-firing)
- Per-symbol daily cap (8) and global daily cap (40) -- later removed
- SIGNAL_LOOKBACK reduced from 4 to 3 bars
- **SL widened: 1.2x -> 1.8x ATR** (tighter stops were causing noise exits; median trade held only 7 minutes)
- **TP widened: 2.5x -> 3.5x ATR** (maintains 2:1 R:R with more room)

**Daily caps removed (`f1e5e14`):**
- Circuit breakers + ML filter + cooldown + signal consumption already handle quality
- Daily caps were double-penalizing and blocking good setups
- "CVD (2pts) + HTF trend (2pts) = 4 IS the edge -- trade it at full size"

**Symbol cooldown reduced (`c961f21`):**
- 15 minutes -> 30 seconds (signal consumption already prevents re-firing on same bar)

**XGBoost retrained (`f80f6a1`):**
- Quality gates: minimum confluence >= 3, exclude historically destructive strategies
- Training set: 569 -> 325 quality trades
- Aggressive regularization: max_depth 5->3, reg_alpha 0.1->1.0, reg_lambda 1.0->5.0
- Walk-forward: 52.0% accuracy (above 47.6% baseline)
- Precision: 74.2%, selective recall: 46.9%
- Train/CV gap collapsed from 46pp to 18pp

---

## Phase 6: Paper Trading Launch & Sunday Disaster (Mar 14--16)

### Commits: `f8c2384` through `7b07484`

**Mar 15: Paper trading launched** with TRAINING_MODE=False and all gates active. 12 custom strategies + SCALPING enabled across 14 instruments.

**Mar 16 (Sunday night): The disaster session**
- 11 trades between 02:55--04:35 UTC (Asian session Sunday open)
- 1 win, 10 losses, -$116.65
- 9 of 11 trades had confluence score of exactly 4 (bare minimum)
- 100% of score-4 trades lost
- XAGUSD: 2 trades, -$70.75 (60% of total loss, both hit $50 MAX_LOSS ceiling in 3-5 min)
- Circuit breaker fired at ~04:05 UTC after 5 consecutive losses

**Root causes identified:**
1. Asian session Sunday open = lowest liquidity of the week
2. Confluence score 4 was too easy to reach: CVD signal always gives 2 free points + HTF bias gives 2 = automatic pass
3. Silver at Sunday open has extreme spreads + gap behavior
4. Bot had been blocked for hours, then fired 11 trades in 90 minutes

**Position manager worked correctly:**
- MFE Lock fired twice (caught $5.40 and $5.24 profits)
- Profit Protection fired twice
- MAX_LOSS fired twice on silver
- MFE Flat Exit killed 2 dead trades at 15 minutes

**Risk-based sizing implemented (`1ca56ce`):**
- Replaced `capital * leverage` with `lots = target_risk / loss_per_lot_at_SL`
- Uses MT5 tick_value for correct cross-instrument sizing
- XAGUSD no longer sized at 0.6 lots ($237K notional) -- now 0.01 lots (~$5K)
- SL stays at full ATR distance (removed SL clamping that squeezed stops)

**MT5 reconciliation added:**
- reconcile_positions() runs every 30s
- Direction 1: MT5 positions missing from DB -> create Trade records
- Direction 2: DB trades missing from MT5 -> close with deal history
- Fixed get_deal_from_ticket() to filter by position_id

**Circuit breaker tuned (`bee667d`):**
- Cooldowns: 1h -> 15m global, 30m per-symbol
- Session 1 post-mortem recommendations: confluence min 6 outside kill zones, consecutive loss size reduction
- Kill zone thresholds documented:

| Session | Time (UTC) | Min Confluence |
|---------|-----------|----------------|
| London Open | 07:00-10:00 | 5 |
| NY Open | 12:00-15:00 | 5 |
| London Close | 15:00-17:00 | 6 |
| Asian | 22:00-07:00 | 7 |
| Sunday Open | 22:00-02:00 Sun | BLOCK |

**VWAP + session levels (`7b07484`):**
- Confluence expanded: 12 -> 14 max (VWAP alignment +1, session sweep +1)
- XAGUSD confluence gate lowered to 3 (silver CVD more reliable in thin liquidity)
- 5 new MT5 API endpoints (account_info, order_check, margin calc)
- Pre-trade margin check + margin level guard (200%)

---

## Phase 7: The Brain Era (Mar 17)

### Commits: `c7d6b59` through `b6f809e`

A single day of intense development that added an enormous amount of infrastructure:

**Multi-Timeframe Structure Reader (`46f7683`):**
- market_structure.py: swing detection (HH/HL/LH/LL), BOS/CHoCH, trend phases
- zone_mapper.py: FVG and Order Block detection, proximity checks
- mtf_context.py: unified H4->H1->M15->M5 context with alignment scoring (0-10)
- structure_levels.py: SL behind swing points (not fixed ATR), TP at opposing zones
- Enforces 0.5-3.0 ATR distance band and min 2.0 R:R

**Neo4j Pattern Advisor (`46f7683`):**
- advisor.py: pre-trade graph consultation with 4 query types
- Similar setups WR, symbol+regime WR, news-risk WR, warning detection
- Weighted confidence (0-1) -> sizing modifier (0.5-1.5x)
- 5-minute cache, fails gracefully to neutral defaults

**WebSocket Real-Time Dashboard (`3e4b95e`):**
- Standalone async relay (Redis pub/sub -> browser clients)
- useWebSocket.js composable with auto-reconnect
- **Result: Quickly abandoned.** Django runs Gunicorn WSGI, no channels/ASGI support installed. The HTTP polling approach (5-60s intervals) remained.

**DOM Orderbook (`9ea1077`):**
- MT5 Level 2 data + liquidity detection
- Integrated into brain pipeline
- **Result: Limited value.** Vantage broker provides minimal DOM depth for forex CFDs.

**Autonomous Structure Scanner (`914101f`):**
- 803 lines, scan_for_entries() reads H4->H1->M15->M5
- 4 setup types: TREND_CONTINUATION, BREAKOUT, REVERSAL, RANGE_FADE
- 14-step pipeline per setup
- Ran every 30s on critical queue
- **Result: Removed on Mar 18.** Too many signals, insufficient signal quality, added complexity without improving WR.

**Claude API Intelligence (`a2ae1ae`):**
- Causal news analysis via Haiku (replaces keyword matching)
- Trade setup evaluation with LLM reasoning
- Daily performance report auto-generation
- ~$1/month on Haiku
- Stopped monitoring stack (Grafana/Prometheus/Loki) to free 538MB RAM for Neo4j

**Pi NPU Connected (`7e3e0fe`):**
- FinBERT sentiment via Hailo-10H NPU on Raspberry Pi
- 67ms sentiment inference
- Docker -> Pi routing established (ports 8000 + 11434)
- **Result: "Limited signal value at 1.5B scale" -- logs responses but doesn't override gates**

**MiroFish Intelligence (`a4c2c00`):**
- Causal chains in Neo4j: trade -> news -> regime transitions
- Trade reasoning nodes with human-readable logic

**Neo4j Temporal Decay:**
- 7-day half-life exponential decay on all advisor queries
- BRAIN_V1 trades weighted 2x vs RULE_BASED
- Setup type performance tracking
- Time-of-day performance per symbol

**ICC Detector (`3846501`):**
- H4/H1 FVG and Order Block detection (replacing noisy M15 zones)
- HTF BOS/ChoCH market structure
- Stacked POI detection (FVG+OB overlap >= 20%)
- Fibonacci golden pocket (0.618-0.650)
- Volume Profile POC via 40-bucket H4 tick_volume binning
- Confluence expanded to 17 max (3 new factors)

**24/7 Commodity Trading (`3846501`):**
- Metals and energy bypass London+NY session filter
- Rationale: geopolitical events affect commodities at all hours

**LLM moved to fire-and-forget (`3846501`):**
- Hailo NPU was adding 12-30s latency to critical path
- Moved to daemon thread, preserves logging for training data

**Dual-domain crypto expansion (`b6f809e`):**
- Kelly sizing for Lighter.xyz
- Funding rate signal, open interest, orderbook signal, trade flow, social sentiment
- Neo4j feedback loop for crypto trades
- Massive backtest data dump: 21 CSV files covering 7 symbols x 3 timeframes

**Performance claim (from FOREX_SETTINGS.md):**
> R:R improved 0.73 -> 1.49, avg loss $4.51 -> $0.82

**Total code added on Mar 17:** Approximately 15,000 lines across 50+ files.

---

## Phase 8: Brain Replacement & Simplification (Mar 18)

### Commits: `24b73a3` through `8afabf9`

The day of reckoning. After the complexity explosion of Mar 17, the codebase was radically simplified.

**Neo4j Brain Backtest Seeder (`24b73a3`):**
- Seeds 71 reference trades as StrategyPattern nodes (avg WR=63.3%)
- 35 pattern fingerprints derived from 6 months of H4 data

**The Great Replacement (`33d51bc`):**

REMOVED (2,869 lines deleted):
- `algorithms/strategy_router.py` (460 lines, 11 strategies, HMM regime mapping)
- `algorithms/confluence_scorer.py` (767 lines, 0-14 point gate)
- `macro_analyst.py` (327 lines, LLM news gating)
- `strategy_evolver.py` (1,009 lines, never used in production)

ADDED:
- `algorithms/brain_entry.py` (~220 lines, replaces 2,348-line cvd/entry.py)
  - Fetch bars -> detect signals (FVG/CVD/HTF) -> query Neo4j -> execute
  - Neo4j is the only gate: Pattern WR >= 58% + sample >= 3 -> take trade
  - No strategy router. No confluence scorer. No news gating.
  - 5-minute cadence (deliberate, not frantic)
- `graph.py`: StrategyPattern node layer with upsert/update/query/deactivate
- `intelligence/claude_analyst.py`: Haiku labels each pattern after close

**The Mega Cleanup (`c733b56`):**

REMOVED (11,268 lines deleted):
- `algorithms/cvd/entry.py` (2,348 lines -- the original 12-layer pipeline)
- `algorithms/cvd/trailing.py` (119 lines)
- `algorithms/ict_entry.py` (1,066 lines)
- `algorithms/structure_entry.py` (1,329 lines)
- `algorithms/structure_levels.py` (802 lines)
- `algorithms/mtf_analyzer.py` (237 lines)
- `algorithms/icc_detector.py` (663 lines)
- `algorithms/regime.py` (330 lines)
- `algorithms/strategy_rotator.py` (446 lines)
- `knowledge/advisor.py` (1,252 lines)
- `strategy_orchestrator.py` (441 lines)
- `ai_brain.py` (649 lines)
- `ai_brain_executor.py` (271 lines)

ADDED (3,053 lines):
- `algorithms/entry_forex.py` (345 lines) -- MTF-driven, signals from tick_consumer
- `algorithms/entry_crypto.py` (379 lines) -- CVD + structure on Lighter.xyz
- `engine/mtf_engine.py` (212 lines) -- real-time multi-timeframe bar builder
- `engine/indicators.py` (261 lines) -- clean indicator library (ADX, MACD, RSI, ATR, market structure)
- `engine/bar_builder.py` (102 lines) -- tick-to-bar aggregation
- `tools/trade_cli.py` (589 lines) -- CLI for manual trade management

**R:R Enforcement (`c733b56`, `bb51e1f`, `8afabf9`):**
- TP anchored to fill price (not FVG level) so R:R is always exactly 2:1 from entry
- min_rr=1.95 (was 2.0) to absorb floating-point rounding
- RSI(2) scalper: TP raised to 2x SL across all asset classes
  - Crypto: 1.0% SL -> 2.0% TP (was 1:1)
  - Metals: 0.8% SL -> 1.6% TP (was 1:1)
  - Forex: 0.3% SL -> 0.6% TP (was 1:1)
- Break-even WR now 33.3% (was 50% at 1:1)
- 12 CustomStrategy definitions patched in DB

**Close algorithm fixed:**
- Wrong dict keys: `'price'` -> `'close_price'`, `'time'` -> `'close_time'`
- Retry loop (4x with 1s gaps) for get_deal_from_ticket -- MT5 takes 1-3s to finalize deal history
- Division-by-zero in get_price_at_pnl when position_size_usd=0

---

## The Crypto / Lighter.xyz Side

### Architecture

Lighter.xyz is a zero-fee DEX. The integration uses a split architecture:
- **Read ops:** Pure-Python SDK from Docker (candles, orderbook, account info)
- **Write ops:** macOS native HTTP proxy on port 5555 (Go SignerClient crashes under QEMU)

### Strategy Evolution

| Date | Strategy | Parameters | Result |
|------|----------|-----------|--------|
| Mar 9 | EMA 8/21 + RSI 14/30/65 | Backtested 162 combos | 53.3% WR, +41.36%, PF 1.98 |
| Mar 9 | RSI(2) scalper | 5m candles, SL 1%, TP 0.75% | R:R 0.75:1 = needed >57% WR |
| Mar 12 | 5-strategy crypto backtesting | Grid, mean reversion, RSI scalp, momentum | System built |
| Mar 16 | Lighter signer proxy crashed | 16 signals generated, 0 executed | Critical downtime |
| Mar 17 | Kelly sizing, funding signal, OB signal | 7 new crypto modules added | Infrastructure only |
| Mar 18 | RSI(2) moved to 15m candles | SL 1.0% -> TP 2.0% (1:2 R:R) | Fix from 0.75:1 |
| Mar 18 | EMA position slots decoupled | EMA gets own 3-slot capacity | Was sharing with RSI(2) |
| Mar 18 | entry_crypto.py created | H4 ADX/MACD + H1 structure/CVD + OB filter | Clean 379-line entry |

### Current Crypto Config

- **Symbols:** BTC, ETH, SOL, AVAX, XAG
- **Sizing:** 30% of account balance per trade, max 3 open
- **Entry:** H4 trend (ADX>20 + MACD direction) AND (H1 structure OR CVD setup)
- **OB filter:** Real-time orderbook from ws_streamer, blocks extreme imbalance
- **SL:** 1.5x ATR, TP: 3.0x ATR
- **Circuit breaker:** 4 losses -> 1h pause
- **Cooldown:** 600s per symbol

### Crypto Problems

1. **Signer proxy reliability:** Runs natively on macOS, needs launchd persistence
2. **QEMU incompatibility:** Go-based SignerClient crashes under Docker QEMU emulation
3. **No live trading data yet:** Account needs funding, paused by default
4. **R:R was broken:** 0.75:1 on RSI(2) scalper required >57% WR to break even, fixed to 1:2

---

## What Worked

### 1. CVD Lack of Participants Strategy
The only consistently profitable strategy across both backtest and live data.
- **Backtest:** 626 trades, 46.3% WR, +0.273 PnL, PF 1.449
- **Live:** +$23, 46.2% WR (small sample)
- **Mechanism:** Price makes lower low but CVD makes higher low = sellers exhausted
- **Why it works:** Detects genuine exhaustion in order flow, not just pattern matching

### 2. Risk-Based Position Sizing
Replacing `capital * leverage` with `lots = target_risk / loss_per_lot_at_SL` was the single most important risk management improvement.
- Stopped XAGUSD from sizing at 0.6 lots ($237K notional)
- Uses MT5 tick_value for accurate cross-instrument sizing
- $50 hard cap per trade regardless of instrument

### 3. Circuit Breaker
Correctly fired during the Sunday disaster, limiting the loss to -$116 instead of potentially hundreds more.
- 5 consecutive losses -> 30-minute pause
- Per-symbol: 3 losses -> 15-minute pause
- Proved its value: "The circuit breaker is not the problem -- the entry quality is"

### 4. Position Manager (Exit Logic)
The phase-based exit system worked correctly throughout:
- MFE Lock caught $5+ profits within 7-8 minutes
- Profit Protection limited giveback on winning trades
- MAX_LOSS ($50 ceiling) saved silver trades from unlimited loss
- MFE Flat Exit killed dead trades at 15 minutes

### 5. Session Filtering
Backtest data unambiguously showed:
- **Best window:** 15:00-18:00 UTC (42% WR, $811 PnL, PF 1.62)
- **Worst window:** 01:00-04:00 UTC (24% WR, -$411 PnL, PF 0.68)
- London + NY overlap is where the edge lives

### 6. VWAP Filter
Backtested on XAGUSD M15: WR 36% -> 44%, PnL $856 -> $1,700, max drawdown cut in half. The VWAP filter was the single best signal quality improvement identified.

### 7. The Simplification (Mar 18)
Cutting 11,268 lines and replacing with 3,053 focused lines was the right move. The 12-layer pipeline had:
- High latency (200-500ms filter chain per signal)
- Debugging nightmare (11 strategies x 14 symbols x 8 confluence factors)
- False sense of safety (confluence score 4 passed 100% of the time anyway)

---

## What Did Not Work

### 1. Strategy Router + 11-Strategy Pool
- Built: 11 strategies mapped to 3 HMM regimes with preferred/acceptable/hostile routing
- **Problem:** Most strategies were net losers. CVD LoP was the only winner.
- **Data:** CVD Absorption: 23.8% WR, -$34. ICT BOS, ICT Market Structure, SMC Confluence, London Open Metals, Energy Trend, Oil Momentum -- all negative.
- **Deleted:** Mar 18

### 2. Confluence Scorer
- Built: 8 factors, 0-14 points (later expanded to 17)
- **Problem:** CVD signal always gives 2 free points + HTF bias gives 2 = 4 points automatically. Min gate of 4 was meaningless. 100% of score-4 trades in the Sunday session lost.
- **Deleted:** Mar 18

### 3. Strategy Evolver
- Built: Claude-powered strategy generation, backtesting, auto-promotion
- **Problem:** 1,009 lines of code, never executed a single trade in production
- **Deleted:** Mar 18

### 4. Macro Analyst (LLM News Gating)
- Built: Claude analyzes Finnhub news + geopolitics every 30 minutes
- **Problem:** Added latency, LLM responses unreliable for real-time trading decisions
- **Deleted:** Mar 18

### 5. ICT 5-Step Entry Model
- Built: HTF -> Sweep -> MSS -> FVG -> Price-at-FVG, 954 lines
- **Problem:** Too restrictive in practice. Full 5-step chain rarely completed within a trading session.
- **Deleted:** Mar 18

### 6. Structure Scanner (Autonomous Entry)
- Built: 803 lines, reads H4->H1->M15->M5, 4 setup types
- **Problem:** Generated too many signals without sufficient quality filtering. Ran every 30s on critical queue, competing with CVD entry for resources.
- **Deleted:** Mar 18

### 7. WebSocket Dashboard
- Built: Standalone async relay, Vue composable
- **Problem:** Django runs Gunicorn WSGI, no channels/ASGI support. Would require infrastructure rebuild.
- **Status:** Abandoned. HTTP polling (5-60s intervals) remained.

### 8. DOM Orderbook
- Built: MT5 Level 2 data + liquidity detection
- **Problem:** Vantage broker provides minimal DOM depth for forex CFDs. Insufficient data for meaningful analysis.
- **Status:** Code exists but provides no signal value.

### 9. Neo4j Brain as Primary Gate
- Built: Pattern matching, WR >= 58% + sample >= 3 -> take trade
- **Problem:** Without sufficient live trade data (only 71 seeded reference trades), the brain was effectively blind. Patterns too sparse for statistically significant decisions.
- **Status:** `brain_entry.py` still exists as secondary entry algorithm, but `entry_forex.py` is the primary workhorse.

### 10. Pi NPU FinBERT Sentiment
- Built: FinBERT on Hailo-10H NPU, 67ms inference
- **Problem:** "Limited signal value at 1.5B scale" -- 1.5B parameter model insufficient for nuanced financial sentiment
- **Status:** Logs responses but doesn't override trading gates

### 11. SCALPING Strategy
- **Data:** Blocked at 33.77% WR (threshold: 55%). Consistent loser.
- **Lesson:** Sub-minute scalping on a QEMU-emulated MT5 with 1-3s order latency is fundamentally uncompetitive.

### 12. MEAN_REVERSION Strategy
- **Data:** Consistent loser across all testing periods.
- **Status:** Disabled

### 13. Removing TP from XAUUSD (`96404ef`, later reverted)
- **Idea:** Let trailing stop handle exits for bigger runners
- **Problem:** Without fixed TP, R:R is undefined. Trailing stop is a backstop, not a primary exit mechanism.
- **Reverted:** TP restored to achieve designed 1:2 R:R

### 14. SL at 1.2x ATR (Mar 11 tightening, reversed Mar 13)
- Tightened after -$687 drawdown to "cut losers faster"
- **Problem:** Median trade held 7 minutes -- 1.2x ATR was within normal noise, causing premature stops
- **Fixed:** Widened back to 1.8x ATR which gives room for normal price fluctuation

---

## Backtest vs Live Comparison

### CVD Lack of Participants -- XAGUSD M15

| Metric | Backtest (24h) | Backtest (London) | Backtest (VWAP) | Live (Mar 15-17) |
|--------|---------------|-------------------|-----------------|-------------------|
| Trades | 115 | 23 | 82 | 82 (all strategies) |
| Win Rate | 35.7% | 39.1% | 43.9% | 40.2% |
| Total PnL | $855 | $300 | $1,700 | -$112 |
| Profit Factor | 1.23 | 1.43 | 1.74 | n/a |
| Max Drawdown | $844 | $300 | $238 | n/a |
| Max Consec Loss | 12 | 6 | 4 | n/a |
| Avg Win | $111 | $111 | $111 | n/a |
| Avg Loss | -$50 | -$50 | -$50 | n/a |

**Key observations:**
1. Live WR (40.2%) is between 24h backtest (35.7%) and VWAP-filtered (43.9%) -- plausible
2. Live PnL negative despite similar WR due to: spread costs, slippage, circuit breaker downtime, and Sunday session losses
3. VWAP filter dramatically improves quality: 44% WR vs 36%, max drawdown cut from $844 to $238
4. London+VWAP too restrictive: only 13 trades, PF 0.99 (break-even)

### Parameter Sensitivity (XAGUSD M15)

| SL/TP Config | Trades | WR | PnL | PF | MaxDD |
|-------------|--------|-----|------|-----|-------|
| 1.2/2.4 (tight) | 199 | 42% | $2,650 | 1.46 | $1,000 |
| 1.5/3.0 | 151 | 34% | $250 | 1.05 | $1,250 |
| **1.8/3.6 (current)** | **118** | **37%** | **$700** | **1.19** | **$900** |
| 2.0/4.0 (energy) | 108 | 41% | $1,200 | 1.38 | $400 |
| 2.5/5.0 (very wide) | 81 | 41% | $900 | 1.38 | $550 |

**Note:** 1.2/2.4 looks best in backtest but was horrible live (7-minute median hold time, noise exits). The backtest doesn't model spread/slippage which disproportionately hurts tight stops. The 2.0/4.0 config shows better live characteristics with lower drawdown.

### Time Window Analysis

**Best hours (XAGUSD M15, all 24h):**

| Hour UTC | WR | PnL | Interpretation |
|----------|-----|-----|----------------|
| 17:00 | 70% | $628 | NY session, high liquidity |
| 14:00 | 75% | $283 | NY open |
| 11:00 | 67% | $172 | London session |
| 20:00 | 60% | $233 | US evening, trending moves |

**Worst hours:**

| Hour UTC | WR | PnL | Interpretation |
|----------|-----|-----|----------------|
| 03:00 | 0% | -$450 | Dead zone, no flow |
| 12:00 | 0% | -$250 | London close transition |
| 15:00 | 0% | -$200 | Choppy overlap |

**Conclusion:** The data overwhelmingly supports the current session filter (London 07-10, NY 13-17). The bot should never trade 00:00-06:00 UTC.

---

## Current State of the Codebase

### Forex Entry Pipeline (as of Mar 18)

```
tick_streamer (1s poll)
  -> Redis pub/sub
  -> tick_consumer (builds live M5/M15/H1 bars via mtf_engine)
  -> evaluates ADX + MACD + RSI + structure + FVG/sweep
  -> caches signal to Redis: mtf_signal:{symbol}

entry_forex.py (Celery beat every 60s, OR direct trigger from tick_consumer)
  -> reads mtf_signal:{symbol} from cache
  -> session filter (London 07-10, NY 13-17)
  -> per-symbol daily loss gate ($150)
  -> floating PnL gate (-$50)
  -> position limit (8 max)
  -> circuit breaker (5 losses -> 30min)
  -> risk-based sizing (target_risk / loss_per_lot_at_SL)
  -> hard lot cap per category
  -> TP anchored to fill price (always exactly 2:1 R:R from entry)
  -> send_market_order with min_rr=1.95
```

### Crypto Entry Pipeline

```
entry_crypto.py (Celery beat every 60s)
  -> H4 candles from Lighter.xyz API
  -> H4 trend: ADX > 20 + MACD direction + RSI not extreme
  -> H1 structure: HH/HL (bullish) or LH/LL (bearish)
  -> H1 CVD: Lack of Participants or Absorption
  -> Real-time orderbook imbalance filter (Redis DB2)
  -> place_market_order_usd via signer proxy
  -> OCO SL/TP on-chain
```

### Active Celery Tasks

| Task | Queue | Interval | Purpose |
|------|-------|----------|---------|
| run_forex_entry | default | 60s | Primary forex entry |
| run_quant_trailing_stop | critical | 2s | Position management |
| run_quant_close | critical | 15s | Detect closed positions |
| run_position_reconciliation | critical | 30s | MT5 <-> DB sync |
| run_crypto_entry | default | 60s | Lighter.xyz crypto entry |
| run_lighter_exit | default | 15s | Crypto position management |
| run_lighter_rsi_scalper | default | 30s | RSI(2) mean reversion |
| run_lighter_reconcile | default | 60s | Crypto position sync |
| run_lighter_entry | default | 60s | EMA crossover crypto |
| run_lighter_grid | default | 60s | Grid trading |
| run_lighter_mean_reversion | default | 300s | Mean reversion crypto |
| run_lighter_cvd | default | 60s | CVD crypto entry |
| run_lighter_momentum | default | 60s | Momentum crypto entry |

### Files That Matter (Current)

| File | Lines | Purpose |
|------|-------|---------|
| `entry_forex.py` | 351 | Primary forex entry algorithm |
| `entry_crypto.py` | 380 | Primary crypto entry algorithm |
| `brain_entry.py` | 328 | Neo4j brain entry (secondary) |
| `position_manager.py` | ~450 | 6-phase exit management |
| `close/close.py` | ~300 | Trade closure detection + recording |
| `engine/mtf_engine.py` | 212 | Real-time multi-timeframe bars |
| `engine/indicators.py` | 261 | Clean indicator library |
| `lighter/rsi_scalper.py` | ~300 | RSI(2) crypto scalper |
| `lighter/client.py` | ~350 | Lighter.xyz API wrapper |
| `knowledge/graph.py` | ~400 | Neo4j pattern storage |

### Files Deleted on Mar 18

| File | Lines | Why Deleted |
|------|-------|-------------|
| `cvd/entry.py` | 2,348 | Replaced by entry_forex.py (345 lines) |
| `knowledge/advisor.py` | 1,252 | Over-engineered Neo4j advisor |
| `structure_entry.py` | 1,329 | Autonomous scanner, too noisy |
| `ict_entry.py` | 1,066 | ICT 5-step model, too restrictive |
| `structure_levels.py` | 802 | Structure-based SL/TP |
| `confluence_scorer.py` | 767 | 14-point gate, gave false confidence |
| `icc_detector.py` | 663 | H4/H1 institutional confluence |
| `ai_brain.py` | 649 | Claude API brain v2 |
| `strategy_router.py` | 460 | 11-strategy HMM routing |
| `strategy_orchestrator.py` | 441 | Regime-aware sizing |
| `strategy_rotator.py` | 446 | Auto-rotation logic |
| `regime.py` | 330 | HMM regime wrapper |
| `ai_brain_executor.py` | 271 | Automated brain commands |
| `mtf_analyzer.py` | 237 | Multi-timeframe analyzer |
| `cvd/trailing.py` | 119 | Legacy trailing stop |

**Total deleted:** ~11,200 lines
**Total added:** ~3,050 lines
**Net reduction:** ~8,150 lines

---

## Key Lessons Learned

### 1. Complexity is the Enemy of Profitability
The 12-layer entry pipeline with 11 strategies, HMM regimes, confluence scoring, and strategy routing produced **worse results** than a simple FVG + CVD + session filter. Every layer added latency, potential bugs, and false confidence.

### 2. One Good Strategy > Ten Mediocre Ones
CVD Lack of Participants was the only profitable strategy. Every other strategy was a net loser. The "diversification" through 11 strategies actually diluted the one real edge.

### 3. Backtests Lie About Tight Stops
SL at 1.2x ATR looked great in backtests ($2,650 PnL, 42% WR) but was terrible live because:
- Backtests don't model spread (2-5 pips on XAGUSD)
- Backtests don't model slippage
- Median hold time was 7 minutes -- tight stops get triggered by normal noise

### 4. Risk-Based Sizing is Non-Negotiable
The switch from `capital * leverage` to `lots = target_risk / loss_per_lot_at_SL` immediately fixed the silver blow-up risk. Without it, XAGUSD was taking $237K notional positions.

### 5. Session Filtering is the Cheapest Edge
00:00-06:00 UTC is a consistent money loser across all instruments. Blocking these hours costs nothing and saves real money. The Sunday disaster could have been entirely prevented.

### 6. The Position Manager is the Unsung Hero
It worked correctly from day one. MFE Lock, Profit Protection, MAX_LOSS, and Flat Trade Exit all fired appropriately. The problem was always entry quality, never exit management.

### 7. Circuit Breakers Must Be Short
Initial 1-hour cooldown was too long for an algo bot (it's not a human who needs to calm down). Progressive reduction: 1h -> 15m -> 10m -> 5m. Current: 30 minutes (a compromise).

### 8. LLMs are Not (Yet) Trading Signals
Claude Haiku, FinBERT on NPU, and the LLM scorer all failed to provide actionable trading signals. They work for:
- Pattern labeling (post-hoc)
- News categorization
- Performance reports
They do NOT work for:
- Real-time entry/exit decisions
- Predicting price direction

### 9. Build for Deletion
The codebase went through a complete architecture cycle in 11 days:
- Simple (Mar 7) -> Complex (Mar 11-17) -> Simple again (Mar 18)
- The final architecture is better BECAUSE of the exploration, not despite it
- Every deleted module taught something about what doesn't work

### 10. R:R is Everything
At sub-50% win rates (which is where CVD divergence lives), the R:R ratio determines profitability:
- 1:1 R:R needs >50% WR to profit
- 0.75:1 R:R needs >57% WR (the RSI(2) scalper mistake)
- 1:2 R:R needs only >33% WR
- The system's 40% WR is profitable at 1:2 R:R but loses money at 1:1

---

## Strategy Performance Scorecard

### Final Verdict (as of Mar 18, 2026)

| Strategy | WR | PnL | Status | Verdict |
|----------|-----|------|--------|---------|
| CVD Lack of Participants | 46.2% | +$23 | Active (forex only) | **WINNER** -- only profitable strategy |
| CVD Absorption | 23.8% | -$34 | Disabled | Loser -- false signals in trending markets |
| CVD Extremes Scanner | n/a | negative | Disabled | Loser |
| ICT BOS Continuation | n/a | negative | Disabled + deleted | Over-engineered, too restrictive |
| ICT Market Structure | n/a | negative | Disabled + deleted | Same |
| SMC Confluence | n/a | negative | Disabled + deleted | Same |
| London Open Metals | n/a | negative | Disabled | Poor timing |
| Energy Trend Follow | n/a | negative | Disabled | Oil too volatile for trend following |
| Oil Time-Series Momentum | n/a | negative | Disabled | Academic paper != live results |
| EMA Momentum M15 | mixed | ~break-even | Disabled | Marginal |
| Bollinger Mean Rev M5 | <30% WR | negative | Disabled | Consistent loser |
| SCALPING | 33.8% | negative | Disabled | Impossible with 1-3s order latency |
| STRUCTURE_AUTONOMOUS | n/a | not tested | Deleted | Too noisy |
| RSI(2) Scalper (crypto) | ~45% | pending | Active | R:R fixed to 1:2, needs live data |
| EMA 8/21 (crypto) | 53.3% | +41% (backtest) | Active | Best backtest result, needs live |

### Risk Parameter Evolution

| Parameter | Mar 9 | Mar 11 (pre-crash) | Mar 11 (post-crash) | Mar 13 | Mar 16 | Mar 18 (current) |
|-----------|-------|---------------------|---------------------|--------|--------|-------------------|
| Capital/trade | $5,000 | $5,000 | $500 | $2,000 | risk-based | risk-based ($50 cap) |
| SL (ATR mult) | 1.5 | 1.5 | 1.2 | 1.8 | 1.8 | 1.8 |
| TP (ATR mult) | 2.5 | 2.5 | 2.5 | 3.5 | 3.6 | 3.6 |
| Max open | 10 | 10 | 5 | 5 | 5 | 8 |
| Confluence min | none | none | none | 4 | 3-6 | none (Neo4j) |
| Session filter | none | 07-21 UTC | 07-17, block 09 | 07-17 | 07-17 | London+NY only |
| Circuit breaker | none | none | 5 losses/1h | 5/1h | 5/15m | 5/30m |
| Daily halt | none | $75 | $300 | $300 | $9,999 | none (per-symbol $150) |

---

*Analysis based on 85 git commits from `e34a31f` (initial commit) through `8afabf9` (Mar 18, 2026). All code diffs examined. All parameter values verified from source.*

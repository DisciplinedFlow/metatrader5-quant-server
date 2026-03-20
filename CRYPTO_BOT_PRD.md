# Lighter.xyz Crypto Bot — PRD & Phased Rebuild Plan

## Problem Statement

Two weeks of development produced a bot with 6 entry algorithms, 8 intelligence layers, and sophisticated exit management — but **39% WR and -$8.51 PnL**. The codebase has solid infrastructure (API client, reconciler, exit phases, ML pipeline) but the strategy layer was built ad-hoc without validation gates, resulting in:

1. **Fake metrics** — reconciler deleted losses, dashboard showed 75% WR when exchange showed 39%
2. **Fragmented sizing** — 5 different position sizing formulas across 6 strategies
3. **No backtest-first discipline** — strategies deployed live without proving edge
4. **Re-entry loops** — positions hit SL, bot re-enters immediately, bleeds account
5. **Only XAU profitable** (54.5% WR, +$1.78) — SOL, BTC, ETH all net losers

## What We Have (Working Infrastructure)

| Component | Status | Notes |
|-----------|--------|-------|
| Lighter API client | Working | Read (async) + write (proxy), candles/OB/trades |
| Signer proxy | Working | macOS native, launchd plist available |
| Position reconciler | Fixed today | Records closes with PnL + vanish cooldown |
| Exit algorithm (5 phases) | Working | Breakeven → trailing → fib → profit protection → time exit |
| Order book imbalance | Working | Via ws_streamer → Redis |
| Trade flow / whale detection | Working | From Lighter recent trades |
| Funding rate signals | Working | Z-score contrarian |
| CVD calculator | Working | Binance proxy (note: PAXG ≠ XAU dynamics) |
| Confluence scorer | Working | 8-factor, 0-9 scale |
| Liquidation detector | Working | 3x baseline spike detection |
| Fibonacci TP targets | Working | ZigZag + extension levels |
| Session/symbol sizing | Working | UTC-hour + per-symbol multipliers |
| ML feature pipeline | Working | Records at entry, appends outcome at exit → JSONL |
| CryptoPosition model | Working | Unique constraint, proper close tracking |
| Dashboard (Vue 3) | Working | History, positions, strategies, ML page |
| Backtest engine | Exists | Needs update to match current strategy logic |

## What We Know (Proven Facts)

| Fact | Source | Implication |
|------|--------|-------------|
| XAU: 54.5% WR, +$1.78 | Exchange API | Gold trends well, EMA signals work |
| SOL: 27.3% WR, -$4.47 | Exchange API | Crypto chops, generic signals fail |
| BTC: 0% WR, -$3.23 | Exchange API | Remove from all strategies |
| ETH: 20% WR, -$3.00 | Exchange API | Remove from all strategies |
| 1:2 R:R needs 33% WR to break even | Math | Current 39% WR should be profitable but SOL churn kills it |
| Trades lasting 30+ min win at 73-80% | Forex audit | Don't cut early |
| Best hours: 14:00-18:00 UTC | Forex audit | London-NY overlap |
| Fees: 0.028% taker | Lighter docs | ~$0.04 on $127 position, significant on small wins |

## Design Principles

1. **Backtest before deploy** — No strategy goes live without >50% WR on 6-month historical data
2. **One change at a time** — Each phase adds ONE thing, validates, then moves on
3. **Exchange is source of truth** — PnL comes from exchange API, never from DB estimates
4. **Fail-safe by default** — Every intelligence layer is advisory (adjusts size), never blocks
5. **Unified sizing** — One formula: `risk_usd / sl_distance × multipliers`
6. **Daily reconciliation** — Automatic exchange-DB sync with proper close recording

---

## Phase 0: Foundation Cleanup (No Strategy Changes)
**Goal:** Reliable infrastructure with accurate data. Zero trading.

### 0.1 — Fix exit algorithm scheduling
- [ ] Add `run_lighter_exit` to Celery beat schedule (every 15s, critical queue)
- [ ] Add `run_lighter_reconcile` to Celery beat schedule (every 60s, default queue)
- [ ] Verify both tasks execute and log properly

### 0.2 — Exchange sync endpoint
- [ ] Fix proxy `/trades` endpoint to return paginated fill history
- [ ] Add `/v1/crypto/sync/` Django endpoint that fetches exchange fills and updates DB
- [ ] Dashboard "Sync" button calls this endpoint

### 0.3 — Unified position sizing module
- [ ] Create `lighter/sizing.py` with single `calculate_position_usd(symbol, sl_pct, strategy)` function
- [ ] Parameters: `RISK_PER_TRADE_USD` (single value), session mult, symbol mult, combined
- [ ] All 6 entry algorithms import from this module (replace inline sizing)
- [ ] Unit test: given known inputs, output matches expected USD

### 0.4 — Remove dead strategies
- [ ] Delete `grid.py` (disabled, exceeds OCO quota)
- [ ] Delete BTC/ETH from ALL symbol lists (already done in config, verify everywhere)
- [ ] Remove dead GBPUSD entries (0% WR)
- [ ] Clean up any remaining Neo4j/news references

### Validation Gate
- [ ] `docker compose up` — no errors in celery logs
- [ ] Exit algorithm processes open positions every 15s
- [ ] Reconciler runs every 60s, caches collateral
- [ ] No trades placed (bot paused)

---

## Phase 1: XAU-Only Live Validation
**Goal:** Prove the infrastructure works with the ONE profitable symbol.

### 1.1 — XAU-only configuration
- [ ] Set `LIGHTER_PAIRS = ['XAU']` in config
- [ ] Disable SOL, AVAX, LINK, DOGE from ALL entry algorithm symbol lists
- [ ] Set `LIGHTER_MAX_POSITIONS = 1`
- [ ] Keep `LIGHTER_LEVERAGE = 15`

### 1.2 — Strategy selection: EMA crossover only
- [ ] Disable RSI scalper, CVD entry, momentum entry, mean reversion for this phase
- [ ] Only `entry.py` EMA crossover active (the signal that produced XAU wins)
- [ ] SL/TP: 1.5% / 3% (current metals config, 1:2 R:R)

### 1.3 — Exchange-verified tracking
- [ ] After each trade closes, compare DB PnL with exchange fill PnL
- [ ] Log discrepancy if > $0.01 difference
- [ ] Dashboard shows exchange-sourced PnL (not DB-estimated)

### 1.4 — Run for 48 hours
- [ ] Unpause bot
- [ ] Monitor: target 5+ trades, >50% WR, positive PnL
- [ ] If negative after 10 trades: pause and reassess

### Validation Gate
- [ ] DB PnL matches exchange PnL within $0.05
- [ ] No re-entry loops (vanish cooldown working)
- [ ] No orphaned exchange positions
- [ ] WR ≥ 50% on XAU after 10+ trades

---

## Phase 2: Backtest Framework
**Goal:** Ability to test ANY signal against historical data before deploying live.

### 2.1 — Historical data collector
- [ ] Script to download 6 months of Lighter candles (1m, 5m, 15m, 1h) per symbol
- [ ] Store as Parquet files in `backtest/data/`
- [ ] Symbols: SOL, XAU, AVAX, DOGE (active pairs)

### 2.2 — Unified backtest engine
- [ ] Input: signal function + SL/TP config + symbol + timeframe
- [ ] Output: trades list, WR, PnL, profit factor, max drawdown, Sharpe
- [ ] Simulates: slippage (0.05%), fees (0.028%), spread
- [ ] No look-ahead bias (rolling window only)

### 2.3 — Validate current strategies
- [ ] Run EMA crossover on 6 months XAU → expect >50% WR
- [ ] Run EMA crossover on 6 months SOL → expect <40% WR (confirms removal)
- [ ] Run RSI(2) on 6 months XAU and SOL
- [ ] Run mean reversion on 6 months XAU and SOL
- [ ] Document results in `BACKTEST_RESULTS.md`

### 2.4 — Auto-disable gate
- [ ] Strategy must show >50% WR AND profit factor >1.2 on backtest to be enabled
- [ ] Store results in `CryptoBacktestResult` model
- [ ] Dashboard strategies page shows backtest WR next to live WR

### Validation Gate
- [ ] Backtest engine produces consistent results (run twice, same output)
- [ ] Historical WR for XAU EMA matches live WR (within 10%)
- [ ] At least 3 strategy-symbol combinations tested

---

## Phase 3: Signal Improvement
**Goal:** Find signals that work on more than just XAU.

### 3.1 — Orderbook-based entry (OB data available for SOL, XAU)
- [ ] Backtest: OB imbalance > 60% as entry filter on top of EMA
- [ ] Compare WR with and without OB filter
- [ ] If +5% WR improvement, deploy to Phase 1 XAU config

### 3.2 — Funding rate as primary signal
- [ ] Backtest: Extreme funding (|z| > 2) as standalone entry
- [ ] Mean reversion play: short when longs overlevered, long when shorts overlevered
- [ ] Test on SOL (most volatile funding)

### 3.3 — CVD divergence refinement
- [ ] Backtest CVD LoP (the only strategy that was +$23 in the forex bot)
- [ ] Test on SOL using Binance data (accurate for SOL, unlike PAXG proxy for XAU)
- [ ] If >55% WR, add as second active strategy

### 3.4 — Multi-factor confluence entry
- [ ] Combine: EMA trend + OB imbalance + funding rate + CVD
- [ ] Require 3/4 agreement to enter
- [ ] Backtest on SOL and XAU

### Validation Gate
- [ ] At least one new signal achieves >55% WR on backtest
- [ ] Backtest profit factor > 1.3
- [ ] Paper trade for 24h before live deployment

---

## Phase 4: Multi-Symbol Expansion
**Goal:** Scale to 2-3 profitable symbols.

### 4.1 — Add validated signals to SOL
- [ ] Only signals that passed Phase 3 backtest validation
- [ ] Start with 50% position size (symbol_mult = 0.5)
- [ ] Run 48h, compare live WR vs backtest WR

### 4.2 — Evaluate AVAX and DOGE
- [ ] Backtest winning signals on AVAX and DOGE
- [ ] If >50% WR, add with 50% position size
- [ ] If <50% WR, keep disabled

### 4.3 — Per-strategy position budgets
- [ ] Each strategy gets independent position limit
- [ ] EMA crossover: 1 position
- [ ] RSI scalper: 1 position
- [ ] CVD: 1 position
- [ ] Total max: 2 (OCO limit)

### Validation Gate
- [ ] 2+ symbols profitable over 7 days
- [ ] Total WR > 50%
- [ ] No single symbol losing > $2 in a week
- [ ] Exchange PnL matches DB PnL

---

## Phase 5: ML Integration
**Goal:** Use collected trade data to improve signal quality.

### 5.1 — Training data audit
- [ ] Verify 100+ clean trades in JSONL (from Phases 1-4)
- [ ] Feature completeness check (no null fields)
- [ ] Label quality check (won/lost matches exchange PnL)

### 5.2 — Feature importance analysis
- [ ] Train XGBoost on collected features
- [ ] Identify top 5 predictive features
- [ ] If accuracy > 60%, deploy as pre-entry filter

### 5.3 — ML gate deployment
- [ ] ML model scores each potential entry 0-1
- [ ] Threshold: > 0.5 to proceed (not blocking, just sizing)
- [ ] Below threshold: 50% position size
- [ ] Above threshold: 100% position size

### Validation Gate
- [ ] ML model accuracy > 60% on holdout set
- [ ] A/B test: ML-filtered vs unfiltered WR difference > 5%
- [ ] No significant increase in missed winning trades

---

## Success Criteria

| Phase | Metric | Target |
|-------|--------|--------|
| 0 | Zero errors in logs | 100% |
| 1 | XAU WR after 10 trades | > 50% |
| 1 | DB ↔ exchange PnL match | < $0.05 diff |
| 2 | Backtest consistency | Same result on repeated runs |
| 3 | New signal backtest WR | > 55% |
| 4 | Multi-symbol 7-day PnL | > $0 |
| 5 | ML accuracy on holdout | > 60% |

## Timeline Estimate

| Phase | Scope | Dependencies |
|-------|-------|-------------|
| Phase 0 | Infrastructure cleanup | None |
| Phase 1 | XAU-only validation | Phase 0 |
| Phase 2 | Backtest framework | Phase 0 |
| Phase 3 | Signal R&D | Phase 2 |
| Phase 4 | Multi-symbol | Phase 1 + Phase 3 |
| Phase 5 | ML integration | Phase 4 (100+ trades) |

Phases 1 and 2 can run in parallel (XAU trades live while backtesting offline).

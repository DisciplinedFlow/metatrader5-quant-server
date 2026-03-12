# ML Learning Phase Plan

**Created:** 2026-03-12
**Status:** Phase 1 active (LEARNING_MODE=True)

---

## Current State (Mar 12)

| Metric | Value | Target |
|--------|-------|--------|
| Total closed trades | 178 | 500+ |
| Labeled trades (with features) | 75 | 300+ |
| Training accuracy | 97.3% | <85% (less overfit) |
| Cross-validated accuracy | 38.7% | 55-65% |
| Walk-forward accuracy | 43.5% | 55%+ |
| Model version | v15 (LightGBM) | v30+ |
| Win rate | 51.5% | 55%+ |

**Problem:** 75 training samples = massive overfitting. The model memorizes trades instead of learning patterns. Cross-validation at 38.7% means it's barely better than random when it sees new data.

## Architecture: What Each ML Component Does

```
Signal found (CVD/EMA/Bollinger)
    |
    v
[Strategy Router] -- Hard-coded rules: regime -> strategy list
    |                 TRENDING -> CVD Lack of Participants, EMA Ribbon, etc.
    |                 RANGING  -> CVD Absorption, Bollinger, etc.
    |                 (NOT learned — rule-based)
    v
[XGBoost/LightGBM Gate Filter] -- Scores signal 0.0-1.0
    |                              Uses 15 features (RSI, ATR, session, etc.)
    |                              ACCEPT if score >= 0.40
    |                              Retrains every 30 min automatically
    v
[Confluence Scorer] -- 0-11 points from 8 factors
    |                   HTF bias, sweep, CVD, kill zone, FVG, OB, regime, displacement
    |                   Router sets min threshold per regime
    v
Trade placed or rejected
```

**Key insight:** The ML gate filter improves automatically with more data. The strategy router does NOT learn — it uses fixed regime-to-strategy mappings.

## The Plan: Three Phases

### Phase 1: Wild Learning (NOW - Mar 19)

**Goal:** Collect 500+ trades across all symbols, strategies, and regimes.

**What changed:**
- `LEARNING_MODE = True` in `cvd/entry.py`
- Circuit breakers: bypassed (were locking best symbols after small losses)
- Symbol filter (24h ban): bypassed (was banning EURUSD on 10-trade sample)
- All cooldowns cleared from Redis

**What's still protecting the account:**
- $50 hard SL clamp (broker-level, no software timing gaps)
- MAX_OPEN = 5 positions
- Daily halt at $300
- R:R validation (min 2:1)
- Confluence scoring (still runs)
- ML gate filter (still runs, improves as data grows)
- Pre-trade margin safety check (new)
- Position manager trailing stops
- Worst case: 5 x $50 = $250/cycle on $99k balance (0.25%)

**Expected outcome:**
- 50-80 trades/day at current rate
- 500+ trades by Mar 19
- ML retrains every 30 min, model version should reach v30+

### Phase 2: Evaluate & Tighten (Mar 19-20)

**Goal:** Analyze the week's data and re-enable smart protection.

**Steps:**
1. Check ML cross-validated accuracy — should be 55%+ with 300+ labeled trades
2. Analyze per-strategy-regime performance:
   - Which strategies actually work in TRENDING vs RANGING?
   - Which symbols are consistently profitable?
   - Which time sessions produce the best trades?
3. Set `LEARNING_MODE = False` to re-enable circuit breakers
4. Tune thresholds based on real data:
   - `CIRCUIT_BREAKER_COOLDOWN_HOURS`: probably 0.25 (15 min) instead of 1
   - `SYMBOL_FILTER_COOLDOWN_HOURS`: probably 4 instead of 24
   - `SYMBOL_FILTER_LOOKBACK`: probably 15 instead of 10
   - Router min_confluence for RANGING: possibly 4 instead of 5

### Phase 3: Strategy Selector Model (Mar 20+, only if Phase 2 data supports it)

**Goal:** Replace the hard-coded strategy router with a learned model.

**Prerequisites:**
- 50+ trades per strategy-regime combination (at least 1500+ total trades)
- Clear performance differences between strategies in different regimes

**Design:**
- Input: current market features (regime, volatility, session, RSI, etc.)
- Output: expected PnL ranking of each strategy
- Train on: all closed trades with strategy + regime + features + PnL

**This is NOT needed yet.** The gate filter improving from 38% to 55%+ CV accuracy will have a larger impact than a strategy selector with insufficient data.

## Key Constants Reference

```python
# Entry gate (cvd/entry.py)
LEARNING_MODE = True                    # Bypasses circuit breakers & symbol filter
CIRCUIT_BREAKER_SYMBOL_LOSSES = 3       # Consecutive losses -> pause (bypassed)
CIRCUIT_BREAKER_GLOBAL_LOSSES = 5       # Global consecutive losses (bypassed)
CIRCUIT_BREAKER_COOLDOWN_HOURS = 1      # Cooldown duration (bypassed)
SYMBOL_FILTER_LOOKBACK = 10             # Trades checked for symbol filter (bypassed)
SYMBOL_FILTER_MIN_WR = 0.35            # Min win rate (bypassed)
SYMBOL_FILTER_COOLDOWN_HOURS = 24       # Symbol ban duration (bypassed)
MAX_LOSS_PER_TRADE = 50.0              # Hard SL clamp (ACTIVE)
CAPITAL_PER_TRADE = 2000               # Base capital per trade
MAX_OPEN = 5                           # Max simultaneous positions

# Position manager (position_manager.py)
MAX_LOSS_PER_TRADE_USD = 50.0          # Hard dollar ceiling (ACTIVE)
MFE_LOCK_MINUTES = 15                  # Lock profit within 15 min
FLAT_TRADE_MINUTES = 15                # Kill flat trades at 15 min
PROFIT_PROTECT_GIVEBACK = 0.40         # Close if giving back 40%+ from peak
TIME_EXIT_MINUTES = 30                 # Close stale positions after 30 min

# ML retrainer (runs every 30 min via Celery beat)
# Retrains when enough new labeled trades accumulate
# Walk-forward validation prevents deploying worse models

# Trailing stop interval: 5 seconds (settings.py)
```

## What "Good" Looks Like After Phase 1

| Metric | Current | After 500+ trades |
|--------|---------|-------------------|
| CV accuracy | 38.7% | 55-65% |
| Walk-forward | 43.5% | 55%+ |
| Training accuracy | 97.3% | 75-85% (less overfit) |
| Feature importance | noisy | stable top 5 |
| Win rate | 51.5% | 53-58% (ML filtering bad trades) |
| Avg trade PnL | -$0.67 | $2-5+ (cutting losers better) |

If CV accuracy doesn't improve past 50% with 500 trades, the features themselves need work — not more data.

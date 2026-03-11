# XAUBot-AI Architecture Analysis & Reference Guide

**Date:** 2026-03-11
**Purpose:** Deep-dive reference for adopting patterns into our MT5 Django/Celery trading pipeline
**Repositories analyzed:**
- [xaubot-ai](https://github.com/GifariKemal/xaubot-ai) -- XGBoost + HMM + SMC gold trading bot
- [SURGE-WSI](https://github.com/GifariKemal/SURGE-WSI) -- Kalman + HMM + ICT/SMC forex system
- [smart-money-concepts](https://github.com/joshyattridge/smart-money-concepts) -- Python SMC indicator library

---

## Table of Contents

1. [XAUBot-AI Complete Architecture](#1-xaubot-ai-complete-architecture)
2. [The 37+ Engineered Features](#2-the-37-engineered-features)
3. [The 14 Entry Filters](#3-the-14-entry-filters)
4. [HMM Regime Detection](#4-hmm-regime-detection)
5. [XGBoost Signal Predictor](#5-xgboost-signal-predictor)
6. [SMC Analyzer (Polars)](#6-smc-analyzer-polars)
7. [Kelly Criterion Position Sizing](#7-kelly-criterion-position-sizing)
8. [Risk Management Rules](#8-risk-management-rules)
9. [Position Manager & Exit System](#9-position-manager--exit-system)
10. [Dynamic Confidence System](#10-dynamic-confidence-system)
11. [Auto-Retraining Pipeline](#11-auto-retraining-pipeline)
12. [SURGE-WSI Architecture](#12-surge-wsi-architecture)
13. [smartmoneyconcepts API Reference](#13-smartmoneyconcepts-api-reference)
14. [Patterns to Adopt for Our MT5 Bot](#14-patterns-to-adopt-for-our-mt5-bot)
15. [Architecture Comparison: XAUBot vs Our System](#15-architecture-comparison-xaubot-vs-our-system)

---

## 1. XAUBot-AI Complete Architecture

### System Overview

XAUBot-AI is a monolithic Python trading bot for XAUUSD (gold) on MetaTrader 5. It combines three AI subsystems:

1. **Smart Money Concepts (SMC)** -- Primary signal generator. Detects institutional footprints: Order Blocks, Fair Value Gaps, Break of Structure, Change of Character, Liquidity Zones
2. **XGBoost ML** -- Confirmation gate. Binary classifier (UP/DOWN next bar) with calibrated confidence. Can block SMC signals but cannot initiate trades alone
3. **Hidden Markov Model (HMM)** -- Regime modulator. 3-state volatility classifier that adjusts position sizing and aggression

**Design philosophy:** SMC = PRIMARY (entry/SL/TP source), ML = CONFIRMATION (can block, never initiate), HMM = MODULATOR (adjusts sizing/aggression).

### Backtest Results (Jan 2025 - Feb 2026)

| Metric | Value |
|--------|-------|
| Total trades | 654 |
| Win rate | 63.9% |
| Net profit | $4,189.52 |
| Profit factor | 2.64 |
| Max drawdown | 2.2% |
| Sharpe ratio | 4.83 |

### Component Map

```
TradingBot.__init__()
+-- MT5Connector           -- Broker connection + auto-reconnect (3 attempts, exponential backoff)
+-- SMCAnalyzer            -- 6 SMC concepts via Polars (smc_polars.py)
+-- FeatureEngineer        -- 37 base technical indicators (feature_eng.py)
+-- MLV2FeatureEngineer    -- 23 advanced features: H1 multi-TF, continuous SMC, regime, price action
+-- TradingModelV2         -- XGBoost binary classifier (ml_model.py)
+-- MarketRegimeDetector   -- HMM 3-state regime (regime_detector.py)
+-- FlashCrashDetector     -- >2.5% move/min emergency guard
+-- RiskEngine             -- Half-Kelly lot sizing + circuit breaker (risk_engine.py)
+-- SmartRiskManager       -- 4-mode capital protection (smart_risk_manager.py)
+-- SmartPositionManager   -- 12 exit conditions, ATR trailing (position_manager.py)
+-- SessionFilter          -- WIB timezone session windows (session_filter.py)
+-- DynamicConfidence      -- Adaptive ML threshold 60-85% (dynamic_confidence.py)
+-- KellyPositionScaler    -- Half-Kelly with exit confidence integration
+-- FuzzyExitLogic         -- 30-rule fuzzy controller for exit confidence
+-- KalmanFilter           -- Constant-velocity profit smoother
+-- AutoTrainer            -- Daily model retraining + rollback (auto_trainer.py)
+-- TelegramNotifier       -- 11-type real-time alerts
+-- TradeLogger            -- PostgreSQL + CSV dual storage
+-- FilterConfigManager    -- Runtime filter toggle via JSON
```

### Data Pipeline Flow

```
MT5 Raw OHLCV (200 bars, M15 timeframe)
    |
    +-- FeatureEngineer.calculate_all()        -> 37 base indicators (Polars)
    +-- SMCAnalyzer.calculate_all()            -> 6 SMC patterns (swing, FVG, OB, BOS, CHoCH, liquidity)
    +-- MLV2FeatureEngineer.add_all_v2()       -> 23 V2 features (H1 context, continuous SMC, regime, candles)
    +-- RegimeDetector.detect()                -> 3-state HMM classification
         |
         v
    XGBoost.predict()                          -> BUY/SELL/HOLD + confidence (0-1)
         |
         v
    DynamicConfidence.calculate()              -> Adaptive threshold (60-85%)
         |
         v
    14-Gate Entry Filter Pipeline              -> Sequential hard/soft blocks
         |
         v
    RiskEngine.calculate_position_size()       -> Half-Kelly lot (0.01-0.03)
         |
         v
    MT5 Order Execution                        -> Market order with broker SL/TP
         |
         v
    Position Monitoring (every ~10 sec)        -> 12 exit conditions evaluated
```

### Main Loop Architecture

The bot runs on a **candle-based event system**, not time-based polling:

```
while running:
    if new_M15_candle_formed():
        _trading_iteration()     # Full analysis: features + SMC + ML + entry logic
    else:
        _position_check_only()   # Cached data, just check exits

    write_dashboard_status()     # JSON for web dashboard
    poll_telegram_commands()     # Bidirectional Telegram
    sleep(5)                     # 5-second poll interval
```

**Performance:** Full analysis takes ~50ms. Inter-candle position check takes ~21ms. ML predictions cached between candles.

---

## 2. The 37+ Engineered Features

### Base Features (37) -- feature_eng.py

All computed in pure Polars (vectorized, no loops, <100ms for 5000 bars).

#### Technical Indicators (12 features)

| # | Feature | Formula |
|---|---------|---------|
| 1 | `rsi` | Wilder's RSI(14): 100 - (100 / (1 + RS)) |
| 2 | `atr` | True Range with Wilder's smoothing(14) |
| 3 | `atr_percent` | (ATR / Close) * 100 |
| 4 | `macd` | EMA(12) - EMA(26) |
| 5 | `macd_signal` | EMA(MACD, span=9) |
| 6 | `macd_histogram` | MACD - MACD_signal |
| 7 | `bb_middle` | SMA(20) |
| 8 | `bb_upper` | SMA(20) + 2.0 * StdDev(20) |
| 9 | `bb_lower` | SMA(20) - 2.0 * StdDev(20) |
| 10 | `bb_width` | (BB_upper - BB_lower) / BB_middle |
| 11 | `bb_percent_b` | (Close - BB_lower) / (BB_upper - BB_lower) |
| 12 | `ema_9`, `ema_21` | Exponential moving averages |

#### EMA Crossover Signals (2 features)

| # | Feature | Formula |
|---|---------|---------|
| 13 | `ema_cross_bull` | Binary: EMA_9 crosses above EMA_21 |
| 14 | `ema_cross_bear` | Binary: EMA_9 crosses below EMA_21 |

#### Volume Features (9 features)

| # | Feature | Formula |
|---|---------|---------|
| 15 | `volume_sma` | Rolling mean of volume(20) |
| 16 | `volume_ratio` | Volume / volume_sma |
| 17 | `volume_increasing` | Binary: volume > prev volume |
| 18 | `high_volume` | Binary: volume_ratio > 1.5 |
| 19 | `buy_volume` | Volume when close > open |
| 20 | `sell_volume` | Volume when close < open |
| 21 | `ofi_pseudo` | (buy_vol - sell_vol) / (buy_vol + sell_vol) |
| 22 | `ofi_trend` | Rolling mean of OFI(20) |
| 23 | `ofi_divergence` | ofi_pseudo - ofi_trend |

#### Advanced Volume (2 features)

| # | Feature | Formula |
|---|---------|---------|
| 24 | `volume_momentum` | (volume_ratio / prev_volume_ratio) - 1 |
| 25 | `toxicity` | abs(volume_momentum) + 2*abs(ofi_divergence) |

#### Returns & Momentum (4 features)

| # | Feature | Formula |
|---|---------|---------|
| 26 | `returns_1` | (Close / prev_close) - 1 |
| 27 | `returns_5` | (Close / close_5_ago) - 1 |
| 28 | `returns_20` | (Close / close_20_ago) - 1 |
| 29 | `log_returns` | ln(Close / prev_close) |

#### Price Position (3 features)

| # | Feature | Formula |
|---|---------|---------|
| 30 | `price_position` | (Close - Low) / (High - Low) |
| 31 | `dist_from_sma_20` | (Close / SMA_20) - 1 |
| 32 | `normalized_range` | (High - Low) / Close |

#### Volatility (2 features)

| # | Feature | Formula |
|---|---------|---------|
| 33 | `volatility_20` | Rolling std of log_returns(20) |
| 34 | `avg_normalized_range` | Rolling mean of normalized_range(14) |

#### Lag Features (4 features)

| # | Feature | Formula |
|---|---------|---------|
| 35 | `close_lag_1` | Close shifted by 1 bar |
| 36 | `close_lag_2` | Close shifted by 2 bars |
| 37 | `close_lag_3` | Close shifted by 3 bars |
| 38 | `close_lag_5` | Close shifted by 5 bars |

#### Trend Analysis (4 features)

| # | Feature | Formula |
|---|---------|---------|
| 39 | `higher_high` | Binary: current high > prev high |
| 40 | `lower_low` | Binary: current low > prev low |
| 41 | `hh_count_5` | Rolling sum of higher_high(5) |
| 42 | `ll_count_5` | Rolling sum of lower_low(5) |

#### Time Features (4 features, optional)

| # | Feature | Formula |
|---|---------|---------|
| 43 | `hour` | Hour of day |
| 44 | `weekday` | Day of week |
| 45 | `london_session` | Binary: 08:00-16:00 UTC |
| 46 | `ny_session` | Binary: 13:00-21:00 UTC |

### V2 Features (23) -- ml_v2_feature_eng.py

Added on top of base features for a total of ~60 features.

#### H1 Multi-Timeframe (8 features)

Uses `join_asof` (backward join) to prevent lookahead bias.

| Feature | Description |
|---------|-------------|
| `h1_market_structure` | Directional trend from H1 (1/-1/0) |
| `h1_ema20_distance` | Distance from H1 EMA(20), normalized by ATR |
| `h1_trend_strength` | Count of BOS signals on H1 |
| `h1_swing_proximity` | Distance to nearest H1 swing level |
| `h1_fvg_active` | Binary: price inside H1 fair value gap |
| `h1_ob_proximity` | Distance to H1 order block center |
| `h1_atr_ratio` | H1 ATR / M15 ATR |
| `h1_rsi` | RSI from H1 timeframe |

#### Continuous SMC (7 features)

Converts discrete SMC binary signals to continuous values for better gradient information.

| Feature | Description |
|---------|-------------|
| `fvg_gap_size_atr` | FVG width normalized by ATR |
| `fvg_age_bars` | Bars since last FVG formation |
| `ob_width_atr` | Order block width / ATR |
| `ob_distance_atr` | Distance to OB center / ATR |
| `bos_recency` | Bars since last BOS |
| `confluence_score` | Count of SMC signals in 10-bar window |
| `swing_distance_atr` | Distance to swing level / ATR |

#### Regime Conditioning (4 features)

| Feature | Description |
|---------|-------------|
| `regime_duration_bars` | Consecutive bars in current regime |
| `regime_transition_prob` | 1 / duration (change likelihood) |
| `volatility_zscore` | (ATR - mean50) / std50 |
| `crisis_proximity` | ATR ratio vs 50-bar mean threshold |

#### Price Action (4 features)

| Feature | Description |
|---------|-------------|
| `wick_ratio` | Combined wick length / candle range |
| `body_ratio` | Body size / candle range |
| `gap_from_prev_close` | Open gap from prior close / ATR |
| `consecutive_direction` | Count of candles in same direction |

---

## 3. The 14 Entry Filters

The entry pipeline is a sequential chain of hard gates. Each filter can block the trade entirely (except H1 bias which only adjusts confidence). Execution order matters -- early filters are cheapest to evaluate.

| # | Filter | Type | Logic | Block Behavior |
|---|--------|------|-------|----------------|
| 1 | **Flash Crash Guard** | Hard block | >2.5% price move in 1 minute | Closes ALL positions, activates circuit breaker |
| 2 | **Regime Filter** | Hard block | HMM state = CRISIS or SLEEP | Blocks new entries |
| 3 | **Risk Check** | Hard block | Daily P&L < -3% or total < -10% | Stops all trading |
| 4 | **Session Filter** | Hard block | Dead zone (00:00-06:00 WIB), Friday >23:00 | Blocks entries |
| 5 | **H1 Multi-TF Bias** | Soft adjust | H1 EMA(20) alignment with signal | +5% if aligned, -10% if opposed. NEVER blocks |
| 6 | **Time-of-Hour Filter** | Hard block | Blocks "whipsaw hours" (9am, 9pm WIB transitions). Night safety spread check | Blocks entries during transitions |
| 7 | **Cooldown Timer** | Hard block | 150-second minimum between trades | Prevents overtrading |
| 8 | **SMC Signal Generation** | Required | FVG or OB + BOS or CHoCH must produce BUY/SELL | No signal = no trade |
| 9 | **ML Prediction** | Conditional | XGBoost confidence > dynamic threshold (60-85%) | Can block if <threshold or >65% opposite |
| 10 | **Signal Combination** | Required | SMC + ML agreement or SMC solo with >=55% confidence | Merges confidence scores |
| 11 | **Position Limit** | Hard block | Maximum 2 concurrent open positions | Blocks if at limit |
| 12 | **Smart Risk Gate** | Hard block | Trading mode not STOPPED or PROTECTED | Blocks in recovery modes |
| 13 | **Lot Size Calculator** | Required | Half-Kelly with session/regime multipliers, result > 0 | Crisis regime = 0 lot = blocked |
| 14 | **Trade Execution** | Final | MT5 market order with emergency broker SL | Executes if all above pass |

### Signal Combination Logic (Filter #10)

```
IF SMC signal exists with confidence >= 55%:
    IF ML agrees:
        final_confidence = average(smc_confidence, ml_confidence)  # Boosted
    ELSE IF ML disagrees:
        final_confidence = smc_confidence  # SMC wins, ML ignored

    IF H1 aligned:
        final_confidence += 5%
    ELSE IF H1 opposed:
        final_confidence -= 10%  # Never blocks, just reduces
```

### Filter Config Runtime Toggles

All 11 configurable filters can be toggled at runtime via `data/filter_config.json`. The FilterConfigManager provides `is_enabled()`, `set_enabled()`, and `update_all()` APIs. Dashboard reads this for filter status display.

---

## 4. HMM Regime Detection

### Implementation: regime_detector.py

**Model:** hmmlearn.GaussianHMM with diagonal covariance matrix

**States:** 3 by default (configurable 4th state):
- **LOW_VOLATILITY** -- Normal trading, 1.0x position multiplier
- **MEDIUM_VOLATILITY** -- Normal trading, 1.0x multiplier
- **HIGH_VOLATILITY** -- Reduced trading, 0.5x multiplier
- **CRISIS** (optional) -- No trading, 0.0x multiplier

### HMM Feature Vector (8 features)

| Feature | Purpose |
|---------|---------|
| Log returns | Price momentum signal |
| Volatility (20-period rolling std) | Short-term volatility |
| Volatility (100-period rolling std) | Long-term volatility context |
| Range-to-ATR ratio | Normalized intrabar range |
| Trend strength | Distance between 9/21 SMAs / ATR |
| RSI deviation from 50 | Momentum extremity |
| Autocorrelation proxy | 20-period lagged returns correlation |
| ATR z-score | Volatility regime normalized over 100 bars |

All features are StandardScaler-normalized before training.

### Training Strategy

**Multi-seed fitting:**
- Attempts 5 different random seeds
- Selects best model using penalized scoring:
  - State population imbalance (<3%) -> -10,000 penalty
  - Phantom states (covariance >100) -> penalty
  - Low diagonal stability (<0.70) -> penalty
  - Uneven distributions (0.03-0.15 range) -> penalty

**Initialization:** 90% stay diagonal-dominant transition matrix (0.90 on diagonal, 0.10 distributed off-diagonal) to prevent alternating-state local minima.

### State Classification

States mapped by sorting on `volatility_20` feature mean:
- Lowest mean -> LOW_VOLATILITY
- Middle mean -> MEDIUM_VOLATILITY
- Highest mean -> HIGH_VOLATILITY

### Post-Processing

**Min-Duration Smoothing:** Eliminates regime segments shorter than 5 bars via multi-pass convergence (max 10 passes). Replaces short segments with preceding regime.

**ATR Fallback Override:** Compares current ATR against 200-candle percentiles:
- ATR >= P90 -> forces HIGH_VOLATILITY if HMM said LOW
- ATR >= P75 -> forces MEDIUM_VOLATILITY if HMM said LOW
- ATR <= P25 -> forces LOW_VOLATILITY if HMM said HIGH

### Retraining

- Default retrain frequency: every 20 candles
- Minimum 200 samples required
- Version-compatible model loading with v1/v2 fallback
- Lookback: 500 bars

---

## 5. XGBoost Signal Predictor

### Implementation: ml_model.py

**Model:** XGBoost binary classifier (binary:logistic objective)

**Regularization-heavy parameters (anti-overfitting):**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| max_depth | 3 | Shallow trees (typical is 6) |
| learning_rate | 0.05 | Conservative learning |
| n_estimators | 50 | Few rounds to prevent overfitting |
| alpha (L1) | 1.0 | Feature selection pressure |
| lambda (L2) | 5.0 | Strong weight shrinkage |
| min_child_weight | 10 | Requires significant sample support |
| subsample | 0.7 | Row bagging |
| colsample_bytree | 0.6 | Column bagging |
| gamma | 1.0 | Minimum split improvement |

### Training Process

1. Walk-forward protection with **50-bar gap** between train/test to break autocorrelation
2. 70/30 train-test split
3. Early stopping: 10-round patience on AUC metric
4. NaN/infinity handling via `np.nan_to_num()`
5. Feature name validation between training and inference

### Prediction Output

Returns `PredictionResult`:
- **Signal:** BUY (probability > threshold), SELL (1-probability > threshold), or HOLD
- **Confidence threshold:** 0.65 default, dynamically adjusted 0.60-0.85
- **Feature importance:** Dictionary of feature contributions

### Model as Confirmation Gate

XGBoost cannot initiate trades. Its role:
- ML agrees with SMC -> confidence boosted (averaged)
- ML disagrees with SMC -> SMC confidence used unchanged
- ML confidence >65% opposite direction -> can block entry
- ML confidence <55% -> force minimum lot (0.01)

---

## 6. SMC Analyzer (Polars)

### Implementation: smc_polars.py

Pure Polars vectorized implementation (no pandas, no loops except for stateful pattern detection).

### 6 SMC Concepts Detected

#### 1. Swing Points (Fractal High/Low)
- Window: `swing_length=5` bars
- Detection occurs `swing_length` bars AFTER confirmation (no lookahead)
- Output: `swing_high`, `swing_low`, `swing_high_level`, `swing_low_level`, `last_swing_high`, `last_swing_low`

#### 2. Fair Value Gaps (FVG)
- Bullish: Current Low > Previous-2 High (gap up)
- Bearish: Current High < Previous-2 Low (gap down)
- Minimum gap: 2.0 pips (`fvg_min_gap_pips`)
- Detected on THIRD candle (no lookahead)
- Output: `is_fvg_bull`, `is_fvg_bear`, `fvg_top`, `fvg_bottom`, `fvg_mid`, `fvg_signal`

#### 3. Order Blocks (OB)
- Bullish OB: Last bearish candle before bullish impulse creating swing low
- Bearish OB: Last bullish candle before bearish impulse creating swing high
- Lookback: `ob_lookback=10` periods
- Validation: OB is valid if close is above/below OB level (structure broken)
- Output: `ob`, `ob_top`, `ob_bottom`, `ob_mitigated`

#### 4. Break of Structure (BOS)
- Structure break IN the direction of trend (continuation signal)
- Detected by comparing closes against last swing levels
- Output: `bos` (1 for bullish, -1 for bearish)

#### 5. Change of Character (CHoCH)
- Structure break AGAINST the trend (reversal signal)
- Detected with stateful trend tracking
- Output: `choch` (1 for bullish, -1 for bearish)

#### 6. Liquidity Zones
- Coefficient of variation (std/mean) < 0.001 = clustered prices
- Buy Side Liquidity (BSL): Equal highs clusters
- Sell Side Liquidity (SSL): Equal lows clusters
- Output: `bsl_level`, `ssl_level`, `liquidity_sweep`

### Signal Generation

**Valid signal requires:** Structure break (BOS or CHoCH) + Zone (FVG or OB)

**Confidence scoring (additive):**

| Component | Points |
|-----------|--------|
| Base confidence | 0.40 |
| Structure aligned | +0.15 |
| BOS or CHoCH present | +0.12 |
| FVG present | +0.08 |
| Order Block present | +0.10 |
| Trend strength | +0.10 |
| Fresh level (not mitigated) | +0.05 |
| **Maximum cap** | **0.85** |

**Risk/reward:** Fixed 1:1.5 ratio. Stop loss: 1.5-2x ATR distance.

---

## 7. Kelly Criterion Position Sizing

### Implementation: kelly_position_scaler.py + risk_engine.py

### Formula

```
Full Kelly: f* = (p * b - q) / b
    where p = win rate
          q = 1 - p (loss probability)
          b = win/loss ratio (avg_win / avg_loss)
```

### Safety Constraints

1. Kelly fraction capped at **25% maximum**
2. **Half-Kelly** applied: kelly * 0.5 (conservative)
3. Risk per trade limited by config (1% small account, 0.5% medium)
4. Lot constrained to [min_lot, max_lot] range

### Dynamic Adjustments

**Exit confidence integration:** When exit signals are strong, the system reduces the estimated win probability:
```python
p_continue_win = base_win_rate * (1 - exit_confidence * 0.7)
```

**Kelly-based exit decisions:**
- Kelly hold fraction < 0.25 -> Full exit
- Kelly hold fraction 0.25-0.70 -> Partial exit
- Kelly hold fraction > 0.70 -> Hold position

**Default parameters:**
- Base win rate: 0.55
- Avg winning trade: $8.00
- Avg losing trade: $4.00
- Kelly fraction multiplier: 0.5 (half-Kelly)

### Lot Sizing Pipeline

```
1. Calculate Half-Kelly fraction
2. Cap at config limit (1% max risk)
3. Apply regime multiplier (1.0x normal, 0.5x high vol, 0.0x crisis)
4. risk_amount = balance * risk_percent
5. lot = risk_amount / (SL_pips * pip_value)
6. Round to lot_step
7. Apply ML confidence boost: >= 80% confidence -> 2x lot (max 0.02)
8. Apply ML penalty: < 65% -> force 0.01 only
9. Apply session multiplier: Golden Time 1.2x, Sydney 0.5x, Night 0.5x
10. Constrain to [0.01, 0.03] final range
```

---

## 8. Risk Management Rules

### 4-Layer Protection Hierarchy

```
Layer 1: Broker Stop Loss
+-- ATR-based (1.5x ATR minimum, ~10+ pips)
+-- Sent WITH the order (protects even if bot crashes)
+-- Max loss: ~$50-80 per trade

Layer 2: Software Smart Exit
+-- 12 exit conditions evaluated every ~10 seconds
+-- Typically closes BEFORE broker SL triggers
+-- Target: loss <= $25

Layer 3: Emergency Stop Loss
+-- Max 2% account loss per trade ($100 on $5K)
+-- Separate backup SL if software fails

Layer 4: Circuit Breaker
+-- Daily loss >= 3% ($150) = stop trading today
+-- Total loss >= 10% ($500) = permanent stop
+-- Flash crash >2.5%/min = close ALL positions
```

### Daily Loss Limits

| Parameter | Small Account ($5K) | Medium Account ($50K) |
|-----------|---------------------|----------------------|
| Risk per trade | 1% ($50) | 0.5% ($250) |
| Daily loss limit | 3% ($150) | 2% ($1,000) |
| Total loss limit | 10% ($500) | 10% ($5,000) |
| Max positions | 2-3 | 5 |
| Lot range | 0.01-0.03 | 0.01-2.0 |
| Leverage | 1:100 | 1:30 |

### 4 Trading Modes

| Mode | Trigger | Lot | Max Positions | Recovery |
|------|---------|-----|---------------|----------|
| NORMAL | All green | 0.01-0.03 | 2-3 | -- |
| RECOVERY | 3 consecutive losses | 0.01 | 1 | Auto after 1 win |
| PROTECTED | >=80% daily limit used | 0.01 | 1 | Auto next day |
| STOPPED | Daily or total limit hit | 0.00 | 0 | Manual or next day |

### Smart Risk Manager: ATR-Based Dynamic Scaling

All thresholds adapt to current volatility:
```python
atr_ratio = current_atr / baseline_atr  # ~18.0 for XAUUSD M15
scaling_multiplier = clamp(atr_ratio, 0.3, 1.5)

effective_max_loss = base_max_loss * scaling_multiplier
tp_targets = base_tp * scaling_multiplier
```

### Capital Protection Hierarchy (Dollar Amounts for $5K)

| Level | Amount | Purpose |
|-------|--------|---------|
| Software S/L per trade | ~$25 (0.5%) | Normal exit target |
| Emergency broker S/L | ~$100 (2%) | If software fails |
| Daily loss limit | $250 (5%) | Circuit breaker trigger |
| Total loss limit | $500 (10%) | Permanent stop |

### Grace Period System (Dynamic)

Before applying hard stops, positions get breathing room:
- In profit: 6-12 minutes (regime-based)
- Small loss (<$2): Full grace period
- Fast loss (>$0.30/sec): 3-4 minutes only
- Slow loss: 7+ minutes for recovery
- Never-profitable: 2 minutes max

### State Persistence

Risk state saved atomically to `data/risk_state.txt` with backup. Crash-safe: writes to temp file, then atomic rename.

---

## 9. Position Manager & Exit System

### Implementation: position_manager.py + smart_risk_manager.py

### 12 Exit Conditions (Priority Order)

| # | Condition | Trigger | Action |
|---|-----------|---------|--------|
| 1 | **Market Close** | Near daily/weekend close | Close if profitable, cut if risky |
| 2 | **Regime Danger** | HMM = CRISIS/HIGH_VOL + profit > $50 | Close to protect profit |
| 3 | **Signal Reversal** | ML opposite signal > 75% confidence + profit > $37.50 | Close on reversal |
| 4 | **Peak Drawdown** | Drawback from peak > 30% when peak > $50 | Protect profits |
| 5 | **High Urgency** | Urgency score >= 8 + profit > $50 | Close immediately |
| 6 | **Breakeven Lock** | Pip profit >= breakeven threshold | SL to entry + 0.5x ATR buffer |
| 7 | **Trailing Stop** | Pip profit >= trail_start | Trail by step distance |
| 8 | **Impulse Tighten** | Last candle range > 1.5x ATR | Tighten trailing distance |
| 9 | **Early Exit** | $5-$15 profit + ML reversal >= 65% | Close early |
| 10 | **Stall Detection** | 10+ bars, no significant movement | Close |
| 11 | **Time-Based Exit** | 4h no growth / 6h low profit / 8h final | Close |
| 12 | **Default Hold** | No condition met | Continue holding |

### ATR-Adaptive Trailing Configuration

| Parameter | Fixed Mode | ATR-Adaptive Mode |
|-----------|-----------|-------------------|
| Breakeven | 15 pips | ATR * 2.0 |
| Trail start | 25 pips | ATR * 4.0 |
| Trail step | 10 pips | ATR * 3.0 |

### Smart Take Profit Tiers

| Trigger | Amount | Condition |
|---------|--------|-----------|
| Hard TP | >= 1.20x ATR | Always close |
| Secure TP | >= 0.60x ATR | + momentum declining |
| Peak protection | Peak > $50 | + 40% drawdown from peak |
| Momentum fade | -- | Velocity positive -> negative for 3+ reads |

### Market Close Handler

- Daily close: 05:00 WIB (5pm EST)
- Weekend close: Saturday 05:00 WIB
- Profit + near close -> close to secure gains
- Loss + recoverable -> hold over close
- Loss + weekend -> cut 50% to avoid gap risk

### Fuzzy Exit Logic (30 Rules)

**6 Input Variables** with membership functions:
1. Velocity (crashing, declining, stalling, growing, accelerating)
2. Acceleration (strong_negative through strong_positive)
3. Profit retention (collapsed to peak)
4. RSI (oversold to overbought)
5. Time in trade (very_short to very_long)
6. Profit level (none to exceeded)

**Output:** Single crisp value (0.0-1.0) via center-of-gravity defuzzification.
- > 0.75 -> Exit signal
- 0.50-0.75 -> Warning
- < 0.50 -> Hold

### Kalman Filter for Profit Smoothing

Constant-velocity model tracking [profit, velocity]:
- Process noise: 0.01 (suppresses brief spikes)
- Measurement noise: 0.25 (accounts for XAUUSD bid/ask spread)
- Responds to genuine reversals in 2-3 samples (10-15 seconds)
- Outputs: filtered profit, filtered velocity, calculated acceleration

---

## 10. Dynamic Confidence System

### Implementation: dynamic_confidence.py

The system adjusts the ML confidence threshold required for entry based on current market conditions, scored on a 0-100 scale.

### Scoring Components

| Factor | Best Case | Worst Case |
|--------|-----------|------------|
| Session | +20 (London-NY Overlap) | -30 (Market closed) |
| Regime | +15 (Medium volatility) | -25 (Crisis) |
| Volatility | +10 (Medium) | -10 (Extreme) |
| Trend clarity | +10 (Trending) | -5 (Ranging) |
| SMC confluence | +10 (Present) | +0 (Absent) |
| ML alignment | +5 (>=70%) | +0 (<60%) |

**Base score: 50 points. Range: -10 to 120 (clamped to 0-100).**

### Quality Brackets -> Threshold Mapping

| Score | Quality | ML Threshold |
|-------|---------|-------------|
| >= 80 | EXCELLENT | 60% (easiest entry) |
| 65-79 | GOOD | 65% |
| 50-64 | MODERATE | 70% |
| 35-49 | POOR | 80% |
| < 35 | AVOID | 85% (near-impossible entry) |

This means in excellent conditions (London-NY overlap + medium volatility + trending + SMC confluence), entries are easier. In poor conditions (Asia session + high vol + ranging), the system demands near-certainty from the ML model.

---

## 11. Auto-Retraining Pipeline

### Implementation: auto_trainer.py

### Trigger Conditions

| Trigger | Details |
|---------|---------|
| Daily market close | 05:00 WIB (weekdays), 30-minute window |
| Weekend deep training | Same time Saturday/Sunday (more data, more rounds) |
| Manual fallback | 24+ hours since last training |
| Initial training | First run, no models exist |
| Low AUC detection | Test AUC drops below 0.65 + 4h since last train |

**Minimum cooldown:** 20 hours between retraining attempts.

### Training Pipeline

1. **Backup:** Archive current models (5-backup retention, auto-cleanup)
2. **Data fetch:** 15,000 bars daily / 20,000 bars weekend
3. **Feature engineering:** 37 base + 23 V2 features + SMC indicators
4. **HMM training:** 3-state Gaussian HMM with multi-seed fitting
5. **XGBoost training:** 50 rounds daily / 80 rounds weekend, early stopping with 5-round patience
6. **Evaluation:** AUC threshold check (>=0.65 to accept, <0.60 triggers rollback)
7. **Persistence:** Save model, record to PostgreSQL (fallback: text file)
8. **Notification:** Telegram report with AUC scores

### Walk-Forward Validation

- 70/30 train/test split with 50-bar gap (anti-autocorrelation leakage)
- Metrics tracked: train AUC, test AUC, train accuracy, test accuracy
- Rollback to previous model if test AUC < 0.60

---

## 12. SURGE-WSI Architecture

### Overview

SURGE-WSI is a 6-layer forex trading system (GBPUSD primary) combining Kalman Filter noise reduction, HMM regime detection, and ICT/SMC concepts.

### 6 Processing Layers

```
Layer 1: Data Pipeline
+-- MT5 OHLCV collection (H4 higher TF, M5 entry)
+-- TimescaleDB time-series storage
+-- Redis real-time cache

Layer 2: Regime + Time Detection
+-- Multi-scale Kalman Filter (fast/medium/slow price smoothing)
+-- HMM 3-state regime (BULLISH/BEARISH/SIDEWAYS)
+-- Kill Zone validation (London 08-12, NY 13-17, Overlap 15-17 UTC)

Layer 3: POI Detection
+-- Order Blocks (via smartmoneyconcepts library)
+-- Fair Value Gaps (via smartmoneyconcepts library)
+-- BOS/CHoCH structural breaks

Layer 4: Entry Trigger
+-- Rejection candle confirmation (wick > 50% of body)
+-- Liquidity sweep detection (price penetrates prior swing by 2+ pips)
+-- Market Structure Shift (MSS) via BOS on lower TF
+-- Quality scoring (minimum 75 points)

Layer 5: Risk Management
+-- Quality-based sizing: high (>80%) = 1.5%, medium (60-80%) = 1.0%, low = 0.5%
+-- Daily loss limit: $80 (0.8% of $10K)
+-- Max SL: 10 pips
+-- Max per-trade loss: 0.1% of balance
+-- December skip (historically 12.5% WR)

Layer 6: Smart Exit
+-- TP1: 1:1 R:R -> Close 50%, move SL to breakeven
+-- TP2: 2:1 R:R -> Close 30%
+-- TP3: 3:1 R:R -> Close remaining 20% or trail
+-- ATR-based trailing (10-50 pip range)
+-- Regime flip -> forced exit
```

### SURGE-WSI vs XAUBot Key Differences

| Aspect | XAUBot-AI | SURGE-WSI |
|--------|-----------|-----------|
| Primary instrument | XAUUSD (gold) | GBPUSD (forex) |
| ML model | XGBoost (60 features) | None (pure SMC + Kalman) |
| Signal source | SMC + ML confirmation | SMC only + rejection candle |
| Regime detection | HMM 8 features | HMM 2 features (returns + volatility) |
| Price smoothing | Kalman on profit trajectory | Kalman on price data (triple-scale) |
| Confidence system | Dynamic 60-85% threshold | Fixed quality score >= 75 |
| Position sizing | Half-Kelly + regime | Quality-based fixed % |
| Max positions | 2 | 1 |
| Partial exits | None (all-or-nothing smart exit) | TP1/TP2/TP3 partials |
| Data storage | PostgreSQL + CSV | TimescaleDB + Redis |
| "Zero losing months" | Not explicitly targeted | Core design goal |

### SURGE-WSI Kalman Filter (Triple-Scale)

Three parallel filters with different sensitivities:

| Filter | Process Noise | Measurement Noise | Purpose |
|--------|--------------|-------------------|---------|
| Fast | 0.05 | 0.05 | Short-term signal |
| Medium | 0.01 | 0.1 | Trend following |
| Slow | 0.001 | 0.2 | Long-term direction |

State model: Constant acceleration (3D: price, velocity, acceleration). Outputs: smoothed price, velocity, acceleration, residual, uncertainty.

### SURGE-WSI HMM Configuration

- 3 states: BULLISH, BEARISH, SIDEWAYS
- 50-bar lookback, 100 minimum samples
- 0.6 minimum probability threshold
- Features: returns + 5-period rolling std volatility
- Retrains every 200 updates
- Fallback: linear regression if HMM unavailable

### SURGE-WSI Entry Requirements (ALL must be met)

1. Within London or NY Kill Zone
2. HMM regime = BULLISH or BEARISH (not SIDEWAYS), probability > 60%
3. Price at valid POI (Order Block or FVG)
4. Rejection candle confirmation (wick > 50% of body)
5. Quality score >= 75 points

---

## 13. smartmoneyconcepts API Reference

### Installation

```bash
pip install smartmoneyconcepts
```

### Usage

```python
from smartmoneyconcepts import smc
```

**Input requirement:** Pandas DataFrame with lowercase OHLC columns: `["open", "high", "low", "close"]` and optionally `["volume"]`.

### Complete Function Reference

#### 1. smc.fvg(ohlc, join_consecutive=False)

**Fair Value Gap detection.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| join_consecutive | bool | False | Merge consecutive FVGs into one |

| Return Column | Values | Description |
|---------------|--------|-------------|
| FVG | 1, -1, NaN | 1=bullish, -1=bearish |
| Top | float | Upper boundary of gap |
| Bottom | float | Lower boundary of gap |
| MitigatedIndex | int/NaN | Index where gap was filled |

**Logic:** Bullish FVG when candle[i-2].high < candle[i].low. Bearish when candle[i-2].low > candle[i].high.

---

#### 2. smc.swing_highs_lows(ohlc, swing_length=50)

**Swing point detection using fractal method.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| swing_length | int | 50 | Candles before AND after to compare |

| Return Column | Values | Description |
|---------------|--------|-------------|
| HighLow | 1, -1, NaN | 1=swing high, -1=swing low |
| Level | float | Price level of swing point |

**Note:** With `swing_length=50`, you need 100 candles before the first swing can be detected. For M15 trading, use `swing_length=5-10` for faster signals.

---

#### 3. smc.bos_choch(ohlc, swing_highs_lows, close_break=True)

**Break of Structure and Change of Character.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| swing_highs_lows | DataFrame | required | Output from swing_highs_lows() |
| close_break | bool | True | Use close for break validation |

| Return Column | Values | Description |
|---------------|--------|-------------|
| BOS | 1, -1, NaN | 1=bullish BOS, -1=bearish |
| CHOCH | 1, -1, NaN | 1=bullish CHoCH, -1=bearish |
| Level | float | Price level of structure break |
| BrokenIndex | int | Candle index where break occurred |

**Logic:** BOS = break in trend direction (continuation). CHoCH = break against trend (reversal).

---

#### 4. smc.ob(ohlc, swing_highs_lows, close_mitigation=False)

**Order Block detection.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| swing_highs_lows | DataFrame | required | Output from swing_highs_lows() |
| close_mitigation | bool | False | Use close for invalidation |

| Return Column | Values | Description |
|---------------|--------|-------------|
| OB | 1, -1, NaN | 1=bullish, -1=bearish |
| Top | float | Upper boundary |
| Bottom | float | Lower boundary |
| OBVolume | float | Sum of current + 2 prev candle volumes |
| Percentage | float | Strength: min(highVol,lowVol)/max(highVol,lowVol) |
| MitigatedIndex | int/NaN | Index where OB was invalidated |

---

#### 5. smc.liquidity(ohlc, swing_highs_lows, range_percent=0.01)

**Liquidity zone detection (equal highs/lows clusters).**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| swing_highs_lows | DataFrame | required | Output from swing_highs_lows() |
| range_percent | float | 0.01 | Price proximity threshold (1%) |

| Return Column | Values | Description |
|---------------|--------|-------------|
| Liquidity | 1, -1, NaN | 1=buy-side, -1=sell-side |
| Level | float | Price level of cluster |
| End | int | Index of final cluster point |
| Swept | int/NaN | Index when liquidity was taken |

---

#### 6. smc.previous_high_low(ohlc, time_frame="1D")

**Previous period high and low levels.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| time_frame | str | "1D" | Period: 15m, 1H, 4H, 1D, 1W, 1M |

| Return Column | Values | Description |
|---------------|--------|-------------|
| PreviousHigh | float | Prior period's high |
| PreviousLow | float | Prior period's low |
| BrokenHigh | 0, 1 | 1 when price exceeds previous high |
| BrokenLow | 0, 1 | 1 when price breaks below previous low |

---

#### 7. smc.sessions(ohlc, session, start_time="", end_time="", time_zone="UTC")

**Trading session markers.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| session | str | required | Session name (see below) |
| start_time | str | "" | Custom start "HH:MM" |
| end_time | str | "" | Custom end "HH:MM" |
| time_zone | str | "UTC" | Timezone "UTC+0" format |

**Predefined sessions:** Sydney, Tokyo, London, New York, Asian Kill Zone, London Open Kill Zone, New York Kill Zone, London Close Kill Zone, Custom.

| Return Column | Values | Description |
|---------------|--------|-------------|
| Active | 0, 1 | 1 if candle within session |
| High | float | Session's highest price |
| Low | float | Session's lowest price |

---

#### 8. smc.retracements(ohlc, swing_highs_lows)

**Fibonacci-style retracement calculation.**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| ohlc | DataFrame | required | OHLC price data |
| swing_highs_lows | DataFrame | required | Output from swing_highs_lows() |

| Return Column | Values | Description |
|---------------|--------|-------------|
| Direction | 1, -1, NaN | 1=bullish, -1=bearish |
| CurrentRetracement% | float | Current pullback % from swing |
| DeepestRetracement% | float | Maximum retracement achieved |

### Integration Pattern for Django/Celery

```python
import pandas as pd
from smartmoneyconcepts import smc

# Prepare OHLC DataFrame (lowercase columns required)
df = pd.DataFrame({
    'open': [...], 'high': [...], 'low': [...], 'close': [...], 'volume': [...]
})

# Step 1: Detect swing structure (use smaller swing_length for M15)
swing_hl = smc.swing_highs_lows(df, swing_length=7)

# Step 2: Detect market structure breaks
structure = smc.bos_choch(df, swing_hl, close_break=True)

# Step 3: Identify zones
fvg = smc.fvg(df, join_consecutive=True)
ob = smc.ob(df, swing_hl, close_mitigation=False)
liquidity = smc.liquidity(df, swing_hl, range_percent=0.01)

# Step 4: Get retracements
retracements = smc.retracements(df, swing_hl)

# Step 5: Session context
sessions = smc.sessions(df, session="London", time_zone="UTC+0")

# Step 6: Previous levels
prev_levels = smc.previous_high_low(df, time_frame="1D")
```

### Suppress Credit Message

```bash
export SMC_CREDIT=0
```

---

## 14. Patterns to Adopt for Our MT5 Bot

### High-Priority Adoptions

#### 1. SMC as Primary Signal Source (via smartmoneyconcepts library)

**What they do:** SMC generates the actual entry/SL/TP. ML only confirms/blocks.

**What we should do:** Add SMC analysis to our CVD/Bollinger/EMA strategies as an additional confirmation layer OR build a dedicated SMC strategy:

```
Our current: CVD signal -> ML meta-filter -> entry
Proposed:    SMC signal -> CVD confirmation -> ML meta-filter -> entry
```

The `smartmoneyconcepts` package is pip-installable and returns pandas DataFrames -- perfect for our Django/Celery pipeline. We can call it inside our strategy `check_entry()` methods.

#### 2. Dynamic Confidence Threshold

**What they do:** Adjust ML confidence required for entry based on session, regime, volatility, trend (score 0-100 -> threshold 60-85%).

**What we should do:** Our ML meta-filter has fixed threshold progression (0 -> 0.40 -> 0.50 -> 0.55). We should make this dynamic:
- During London-NY overlap + trending: lower threshold (more entries)
- During Asian session + ranging: higher threshold (fewer entries)
- This matches their "EXCELLENT conditions need only 60% confidence, POOR conditions need 85%"

#### 3. Multi-Timeframe H1 Context Features

**What they do:** 8 H1 features added via backward join (no lookahead). H1 market structure, EMA distance, ATR ratio, swing proximity.

**What we should do:** Our S/R system already uses M15+H1+H4 swing detection. We should expose H1 indicators as features for our LightGBM meta-filter:
- `h1_market_structure` (our S/R trend direction)
- `h1_atr_ratio` (H1 ATR / M5 ATR)
- `h1_swing_proximity` (distance to nearest H1 S/R level)

#### 4. Continuous SMC Features (Not Just Binary)

**What they do:** Convert binary SMC flags (OB yes/no) to continuous values (OB distance in ATR, FVG size in ATR, BOS recency in bars).

**Why this matters:** Tree-based models (XGBoost, LightGBM) can split on continuous values but get almost no information from binary flags. This is a significant ML improvement.

#### 5. HMM Regime Detection with ATR Fallback

**What they do:** 3-state HMM with 8 features, plus ATR percentile override as sanity check.

**What we should do:** Our market context gate already does macro + regime, but adding formal HMM classification with ATR fallback would be more robust than our current approach. The ATR percentile override is clever -- prevents the HMM from calling "low volatility" when ATR is at the 90th percentile.

#### 6. Regime-Based Position Sizing Multipliers

**What they do:** LOW/MEDIUM = 1.0x, HIGH = 0.5x, CRISIS = 0.0x.

**What we should do:** Our dynamic sizing already considers volatility, but we should add explicit regime multipliers. No trading in crisis mode is a strong capital preservation pattern.

### Medium-Priority Adoptions

#### 7. 4-Mode Trading State Machine

Their NORMAL -> RECOVERY -> PROTECTED -> STOPPED progression with automatic transitions is elegant:
- 3 consecutive losses -> RECOVERY (min lot, 1 position)
- 80% daily limit used -> PROTECTED (min lot, 1 position)
- Daily/total limit hit -> STOPPED (no trading)

We have circuit breaker and pause logic, but formalizing it as a state machine would make the logic cleaner and more debuggable.

#### 8. Fuzzy Logic Exit Confidence

30-rule fuzzy controller combining velocity, acceleration, profit retention, RSI, time, profit level into a single exit confidence score. More nuanced than our binary exit conditions.

#### 9. Kalman-Smoothed Profit Trajectory

Using a Kalman filter to smooth noisy profit readings and extract velocity/acceleration for exit decisions. Responds in 2-3 samples (10-15 seconds). Better than raw P&L for making exit decisions.

#### 10. Auto-Retraining with Rollback

Daily retraining at 05:00 with AUC-gated acceptance (>=0.65 to keep, <0.60 triggers rollback). We should adopt this for our LightGBM meta-filter.

### Lower-Priority / Inspirational

#### 11. Flash Crash Guard (>2.5%/min Emergency)

We don't trade gold (high flash crash risk), but having a volatility circuit breaker that closes ALL positions is a good safety net for any instrument.

#### 12. Signal Persistence Across Restarts

They save signal state to JSON so the bot doesn't duplicate entries after a restart. We handle this via Celery task idempotency, but worth verifying.

#### 13. M5 Confirmation for M15 Signals

Lower timeframe confirmation before entry. We could use M1 confirmation for our M5 strategies.

---

## 15. Architecture Comparison: XAUBot vs Our System

### Side-by-Side

| Component | XAUBot-AI | Our MT5 Bot |
|-----------|-----------|-------------|
| **Architecture** | Monolithic Python script | Django + Celery microservices |
| **Primary signal** | SMC (OB, FVG, BOS, CHoCH) | CVD Lack of Participants, Bollinger, EMA Ribbon |
| **ML model** | XGBoost (60 features, binary) | LightGBM (8 features, binary) |
| **ML role** | Confirmation gate only | Meta-filter (blocks low-quality signals) |
| **Regime detection** | HMM 3-state (8 features) | Macro + regime gate (merged) |
| **Position sizing** | Half-Kelly + regime + session | Vol + streak + symbol + context |
| **Entry filters** | 14 sequential gates | 6 layers (time, circuit, symbol, context, ML, sizing) |
| **Exit system** | 12 conditions + fuzzy + Kalman | MFE-optimized phases + S/R trailing |
| **Trailing** | ATR-adaptive (2x/4x/3x ATR) | S/R swing trailing + phase-based |
| **Data processing** | Polars (fast) | Pandas (slower but sufficient) |
| **Broker** | Direct MT5 Python API | MT5 Flask API (containerized) |
| **Instruments** | XAUUSD only | Multi-pair forex + Lighter DEX |
| **Retraining** | Daily auto with rollback | Manual trigger at 30 labeled trades |
| **Dashboard** | Next.js web UI | Vue 3 + lightweight-charts |
| **Notifications** | Telegram bidirectional | Django AI Brain (advisory) |
| **Database** | PostgreSQL + CSV fallback | PostgreSQL (primary) |
| **Deployment** | Docker single container | Docker Compose multi-service |

### What They Have That We Don't (And Should Consider)

1. **SMC pattern detection** -- Order Blocks, Fair Value Gaps, Break of Structure as primary signals. The `smartmoneyconcepts` pip package makes this easy to add.

2. **Dynamic confidence threshold** -- Their 60-85% threshold based on market quality score. Our fixed threshold progression is simpler but less adaptive.

3. **Formal HMM regime classification** -- 3-state with 8 features + ATR override. More sophisticated than our macro+regime merge.

4. **Multi-timeframe ML features** -- H1 features via backward join. We have S/R multi-TF but don't expose it to our ML model.

5. **Continuous SMC features** -- FVG size, OB distance, BOS recency as continuous values. Much better for tree-based ML than binary flags.

6. **Kalman-smoothed exit signals** -- Profit trajectory smoothing for cleaner exit decisions.

7. **Fuzzy logic exits** -- 30-rule controller for exit confidence. More nuanced than binary conditions.

8. **4-mode trading state machine** -- NORMAL/RECOVERY/PROTECTED/STOPPED with auto-transitions.

9. **Auto-retraining with AUC-gated rollback** -- Daily retraining with quality checks.

### What We Have That They Don't

1. **MFE/MAE-optimized exits** -- Our Phase 0-3 system based on actual trade statistics (MFE lock at $5+, flat exit threshold). Data-driven rather than rule-based.

2. **Multi-instrument support** -- We trade multiple forex pairs + crypto. They're single-instrument (XAUUSD).

3. **S/R-based dynamic TP/SL** -- Our multi-TF swing clustering places TP/SL at actual structure levels. They use fixed ATR multiples.

4. **AI Brain advisory system** -- LLM-powered trade analysis (advisory for exits, auto-execute for SL tightening).

5. **Lighter DEX integration** -- Cross-venue execution capability.

6. **Celery task architecture** -- Distributed, fault-tolerant task processing vs their monolithic loop.

7. **Full 30-feature extraction for LLM training** -- We extract extensive features for future LLM training data, beyond what the live ML model uses.

### Recommended Integration Path

**Phase 1: Add smartmoneyconcepts to Feature Pipeline**
```
pip install smartmoneyconcepts
```
Add SMC analysis in our strategy `check_entry()` methods. Start with FVG and OB detection as additional confirmation for CVD signals. Expose continuous SMC features (FVG size, OB distance, BOS recency) to our LightGBM meta-filter.

**Phase 2: Dynamic Confidence Threshold**
Replace fixed threshold progression with session+regime+volatility scoring. Use their 0-100 quality score -> threshold mapping pattern.

**Phase 3: HMM Regime Detector**
Add `hmmlearn` as a formal regime classifier alongside our existing market context gate. Use their 8-feature vector and ATR fallback override pattern.

**Phase 4: Enhanced Exit System**
Consider adding Kalman-smoothed profit trajectory and fuzzy exit confidence scoring to complement our MFE-based phase system.

**Phase 5: Auto-Retraining Pipeline**
Implement daily auto-retraining for our LightGBM with AUC-gated acceptance and automatic rollback on degradation.

---

## Appendix A: Technology Stack Comparison

| Layer | XAUBot-AI | SURGE-WSI | Our System |
|-------|-----------|-----------|------------|
| Language | Python 3.11+ | Python 3.11+ | Python 3.11+ |
| Data processing | Polars | Pandas | Pandas |
| ML framework | XGBoost | None | LightGBM |
| Regime detection | hmmlearn (HMM) | hmmlearn (HMM) | Custom rule-based |
| SMC library | Custom (Polars) | smartmoneyconcepts | None (to add) |
| Price smoothing | Kalman (custom) | filterpy (Kalman) | None (to add) |
| Broker API | MetaTrader5 (direct) | MetaTrader5 (direct) | MT5 Flask API |
| Database | PostgreSQL | TimescaleDB | PostgreSQL |
| Cache | None | Redis | Redis |
| Dashboard | Next.js | None | Vue 3 + Vite |
| Notifications | Telegram | Telegram | Django AI Brain |
| Deployment | Docker (single) | Docker Compose | Docker Compose |
| Task scheduling | asyncio loop | Main loop | Celery + Beat |

## Appendix B: XAUBot Session Schedule (WIB = GMT+7)

| Window | WIB Hours | Multiplier | Status |
|--------|-----------|-----------|--------|
| Dead Zone | 00:00-04:00 | N/A | BLOCKED |
| Rollover | 04:00-06:00 | N/A | BLOCKED |
| Sydney | 06:00-07:00 | 0.5x | Reduced |
| Tokyo+Sydney | 07:00-13:00 | 0.7x | Reduced |
| Tokyo End | 13:00-15:00 | 0.7x | Reduced |
| London | 15:00-20:00 | 1.0x | Normal |
| **GOLDEN TIME** | **20:00-23:59** | **1.2x** | **Optimal** |
| Friday Late | >23:00 | N/A | BLOCKED |

## Appendix C: SURGE-WSI Kill Zones (UTC)

| Session | UTC Hours | Purpose |
|---------|-----------|---------|
| London | 08:00-12:00 | Primary trading |
| New York | 13:00-17:00 | Primary trading |
| Overlap | 15:00-17:00 | Highest liquidity |

## Appendix D: Key Configuration Parameters (XAUBot)

| Parameter | Value | Location |
|-----------|-------|----------|
| Flash crash threshold | 2.5%/min | config.py |
| ML min confidence | 65% | config.py |
| Entry confidence | 70% | config.py |
| High confidence | 75% | config.py |
| Very high confidence | 80% | config.py |
| Trade cooldown | 300 seconds | config.py |
| Swing detection window | 5 bars | config.py |
| FVG minimum gap | 2.0 pips | config.py |
| Order Block lookback | 10 bars | config.py |
| Regime lookback | 500 bars | config.py |
| Retrain frequency | 7 days | config.py |
| HMM retrain frequency | 20 candles | regime_detector.py |
| XGBoost max depth | 3 | ml_model.py |
| XGBoost learning rate | 0.05 | ml_model.py |
| XGBoost L1 (alpha) | 1.0 | ml_model.py |
| XGBoost L2 (lambda) | 5.0 | ml_model.py |
| Min SL distance | 1.5x ATR | risk_engine.py |
| Max daily loss | 3% (small) / 2% (medium) | config.py |
| Max total loss | 10% | config.py |
| Max positions | 2-3 | config.py |
| Lot range | 0.01-0.03 | smart_risk_manager.py |

---

*This document was compiled from direct source code analysis of all three repositories. Last updated: 2026-03-11.*

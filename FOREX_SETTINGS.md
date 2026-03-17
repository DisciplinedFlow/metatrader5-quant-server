# Forex Bot Settings & Recovery Guide

> How to configure, tune, and restore safety gates on the BRAIN_V1 trading system.

---

## Current Mode: BRAIN UNLEASHED (Mar 17, 2026)

The brain trades autonomously with smart gates only. Dumb gates removed.

### Smart Gates (ACTIVE — keep these)

| Gate | What It Does | How to Adjust |
|------|-------------|---------------|
| **Max Risk €50/trade** | Caps loss per position at €50 via risk-based sizing | `entry.py:80` → `MAX_LOSS_PER_TRADE = 50` |
| **R:R Minimum 2.0** | Only takes trades where reward ≥ 2× risk | `structure_levels.py` → `min_rr=2.0` |
| **Margin Check** | Pre-validates margin before every order | `entry.py` → `check_margin_for_order()` |
| **Order Dry-Run** | Validates SL/TP/volume before sending | `entry.py` → `check_order()` |
| **Anti-Churn 60s** | Prevents re-entering same symbol within 60s | `structure_entry.py` → 60s cooldown check |
| **PairLock** | No duplicate positions on same symbol | `PairLock.objects.filter(symbol=pair)` |
| **Neo4j Advisor** | AVOID blocks trade if confidence < 0.2 | `advisor.py` → `_calculate_confidence()` |
| **MTF Conflict Filter** | Skips trades against HTF trend (conf ≥ 0.6) | `entry.py` → MTF context check |
| **News Sizing** | EXTREME → 0.5×, ELEVATED → 0.75× position size | `news_sentiment.py` → `size_multiplier` |
| **NG-C Vol Guard** | Skips NG-C when vol_min forces risk > 2.5× target | `entry.py:1743` |

### Dumb Gates (REMOVED — add back if needed)

| Gate | What It Did | How to Restore |
|------|------------|----------------|
| **Circuit Breaker (global)** | 5 losses → pause all trading | See "Restore Circuit Breaker" below |
| **Circuit Breaker (symbol)** | 3 losses → pause that symbol | See "Restore Circuit Breaker" below |
| **Symbol WR Filter** | Skip symbol if WR < 35% last 10 trades | See "Restore Symbol Filter" below |
| **Kill Zone Confluence Raise** | Min confluence 6 outside kill zones | See "Restore Kill Zone Gate" below |
| **Daily Halt** | Stop all trading after -$300/day | See "Restore Daily Halt" below |

---

## How to Restore Each Gate

### Restore Circuit Breaker

The circuit breaker pauses trading after consecutive losses.

```python
# In entry.py, find CIRCUIT_BREAKER constants (~line 57):
CIRCUIT_BREAKER_SYMBOL_LOSSES = 3     # losses on same symbol → pause
CIRCUIT_BREAKER_GLOBAL_LOSSES = 5     # total losses → pause all
CIRCUIT_BREAKER_GLOBAL_COOLDOWN_MINUTES = 5   # how long to pause (global)
CIRCUIT_BREAKER_SYMBOL_COOLDOWN_MINUTES = 15  # how long to pause (symbol)
```

The circuit breaker code is still in `_check_circuit_breaker()` function. In TRAINING_MODE it's bypassed. To restore:

**Option A: Turn off training mode**
```python
# entry.py line 75:
TRAINING_MODE = False  # Restores ALL gates including circuit breaker
```

**Option B: Keep training mode but re-enable just circuit breaker**
```python
# In entry.py, find the _check_circuit_breaker call (~line 1189):
# Change from:
if not TRAINING_MODE:
    allowed, reason = _check_circuit_breaker(...)
# To:
allowed, reason = _check_circuit_breaker(...)  # Always check, even in training
```

**Tune the values:**
- Shorter cooldown for aggressive: `GLOBAL_COOLDOWN = 3` (3 minutes)
- Longer cooldown for conservative: `GLOBAL_COOLDOWN = 15` (15 minutes)
- More lenient trigger: `GLOBAL_LOSSES = 8` (8 losses before pause)

### Restore Symbol WR Filter

Blocks symbols with poor recent win rate.

```python
# In entry.py (~line 61):
SYMBOL_FILTER_LOOKBACK = 10        # Check last N trades
SYMBOL_FILTER_MIN_WR = 0.35       # Minimum 35% win rate
SYMBOL_FILTER_COOLDOWN_HOURS = 8   # How long to skip
```

To restore, same approach as circuit breaker — find the `_check_symbol_filter` call and remove the `if not TRAINING_MODE` guard.

### Restore Kill Zone Confluence Raise

Requires higher confluence score outside trading sessions (London/NY).

```python
# In entry.py (~line 1633), uncomment:
try:
    from app.quant.indicators.kill_zones import is_in_kill_zone
    if not is_in_kill_zone():
        router_min_confluence = max(router_min_confluence, 6)
except Exception:
    pass
```

### Restore Daily Halt

Stops all trading after exceeding daily loss limit.

```python
# In tasks.py (~line 26):
DAILY_MAX_LOSS_USD = 300  # Was $9,999 (disabled). Set to $300 for live.

# The check is in run_quant_entry_algorithm():
if not TRAINING_MODE and _check_global_daily_halt():
    return  # Skip all trading today
```

### Restore Confluence Minimum

Raise the minimum confluence score required for entry.

```python
# In entry.py (~line 1374):
router_min_confluence = 3  # Brain mode. Change to 4 or 5 for tighter filtering.
```

---

## Going Live Checklist (When Moving to Real Money)

1. **Set TRAINING_MODE = False** → restores all gates
2. **Set DAILY_MAX_LOSS_USD = 200** → hard daily stop
3. **Set Circuit Breaker Global = 10 minutes** → breathing room
4. **Set Confluence minimum = 4** → quality filter
5. **Reduce MAX_OPEN_TRADES to 5** → limit exposure
6. **Reduce Per-strategy max_positions to 3** → diversify
7. **Test on demo for 1 week** with gates on to verify brain + gates work together
8. **Start with 25% of intended capital** → scale up as confidence grows

---

## Active Configuration (Mar 17, 2026)

| Parameter | Value | Notes |
|-----------|-------|-------|
| TRAINING_MODE | `True` | Brain mode — smart gates only |
| Position Sizing | Risk-based | `lots = target_risk / loss_per_lot_at_SL` |
| MAX_LOSS_PER_TRADE | `€50` | Hard cap per position |
| R:R Minimum | `2.0` | Structure-based SL/TP |
| Account Currency | `EUR` | VantageInternational-Demo |
| Broker Leverage | `500:1` | Not used — risk-based sizing instead |
| Active Strategies | 7 | CVD Lack of Part, Absorption, London Open, Structure Auto, 3 energy |
| News Intelligence | Pi FinBERT → Claude → Keywords | 3-tier fallback |
| Neo4j Advisor | Temporal decay 7d half-life | BRAIN_V1 trades 2× weight |
| Structure Scanner | Every 30s, autonomous | 4 setup types, max 3 signals/cycle |
| Circuit Breaker | **OFF** (brain self-corrects) | Restore for live trading |
| Symbol Filter | **OFF** (brain reads structure) | Restore for live trading |
| Daily Halt | **OFF** ($9,999 = disabled) | Restore for live trading |

---

## Change Log

### Mar 17, 2026 — Brain Unleashed
- TRAINING_MODE=True, all dumb gates bypassed
- Structure scanner deployed (autonomous entries)
- Neo4j causal chains + trade reasoning memory
- Claude API intelligence active (€100 budget)
- Pi FinBERT NLP connected (67ms sentiment)
- DOM orderbook integration
- WebSocket real-time dashboard
- Temporal memory decay (7-day half-life)
- Circuit breaker: cleared, brain self-corrects
- Symbol filter: cleared, brain reads current structure
- Kill zone raise: disabled, brain reads MTF
- Performance: R:R improved 0.73 → 1.49, avg loss $4.51 → $0.82

### Mar 16, 2026 — Risk-Based Sizing + Circuit Breaker Tuning
- Replaced `capital × leverage` with risk-based sizing
- Circuit breaker: 1h → 15m → 10m → 5m (progressive reduction)
- Backtest gate disabled for SCALPING
- VWAP + session levels added to confluence (max 12 → 14)
- XAGUSD confluence gate lowered to 3
- News sentiment via RSS feeds (CNBC, MarketWatch, BBC, Yahoo)

### Mar 15, 2026 — Initial Launch
- Paper trading run started
- TRAINING_MODE=False, all gates active
- 12 custom strategies + SCALPING
- Fixed ATR SL/TP (1.8×/3.6×)

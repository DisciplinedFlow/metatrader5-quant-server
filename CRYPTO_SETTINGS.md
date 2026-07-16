# Crypto Bot Settings — Gate & Blocker Reference

> Current state: **TRAINING MODE** (gates disabled, brain collecting data)
> Date disabled: 2026-03-17
> Re-enable when: 200+ crypto trades with ML features in DB

---

## Disabled Gates (re-enable in order)

### 1. ML Meta-Filter
**Files:**
- `backend/django/app/quant/algorithms/lighter/rsi_scalper.py` (~line 278)
- `backend/django/app/quant/algorithms/lighter/mean_reversion.py` (~line 333)

**What it does:** XGBoost classifier scores each signal 0-1, rejects below threshold.

**Why disabled:** Model undertrained on crypto — returned 0.44 on every signal regardless of quality, blanket-rejecting 92% of trades.

**Re-enable when:** `CryptoPosition.objects.filter(status='CLOSED').count() >= 200` and `train_crypto_ml` task has run successfully.

**Code to restore (both files):**
```python
# ── ML meta-filter ──
try:
    from app.quant.ml.crypto_integration import ml_filter_crypto
    ml_passed, ml_score, ml_reason = ml_filter_crypto(
        symbol, signal_type, rsi_value=current_rsi, adx_value=None,
        hour=__import__('datetime').datetime.utcnow().hour
    )
    if not ml_passed:
        logger.info("RSI2 %s: ML REJECT score=%.2f — %s", symbol, ml_score, ml_reason)
        return False
except Exception:
    pass
```

**Recommended threshold:** Start at 0.40 (lenient), raise to 0.55 once model accuracy > 60%.

---

### 2. Losing Streak Cooldown
**Files:**
- `backend/django/app/quant/algorithms/lighter/rsi_scalper.py` (~line 189)
- `backend/django/app/quant/algorithms/lighter/mean_reversion.py` (~line 197)
- `backend/django/app/quant/algorithms/lighter/entry.py` — `_check_lighter_losing_streak()` (~line 228)

**What it does:** After 5 consecutive losses across all Lighter strategies, pauses trading for 5 minutes. Cache key: `lighter:streak_cooldown`.

**Why disabled:** Brain needs to observe behavior through losing streaks to learn patterns.

**Re-enable when:** Account equity > $200 (at $32, a 5-loss streak at current sizing is survivable; at larger sizing it's not).

**Code to restore (rsi_scalper.py + mean_reversion.py):**
```python
# Losing streak cooldown (5 losses → 5 min pause)
if cache.get('lighter:streak_cooldown'):
    logger.debug("RSI2: losing streak cooldown, skipping")
    return
```

**Code to restore (entry.py — replace the stub function):**
```python
def _check_lighter_losing_streak():
    """Losing streak cooldown: 5 min pause after 5 consecutive losses."""
    from django.core.cache import cache
    if cache.get('lighter:streak_cooldown'):
        return False, "Lighter: losing streak cooldown (5 min)"

    from app.crypto.models import CryptoPosition
    recent = CryptoPosition.objects.filter(
        status='CLOSED',
        entry_signal__startswith=PLATFORM_PREFIX,
        pnl_usd__isnull=False,
    ).order_by('-closed_at')[:5]

    losses = sum(1 for p in recent if p.pnl_usd < 0)
    if len(recent) >= 5 and losses >= 5:
        cache.set('lighter:streak_cooldown', True, timeout=300)
        logger.warning("Lighter: 5 consecutive losses — 5 min cooldown")
        return False, "Lighter: 5 consecutive losses, 5 min cooldown"
    return True, "OK"
```

---

### 3. Trend Pullback Signal (killed, not just disabled)
**File:** `backend/django/app/quant/algorithms/lighter/entry.py` (~line 158)

**What it was:** Signal Mode 2 in EMA entry — bought pullbacks into 1h EMA trends using 15m RSI.

**Why killed:** 36% WR across 14 trades, -$2.38 net loss. Statistically a losing strategy.

**Re-enable when:** Never, unless backtested and proven profitable on new data.

**Code to restore:** Uncomment the `trend_pullback_15m` signal block in entry.py signal generation section.

---

## Active Gates (kept on — these help)

### Position Limits
- RSI2: max 3 open (`RSI2_MAX_POSITIONS`)
- Mean Reversion: max 4 open
- EMA Entry: max 2 open (`LIGHTER_MAX_POSITIONS`)
- **Why keep:** Protects $32 account from overexposure. Remove limit increase until equity > $500.

### Per-Symbol Cooldowns
- RSI2: 30 seconds post-trade
- Mean Reversion: 60 seconds post-trade
- **Why keep:** Prevents re-entering the same dying signal every 30s cycle.

### Dashboard Toggle
- Cache key: `lighter:disabled`
- **Why keep:** Manual kill switch for emergencies.

---

## Active Intelligence Layers (sizing, not blocking)

### News Sentiment
- Source: Pi FinBERT → Claude API → keyword fallback
- Effect: NORMAL=1.0x, ELEVATED=0.75x, EXTREME=0.5x sizing
- Cache: 5 min
- **Never blocks, only sizes down**

### Graph Advisor (Neo4j)
- Queries: similar setups, symbol-regime WR, time-of-day WR, causal chains
- Effect: STRONG=1.2x, NORMAL=1.0x, CAUTION=0.7x sizing
- AVOID = skip trade (only fires with strong historical evidence of losses)
- Cache: 5 min
- **Rarely blocks, mostly adjusts sizing**

### Trade Reasoning Recording
- Records WHY each trade was taken to Neo4j
- Builds the data that makes graph advisor smarter over time
- **Never blocks, pure observation**

---

## Sizing Parameters
```
LIGHTER_CAPITAL_USD = 10        # config.py
LIGHTER_LEVERAGE = 5            # config.py
LIGHTER_POSITION_SIZE_PCT = 0.40  # 40% of capital per trade
LIGHTER_MAX_POSITIONS = 2       # config.py
RSI2 base size = $8
MR base size = $8
```

## Re-enable Checklist

1. [ ] 200+ closed crypto trades in DB → re-enable ML filter at threshold 0.40
2. [ ] ML model accuracy > 60% on validation set → raise threshold to 0.55
3. [ ] Account equity > $200 → re-enable losing streak cooldown
4. [ ] Account equity > $500 → consider increasing position limits
5. [ ] Backtest trend_pullback on fresh data → only re-enable if WR > 50%

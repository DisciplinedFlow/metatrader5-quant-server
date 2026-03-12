# Production Rollback: Disable Training Mode

**Created:** 2026-03-12
**Purpose:** Reapply all production safety filters after ML training data collection reaches 1,000+ labeled trades.
**Trigger:** Run `TRAINING_MODE = False` when trade count target is hit.

## Pre-Flight Check

```bash
# Verify you have enough labeled trades before switching
docker exec django bash -c "cd /app && python manage.py shell -c \"
from app.nexus.models import Trade
count = Trade.objects.filter(pnl__isnull=False).count()
print(f'Labeled trades: {count}')
print('READY for production' if count >= 1000 else f'Need {1000 - count} more trades')
\""
```

## Changes Required

### 1. Entry Algorithm — `backend/django/app/quant/algorithms/cvd/entry.py`

**Line ~63:** Flip the master switch:
```python
# CHANGE FROM:
TRAINING_MODE = True

# CHANGE TO:
TRAINING_MODE = False
```

**Line ~58-59:** Restore production symbol filter thresholds:
```python
# CHANGE FROM:
SYMBOL_FILTER_MIN_WR = 0.25
SYMBOL_FILTER_COOLDOWN_HOURS = 2

# CHANGE TO:
SYMBOL_FILTER_MIN_WR = 0.35
SYMBOL_FILTER_COOLDOWN_HOURS = 8
```

> Setting `TRAINING_MODE = False` automatically re-enables all 11 filter layers:
> 1. Trading session (07:00-17:00 UTC, Sundays blocked)
> 2. High-impact economic event guard (NFP, FOMC, CPI — 30min window)
> 3. Global circuit breaker (5 consecutive losses → 1h pause)
> 4. Per-symbol circuit breaker (3 consecutive losses → 1h pause)
> 5. Symbol performance filter (WR < threshold over last 10 trades → cooldown)
> 6. Strategy router regime gate (regime-strategy mismatch → skip)
> 7. Correlation group limit (no duplicate positions in same group)
> 8. Market context gate (macro news + regime sizing)
> 9. ML meta-filter (XGBoost win probability → reject low scores)
> 10. Confluence scorer gate (score < should_trade band → skip)
> 11. Router min_confluence gate (regime-specific minimum)

### 2. Strategy Router — `backend/django/app/quant/algorithms/strategy_router.py`

**Line ~139-144:** Decide on VOLATILE min_confluence. Was 9 (too strict), currently 6:
```python
'VOLATILE': {
    'size_multiplier': 0.5,
    'min_confluence': 6,       # Was 9 pre-training. 6 is a good middle ground.
    'sl_multiplier_adj': 1.5,
    'tp_approach': 'trailing',
},
```

> **Recommendation:** Keep at 6. The old value of 9 was effectively impossible to reach (9/11 confluence points). 6 still requires strong setups while allowing trades in volatile conditions. Review after analyzing the 1,000-trade dataset — if volatile-regime trades have significantly worse outcomes, raise to 7.

### 3. Tasks — `backend/django/app/quant/tasks.py`

**No manual changes needed.** `GLOBAL_MAX` and `DAILY_MAX_LOSS_USD` are computed from `TRAINING_MODE` automatically:
```python
GLOBAL_MAX = 20 if TRAINING_MODE else 10
DAILY_MAX_LOSS_USD = 9999.0 if TRAINING_MODE else 300.0
```

Setting `TRAINING_MODE = False` in entry.py restores:
- GLOBAL_MAX = 10 concurrent positions
- DAILY_MAX_LOSS_USD = $300

### 4. ICT Scanner Symbols — `backend/django/app/quant/tasks.py`

**No changes needed.** The expanded 14-symbol list is good for production:
```
Forex majors:  EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD, USDCAD, USDCHF
Forex minors:  EURGBP, USDCNH, USDSEK
Metals:        XAUUSD, XAGUSD
Energy:        USOUSD, UKOUSDft
```

### 5. `smartmoneyconcepts` Package

This package is pip-installed directly in containers (not in requirements.txt due to slow numba compilation under QEMU). After any container rebuild:
```bash
docker exec django pip install smartmoneyconcepts
docker exec celery pip install smartmoneyconcepts
```

## Deployment Steps

```bash
# 1. Make the code changes above (just entry.py line 63 + lines 58-59)

# 2. Hot-patch containers
docker cp backend/django/app/quant/algorithms/cvd/entry.py celery:/app/app/quant/algorithms/cvd/entry.py
docker cp backend/django/app/quant/algorithms/cvd/entry.py django:/app/app/quant/algorithms/cvd/entry.py

# 3. Clear any stale cooldowns from training
docker exec django bash -c "cd /app && python manage.py shell -c \"
from django.core.cache import cache
import redis as _redis
from django.conf import settings
r = _redis.Redis.from_url(settings.CELERY_BROKER_URL)
for pattern in ['symbol_filter:*', 'circuit_breaker:*', 'daily_halt*']:
    for k in r.keys(pattern):
        r.delete(k)
        print(f'Cleared: {k.decode()}')
print('All cooldowns cleared')
\""

# 4. Restart workers
docker restart celery celery-beat

# 5. Verify production filters are active
docker logs celery --tail 200 --since 2m 2>&1 | grep -E "TRAINING MODE|Confluence too low|ROUTER SKIP|paused|session"
# Should see "Confluence too low" and "ROUTER SKIP" messages — NOT "TRAINING MODE"

# 6. Commit and push
git add backend/django/app/quant/algorithms/cvd/entry.py
git commit -m "Disable TRAINING_MODE: restore production safety filters"
git push nomu main
```

## Post-Rollback: Retrain ML Model

After switching to production, trigger a model retrain with the new 1,000+ trade dataset:
```bash
docker exec django bash -c "cd /app && python manage.py shell -c \"
from app.quant.ml.trainer import train_model
result = train_model(force=True)
print(result)
\""
```

## Training Mode Stats at Time of Creation

| Metric | Value |
|--------|-------|
| Labeled trades | 203 |
| Target | 1,000 |
| Remaining | 797 |
| Instruments | 14 (7 forex majors + 3 minors + 2 metals + 2 energy) |
| Active strategies | All CustomStrategies in DB |
| Position limit | 20 concurrent |
| Filters bypassed | All 11 layers |

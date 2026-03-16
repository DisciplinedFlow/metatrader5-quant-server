# Crypto Bot Fix — Mar 16, 2026

## Issues Found

### 1. Lighter Signer Proxy Down (CRITICAL)
The Lighter.xyz signer proxy on port 5555 was not running. Every Lighter entry attempt
failed with `Lighter signer proxy not reachable at http://host.docker.internal:5555`.
16 valid trade signals (9x GBPUSD, 7x EURUSD) were generated but none could execute.

### 2. Circuit Breaker Log Flood (PERFORMANCE)
When the global circuit breaker was active (5 consecutive losses → 1h cooldown),
every entry cycle iterated through ~12 strategies × ~14 pairs, generating:
- ~588 WARNING logs per 10 minutes
- ~588 `record_to_graph.delay()` calls writing to Neo4j
- Entry task taking 2-5s instead of <0.2s

### 3. SCALPING Backtest Gate (WORKING AS DESIGNED)
SCALPING strategy blocked at 33.77% win rate (threshold: 55%). No fix needed.

## Fixes Applied

### Fix 1: Started Signer Proxy
```bash
cd backend/lighter-proxy && python3 proxy.py
```
Runs natively on macOS (Go native library crashes under QEMU in Docker).
First trade executed: GBPUSD BUY $20 via Lighter DEX.

**Note:** The proxy needs a launchd plist for persistence across reboots.
See `backend/lighter-proxy/com.lighter.proxy.plist`.

### Fix 2: Global CB Early Exit (tasks.py + entry.py)

**`backend/django/app/quant/tasks.py`** — Added fast Redis check before strategy loop:
```python
if not TRAINING_MODE:
    from django.core.cache import cache
    if cache.get('circuit_breaker:global'):
        logger.debug("Global circuit breaker active — skipping all entry algorithms.")
        return
```

**`backend/django/app/quant/algorithms/cvd/entry.py`** — Two changes:
1. Pre-loop global CB: downgraded from WARNING to DEBUG, removed graph write
2. Per-symbol CB: downgraded from WARNING to DEBUG, removed redundant graph write

**Result:** 588 warnings/10min → 0. Entry task: 2-5s → 0.01-0.2s. Zero trading logic changed.

## Files Modified
- `backend/django/app/quant/tasks.py` (hot-patched into celery + django containers)
- `backend/django/app/quant/algorithms/cvd/entry.py` (hot-patched into celery + django containers)

## Verification
```bash
# Check proxy health
curl http://localhost:5555/health

# Check CB noise is gone
docker logs celery --since 5m 2>&1 | grep -c "Circuit breaker"

# Check no proxy errors
docker logs celery --since 5m 2>&1 | grep -c "signer proxy not reachable"
```

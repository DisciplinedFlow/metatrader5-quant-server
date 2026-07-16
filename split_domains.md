# Domain Separation Plan: Forex (MT5) vs Crypto (Lighter.xyz)

**Date:** 2026-03-21
**Goal:** Split the monolith so rebuilding or restarting the crypto stack cannot crash or interrupt the forex trading stack, and vice versa.

---

## Current State Audit

### Shared containers (the problem)

| Container | What it runs |
|-----------|-------------|
| `django` | Serves BOTH `app/nexus/` (forex API) AND `app/crypto/` (crypto API) under one Gunicorn process |
| `celery` | Runs ALL tasks: forex trailing-stop (every 2s!), forex entry (60s), crypto lighter-exit (15s), lighter-entry (60s), lighter-rsi-scalper (30s), lighter-reconcile (60s), lighter-mean-reversion (300s), plus tick consumer + WebSocket server as background processes |
| `celery-beat` | Schedules ALL tasks from a single `CELERY_BEAT_SCHEDULE` |
| `redis` | Single instance, DB0=Celery broker, DB1=Django cache (shared by both domains), DB2=tick stream |
| `postgres` | Single instance, single `default` database |

### What is already separated

- `mt5` container — forex-only, already isolated
- `lighter-proxy` (`ws_streamer.py`) — runs natively on macOS outside Docker, already separate
- Redis key namespaces are already well-separated by convention:
  - Forex: `fx:*`, `fx_cd:*`, `realtime_cvd:*`, `tick_consumer:*`, `bot:paused`, `market_pulse:*`, `hmm:*`, `quant:*`
  - Crypto: `lighter:*`, `bot:crypto:paused`, `crypto:*`

### Cross-domain coupling inventory

These are the actual coupling points that complicate separation:

**1. Shared Celery app and broker (DB0)**
All tasks share one Redis DB0 queue. A full celery restart (e.g. to deploy crypto changes) kills the 2-second forex trailing-stop heartbeat.

**2. `quant.tasks.run_crypto_entry` is scheduled alongside forex tasks**
`settings.py` line 326 schedules `quant.tasks.run_crypto_entry` (which calls `entry_crypto.py` → Lighter DEX) from within the main celery worker alongside `run_quant_trailing_stop_algorithm`. This is the most dangerous coupling: a bug in crypto entry that hangs can starve the forex trailing-stop queue.

**3. `global_daily_halt` Redis key is read by crypto tasks but SET by forex logic**
`crypto/tasks.py` checks `cache.get('global_daily_halt')` before each entry. This key is set by the forex risk manager (`entry_forex.py` → daily loss tracking). After separation, if the Redis instance is also split, this cross-domain risk signal breaks.

**4. `lighter/cvd_entry.py` imports `app.nexus.models.CustomStrategy`**
Line 134 of `cvd_entry.py`: `from app.nexus.models import CustomStrategy`. This means the crypto algorithm currently reads strategy config from the forex domain's database model. If Django instances are split this import will fail unless both share the same DB.

**5. `quant/ml/` directory is used by both domains**
`crypto_features.py`, `crypto_trainer.py`, `crypto_integration.py` live inside `app.quant.ml` alongside forex ML code. They import `from app.crypto.models import CryptoPosition`. No code conflict, but they are co-located.

**6. `app/quant/algorithms/lighter/config.py` imports `app.crypto.models`**
`is_global_position_limit_reached()` queries `CryptoPosition.objects` directly. This function is called from all lighter entry algorithms.

**7. Shared `ml_models/` Docker volume**
Both the forex model (`ml_models/`) and crypto model (`ml_models/crypto_training_data/`, `ml_models/crypto_model.joblib`) live in the same volume, mounted by both `django` and `celery`. Not a runtime problem but complicates ownership.

**8. Shared `quant-logs/` volume**
Both domains write to separate log files (`quant.log` vs `crypto.log` / `lighter.log`) but inside the same Docker volume. Not a correctness problem.

**9. Single `celery-beat` process**
Beat reads the entire `CELERY_BEAT_SCHEDULE` from `settings.py`. Restarting beat to change crypto schedule timing also briefly interrupts forex scheduling.

---

## Phase 1: Separate Celery Workers (LOW RISK — do first)

**What:** Add a second Celery worker (`celery-crypto`) that handles only crypto queues. Move all Lighter/crypto tasks off the main forex worker.

**Why this first:** Zero code changes. Purely operational. The forex trailing-stop (2s) is isolated from crypto task hangs immediately.

### Step 1.1 — Add a dedicated crypto queue

In `settings.py`, change the routing for all crypto tasks to a new `crypto` queue:

```python
CELERY_TASK_ROUTES = {
    # --- FOREX (forex worker: queues critical, analysis, default) ---
    'quant.tasks.run_quant_trailing_stop_algorithm': {'queue': 'critical'},
    'quant.tasks.run_quant_close_algorithm':         {'queue': 'critical'},
    'quant.tasks.run_position_reconciliation':       {'queue': 'critical'},
    'quant.tasks.run_forex_entry':                   {'queue': 'critical'},
    'quant.tasks.run_ict_scanner':                   {'queue': 'analysis'},
    'quant.tasks.run_regime_scan':                   {'queue': 'analysis'},
    'quant.tasks.run_strategy_orchestrator':         {'queue': 'analysis'},
    'quant.tasks.fetch_market_pulse':                {'queue': 'default'},
    'quant.tasks.check_news_sentiment':              {'queue': 'default'},
    'quant.tasks.check_tick_consumer_health':        {'queue': 'default'},

    # --- CRYPTO (crypto worker: queues crypto-critical, crypto-analysis) ---
    'quant.tasks.run_crypto_entry':                  {'queue': 'crypto-critical'},
    'crypto.tasks.run_lighter_exit':                 {'queue': 'crypto-critical'},
    'crypto.tasks.run_lighter_reconcile':            {'queue': 'crypto-critical'},
    'crypto.tasks.run_lighter_entry':                {'queue': 'crypto-analysis'},
    'crypto.tasks.run_lighter_rsi_scalper':          {'queue': 'crypto-analysis'},
    'crypto.tasks.run_lighter_mean_reversion':       {'queue': 'crypto-analysis'},
    'crypto.tasks.run_funding_arb_scan':             {'queue': 'crypto-analysis'},
}
```

Also update the beat schedule entry that inline-specifies the queue:
```python
# Remove the hardcoded 'options': {'queue': 'critical'} from run-lighter-exit in CELERY_BEAT_SCHEDULE
# The CELERY_TASK_ROUTES entry above takes precedence
```

### Step 1.2 — Add `celery-crypto` service to docker-compose.yml

```yaml
celery-crypto:
  build:
    context: backend/django
    dockerfile: Dockerfile
  container_name: celery-crypto
  command: celery -A app worker --loglevel=info --concurrency=3 -Q crypto-critical,crypto-analysis -n celery-crypto@%h
  volumes:
    - static_volume:/app/staticfiles
    - quant-logs:/app/logs
    - ./ml_models:/app/ml_models
  env_file:
    - .env
  depends_on:
    - django
    - redis
  networks:
    - default
  labels:
    <<: *default-labels
  logging: *default-logging
  mem_limit: 1536m
  cpus: 1.5
```

### Step 1.3 — Modify main `celery` worker to exclude crypto queues

```yaml
celery:
  # ...existing config...
  command: bash -c "python -m app.ws.server & python manage.py tick_consumer --redis-url redis://redis:6379/2 & celery -A app worker --loglevel=info --concurrency=6 -Q default,critical,analysis -n celery-forex@%h"
```

### Step 1.4 — Optionally add a `celery-beat-crypto` service

Beat itself is lightweight and a single restart is < 1s, but if you want total independence:

```yaml
celery-beat-crypto:
  # Same image, separate beat schedule via env var CELERY_BEAT_SCHEDULER override
  # OR: use database-backed scheduler and per-worker schedule tables
  # Simplest: just keep one beat, but accept it restarts briefly on schedule changes
```

**Recommendation for Phase 1:** Keep one beat for now. The win from separate workers is enormous; separate beat is minor upside.

### Deployment procedure (no downtime)

1. Deploy new settings.py with updated routes
2. `docker compose up -d celery-crypto` — starts new crypto worker
3. `docker compose restart celery` — forex worker now ignores crypto queues
4. `docker compose restart celery-beat` — beat now routes to correct queues
5. Verify with `docker exec celery celery -A app inspect active_queues`

**Risk:** Minimal. During step 3 (~5s restart), crypto tasks queue up in Redis and execute when celery-crypto picks them up. Forex trailing-stop is unaffected.

---

## Phase 2: Separate Celery Beat (LOW RISK — optional)

**What:** Run two beat processes, each with a subset of the schedule. Eliminates the last shared restart dependency between domains at the scheduler level.

**Implementation options:**

### Option A — Django DB scheduler (django-celery-beat)

Install `django-celery-beat`, store tasks in DB. Each beat instance can filter by a label/group. This requires a DB migration and adds a dependency, but gives you a dashboard to edit schedules without redeployment.

### Option B — Two settings files with filtered schedules

Create `app/settings_crypto.py` and `app/settings_forex.py`, each importing from the base `settings.py` and overriding `CELERY_BEAT_SCHEDULE` with only their domain's tasks.

```python
# app/settings_crypto.py
from app.settings import *

CELERY_BEAT_SCHEDULE = {k: v for k, v in CELERY_BEAT_SCHEDULE.items()
                        if 'crypto' in k or 'lighter' in k or 'funding' in k}
```

docker-compose entries:
```yaml
celery-beat-forex:
  command: celery -A app beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
  # OR: DJANGO_SETTINGS_MODULE=app.settings_forex celery -A app beat ...

celery-beat-crypto:
  command: celery -A app beat --loglevel=info
  environment:
    DJANGO_SETTINGS_MODULE: app.settings_crypto
```

**Recommendation:** Option B (split settings files) is the lowest friction. Do this in Phase 2 after Phase 1 is stable for a week.

---

## Phase 3: Separate Django Instances (MEDIUM RISK — do after Phase 1 is stable)

**What:** Run two Django/Gunicorn instances: `django-forex` and `django-crypto`. Each serves its own URL namespace. Traefik routes by hostname prefix.

**Why the risk is medium:** The `app.crypto` Django app currently shares the same Django project, `INSTALLED_APPS`, and migrations. Splitting requires either duplicating the project or using `DJANGO_SETTINGS_MODULE` overrides.

### Approach A — Two settings modules, one codebase (recommended)

Create `app/settings_forex.py`:
```python
from app.settings import *
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'app.crypto']
# Remove crypto URLs, or keep them (Django ignores unreachable apps gracefully)
```

Create `app/settings_crypto.py`:
```python
from app.settings import *
INSTALLED_APPS = [app for app in INSTALLED_APPS if app not in ('app.quant',)]
# Crypto Django only needs: app.crypto, rest_framework, corsheaders
```

docker-compose:
```yaml
django-forex:
  build:
    context: backend/django
    dockerfile: Dockerfile
  container_name: django-forex
  command: gunicorn --bind 0.0.0.0:8000 --workers 3 --worker-class=gthread --threads=2 --timeout 120 app.wsgi:application
  environment:
    DJANGO_SETTINGS_MODULE: app.settings_forex
  # ... traefik labels pointing to DJANGO_DOMAIN

django-crypto:
  build:
    context: backend/django
    dockerfile: Dockerfile
  container_name: django-crypto
  command: gunicorn --bind 0.0.0.0:8002 --workers 2 --worker-class=gthread --threads=2 --timeout 120 app.wsgi:application
  environment:
    DJANGO_SETTINGS_MODULE: app.settings_crypto
  ports:
    - "8002:8002"
  # ... traefik labels pointing to CRYPTO_DOMAIN (new env var)
```

### Critical blocker for Phase 3: the CustomStrategy cross-import

`lighter/cvd_entry.py:134` imports `from app.nexus.models import CustomStrategy`. This creates a compile-time dependency of the crypto domain on the forex nexus model.

**Resolution options (choose one):**
1. **Move the config lookup to Redis** (recommended): Store CVD strategy configs as a JSON blob in Redis (`lighter:cvd_strategies`). The forex Django or an admin API writes this; crypto reads it directly. Eliminates the DB cross-dependency.
2. **Duplicate the relevant config**: CVD strategies for Lighter are probably a small JSON structure. Store them in `app.crypto.models.CryptoStrategyConfig` instead. Copy the data once during migration.
3. **Shared DB, separate app servers**: Both Django instances point to the same PostgreSQL `default` database. Django-crypto can still query `nexus_customstrategy` table via a raw query or by keeping `app.nexus` in `INSTALLED_APPS` (read-only, no migrations in crypto instance). This is the lowest-friction option.

**Recommendation for Phase 3:** Use Option 3 (shared DB, `app.nexus` in read-only mode in crypto settings) initially. Migrate to Option 1 (Redis config) at leisure — it's a clean long-term design.

### URL routing change

Current `urls.py`:
```python
urlpatterns = [
    path('admin/', admin.site.urls),
    path('v1/', include('app.nexus.urls')),       # forex
    path('v1/crypto/', include('app.crypto.urls')), # crypto
]
```

After split:
- `django-forex` serves `v1/` only (forex + admin)
- `django-crypto` serves `v1/crypto/` only
- Dashboard API calls need to be routed to the right backend (update `VITE_API_URL` env var, or use two env vars: `VITE_FOREX_API_URL` and `VITE_CRYPTO_API_URL`)

---

## Phase 4: Separate Redis Databases (LOW RISK — most is already clean)

**What:** Confirm and lock down Redis key namespace isolation. Optionally split into two Redis instances in a future state.

### Current Redis DB layout

| DB | Used by | Contents |
|----|---------|----------|
| 0 | Both — Celery broker + result backend | Task queues (will be split by Phase 1 into named queues, but same DB) |
| 1 | Both — Django cache | Forex keys (`fx:*`, `realtime_cvd:*`, `hmm:*`, `market_pulse:*`) AND crypto keys (`lighter:*`, `bot:crypto:paused`, `crypto:*`) |
| 2 | Tick streamer | MT5 tick pub/sub + Lighter OB data |

### The `global_daily_halt` coupling

`crypto/tasks.py` reads `cache.get('global_daily_halt')`. This key is set by the forex daily loss tracker in `entry_forex.py`. This is an intentional cross-domain safety valve: if forex hits its daily loss limit, crypto halts too.

**Decision required:** Do you want them independently halted, or should a forex daily halt also halt crypto?

- If **independent**: Prefix the key (`fx:daily_halt` and `lighter:daily_halt`) and update each domain's task to check only its own key.
- If **shared halt is desired**: Keep the key name but document it explicitly as a cross-domain signal. After separation, ensure both Django settings point to the same Redis DB1.

**Recommendation:** Keep the shared halt for now (it's a safety feature). Document it explicitly. Rename to `global_daily_halt` (no namespace) to make the cross-domain intent obvious.

### Redis separation (future state)

If you want full Redis isolation:

```yaml
redis-forex:
  image: redis:6
  container_name: redis-forex
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
  # Used by: django-forex, celery-forex, celery-beat-forex
  # CELERY_BROKER_URL=redis://redis-forex:6379/0

redis-crypto:
  image: redis:6
  container_name: redis-crypto
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
  # Used by: django-crypto, celery-crypto, celery-beat-crypto
  # CRYPTO_CELERY_BROKER_URL=redis://redis-crypto:6379/0
```

The `global_daily_halt` cross-signal would then need to be replicated between Redis instances (e.g., via a small Celery task that copies the key, or by accepting the signal only flows one way).

**Recommendation for Phase 4:** Keep one Redis instance. The namespace separation is already good. Only split Redis if memory pressure becomes a problem or you move to separate physical hosts.

---

## Phase 5: Independent docker-compose Files or Profiles (OPTIONAL — future state)

**What:** Allow `docker compose --profile forex up` and `docker compose --profile crypto up` independently.

### Option A — Docker Compose profiles (simplest)

Add `profiles:` to each service in the existing `docker-compose.yml`:

```yaml
celery-forex:
  profiles: ["forex", "all"]

celery-crypto:
  profiles: ["crypto", "all"]

django-forex:
  profiles: ["forex", "all"]

django-crypto:
  profiles: ["crypto", "all"]

postgres:
  profiles: ["forex", "crypto", "all"]  # shared

redis:
  profiles: ["forex", "crypto", "all"]  # shared
```

Usage:
```bash
docker compose --profile crypto up -d     # only crypto stack
docker compose --profile forex up -d      # only forex stack
docker compose --profile all up -d        # everything
```

### Option B — Separate docker-compose files

```
docker-compose.yml              # shared: postgres, redis, traefik
docker-compose.forex.yml        # django-forex, celery-forex, celery-beat-forex, mt5
docker-compose.crypto.yml       # django-crypto, celery-crypto, celery-beat-crypto
```

Usage:
```bash
docker compose -f docker-compose.yml -f docker-compose.forex.yml up -d
docker compose -f docker-compose.yml -f docker-compose.crypto.yml up -d
```

**Recommendation:** Option A (profiles) for the current single-host setup. Option B if you ever move to separate machines.

---

## Risk Register

| Risk | Severity | Phase | Mitigation |
|------|----------|-------|------------|
| Forex trailing-stop starved by crypto hang | HIGH | Current state | Fixed by Phase 1 (separate workers) |
| Rebuilding celery kills forex trailing-stop during redeploy | HIGH | Current state | Fixed by Phase 1 |
| `cvd_entry.py` breaks if `app.nexus` not installed | MEDIUM | Phase 3 | Use shared DB approach (Option 3) initially |
| `global_daily_halt` not propagated after Redis split | MEDIUM | Phase 4 | Keep shared Redis or implement cross-instance signal |
| Beat restart briefly interrupts both domains' scheduling | LOW | Current state | Fixed by Phase 2; acceptable gap <1s |
| Dashboard breaks when API endpoint URLs change | MEDIUM | Phase 3 | Update `VITE_API_URL` env vars; can run both Django instances simultaneously during transition |
| Memory pressure from 2 Django + 2 Celery | LOW | Phase 3 | django-crypto can run with 2 workers (low traffic); total increase ~512MB |
| Migration conflicts if both Django instances run manage.py migrate | MEDIUM | Phase 3 | Run migrations only from django-forex; django-crypto is read-only for nexus tables |
| `ml_models/` volume contention | LOW | All phases | Forex and crypto write different files; concurrent writes to different paths are safe |

---

## Shared Dependencies Summary

These are things that BOTH domains need and must remain shared or explicitly duplicated:

| Dependency | Shared or Separate after full split |
|-----------|-------------------------------------|
| PostgreSQL instance | Shared (same server, same database) |
| Redis instance | Shared (different key namespaces) |
| Celery broker (Redis DB0) | Shared, but named queues route to domain workers |
| Django cache (Redis DB1) | Shared, namespaced |
| `app/quant/engine/` (bar_builder, indicators) | Shared code — both domains use these |
| `app/quant/algorithms/lighter/` | Crypto domain code, lives under quant/ but belongs to crypto |
| `app/quant/ml/crypto_features.py` | Crypto domain code in forex module — migrate to `app.crypto.ml` in future |
| `app/nexus.models.CustomStrategy` | Forex model used by crypto (cvd_entry.py:134) — decouple in Phase 3 |
| `ml_models/` Docker volume | Shared volume, separate file paths |
| Traefik | Shared reverse proxy |
| `ws_streamer.py` (macOS, native) | Already separate, not in Docker |

---

## Recommended Execution Order

### Week 1 — Phase 1 (do now, while bot is running)

1. Update `CELERY_TASK_ROUTES` in `settings.py` — add `crypto-critical` and `crypto-analysis` queues
2. Add `celery-crypto` service to `docker-compose.yml`
3. Update `celery` (forex) command to exclude crypto queues
4. Deploy: `docker compose up -d celery-crypto && docker compose restart celery celery-beat`
5. Verify with `celery inspect active_queues` on both workers

**This alone achieves the primary goal**: forex trailing-stop is completely isolated from crypto task failures or restarts.

### Week 2 — Phase 2 (optional but clean)

Split beat schedules using settings module override. Low risk, low reward unless you restart beat frequently.

### Month 2 — Phase 3 (after paper trading run ends Mar 31)

Separate Django instances. Do NOT do this while paper trading is active — it risks disrupting the API serving dashboard polling. Wait for a maintenance window.

### Month 3 — Phase 4 + 5 (if needed)

Docker Compose profiles and Redis separation only if you're adding more infrastructure (e.g., separate server for crypto, dedicated ML training box running its own Redis).

---

## Pre-Separation Safety Checklist

Before any restart:
```bash
# Check open positions (broker holds them server-side but confirm)
docker exec django python3 -c "from app.utils.api.positions import get_positions; print(get_positions())"

# Confirm celery-crypto picks up crypto queues correctly
docker exec celery-crypto celery -A app inspect active_queues

# Confirm forex celery no longer sees crypto queues
docker exec celery celery -A app inspect active_queues

# Confirm beat routes tasks correctly (check task routing in a dry run)
docker exec celery-beat celery -A app inspect scheduled
```

---

## What Can Be Done Incrementally vs Big Bang

| Change | Incremental | Big Bang | Notes |
|--------|------------|----------|-------|
| Add `celery-crypto` worker | Yes | — | Zero downtime; old worker keeps running until new one is up |
| Update task routes in settings | Yes | — | Apply while both workers run; tasks drain naturally |
| Split beat schedules | Yes | — | Start new beat, stop old one; <1s gap |
| Separate Django instances | Partial | For URL changes | Can run both simultaneously; switch DNS/Traefik atomically |
| Split `ml_models/` volume | No | Yes | Requires stopping both containers, copying files, remounting |
| Split Redis instances | No | Yes | All cache keys lost on switch; bot paused during migration |
| Decouple `cvd_entry.py` ← nexus | Yes | — | Code change + deploy; takes effect next task execution |
| Move `app/quant/ml/crypto_*` to `app/crypto/ml/` | Yes | — | Refactor during a maintenance window, update all imports |

The big insight is that **Phase 1 is entirely incremental and zero-downtime**, and it delivers 90% of the isolation benefit. Phases 2–5 are refinements that can wait for the right maintenance window.

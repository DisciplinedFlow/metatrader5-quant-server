# K3s Deployment — MT5 Quant Server

Production single-VM K3s manifests, derived from the actual `docker-compose.yml`
(the source of truth for how this platform runs), cross-referenced against the
ChatGPT proposal (`mt5_k3s_deployment.md`).

## Quick start

```bash
# On an amd64 VM with k3s + docker installed:
cp .env.example .env        # fill in real credentials and domains
k8s/scripts/build-images.sh # build mt5/django/dashboard, import into k3s
k8s/scripts/deploy.sh       # secret from .env + all manifests + ingress
kubectl -n mt5-quant get pods -w
```

Pod startup order resolves itself: django's migrate init-container waits on
postgres, celery crashes/restarts until redis+django are up, MT5's startup
probe allows ~10 min for Wine + terminal install on first boot (persisted in
the `mt5-config` PVC afterwards).

## Cross-reference: ChatGPT proposal vs this codebase

The proposal was a reasonable generic skeleton, but it was written without
reading the code. What was wrong or missing, and what this deployment does
instead:

| # | ChatGPT proposal | Reality in codebase | Resolution |
|---|---|---|---|
| 1 | **No Celery Beat at all** | Beat *is* the platform: entry algo (60s), trailing stops (15s), close detection (15s), regime scans, orchestrator, ML retrain | `celery-beat` Deployment, 1 replica, Recreate — two beats would double-fire live trades |
| 2 | `celery -A core worker -Q execution` / `-Q ml` | App module is `app`; queues are `default,critical,analysis`; worker pod also runs `manage.py tick_consumer` (redis db 2) | Exact compose command replicated in `celery.yaml` |
| 3 | `celery-execution` with **replicas: 2** | Duplicate workers + tick consumers = duplicate orders on a live broker account | replicas: 1, strategy: Recreate |
| 4 | CronJob running `python training/train.py` every 30 min | `training/` lives at repo root, **not in the django image**; retraining already runs in-app via beat task `run_ml_retrain` | CronJob dropped |
| 5 | MT5 Deployment: no Service, no ports, no volume, no resources | Flask API :5001 + KasmVNC :3000; Wine prefix in `/config` is stateful; needs 4Gi/2cpu; amd64-only | Service `mt5` (name load-bearing: `MT5_API_URL=http://mt5:5001`), `mt5-config` PVC, limits, startup probe |
| 6 | Dashboard absent | Vue 3 SPA behind nginx that proxies `/api/mt5/` and `/api/django/` | `dashboard.yaml` with a K8s-adapted nginx config (the baked-in one uses Docker's `resolver 127.0.0.11`) |
| 7 | `redis:7`, no persistence | `redis:6` with AOF + maxmemory policy; holds tick stream, beat schedule state, HMM cache | Matching args + `redis-data` PVC |
| 8 | 3 namespaces (`trading-core`/`execution`/`intelligence`) | `.env` and dashboard nginx use bare hostnames (`redis`, `mt5`, `django`) — cross-namespace DNS breaks all of them | Single namespace `mt5-quant`; on one VM the split bought nothing |
| 9 | Secret with 5 hardcoded values | ~40 env vars incl. MT5 creds, ANTHROPIC_API_KEY | Secret `app-env` generated from `.env` at deploy time — never committed |
| 10 | Ingress for the Django API only | Four web surfaces: Django API, MT5 Flask API, VNC, dashboard | All four hosts, rendered from `.env` domains |
| 11 | No probes, no resource limits | Compose defines healthchecks + mem/cpu limits per service | Translated 1:1 to probes/resources |
| 12 | Shared volumes not addressed | `ml_models`, `quant-logs`, `static_volume` shared django↔celery | RWO PVCs — safe because single-node (all pods co-scheduled) |

## What's intentionally not here

- **Monitoring stack** (Prometheus/Grafana/Loki/AlertManager): on K8s, use
  `kube-prometheus-stack` + `loki-stack` Helm charts instead of porting the
  compose containers — you get node/container metrics and log collection for
  free, and can import the JSON dashboards from `monitoring/dashboards/`.
- **TLS**: K3s' bundled Traefik has no ACME resolver configured. Install
  cert-manager (`helm install cert-manager jetstack/cert-manager`), create a
  ClusterIssuer, then uncomment the TLS blocks in `ingress.template.yaml`.
- **`~/.ssh` mount into celery** (present in compose): mount a Secret of type
  `kubernetes.io/ssh-auth` if that workflow is still needed.

## Operational notes for a trading system

- `Recreate` everywhere that matters: mt5 (one broker session), celery
  (duplicate trades), celery-beat (duplicate schedules), django/redis/postgres
  (RWO volumes). Rolling updates are wrong for this workload.
- Upgrades: `build-images.sh v2 && kubectl -n mt5-quant set image ...` or
  re-run deploy.sh; expect a brief execution gap while pods restart —
  position trailing stops resume on the next 15s beat tick.
- The daily-loss halt, circuit breakers, and performance gates live in the
  app layer (see `research/IMPLEMENTATION_PLAN.md`) — Kubernetes adds
  process-level resilience, not trading-logic safety.

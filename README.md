# MT5 Quant Server

Containerized algorithmic trading platform built on MetaTrader 5, Django, and Docker.

## What it does

MT5 Quant Server runs MetaTrader 5 inside a Docker container via Wine, wraps it with a REST API, and layers on automated trading strategies, a web dashboard for manual trading, and a full monitoring stack. The platform currently runs a mean-reversion strategy across 13 forex and commodity pairs with automated trailing stops.

## Architecture

```
                   Traefik (reverse proxy + SSL)
                         |
        -----------------------------------------
        |           |            |              |
    MT5 Flask    Django      Dashboard       Grafana
    API :5001    :8000        :3080          :3001
        |           |            |
        |      PostgreSQL   (static SPA)
        |           |
        |      Redis + Celery
        |           |
    MetaTrader 5    |
    (Wine/Docker)   |
        |___________|
         strategy execution
```

| Service | Port | Description |
|---|---|---|
| MT5 Flask API | 5001 | REST wrapper around MetaTrader 5 -- market data, orders, positions, deal history |
| Django backend | 8000 | Trade persistence, quant algorithm orchestration, DRF API |
| Dashboard | 3080 | Vanilla JS SPA for charts, order placement, position management |
| PostgreSQL | 5432 | Trade data storage |
| Redis + Celery | 6379 | Background task scheduling for strategy execution (3 workers) |
| Traefik | 80/443 | Reverse proxy with automatic Let's Encrypt SSL |
| Prometheus | 9090 | Metrics collection (5s scrape interval) |
| Grafana | 3001 | Dashboards for node metrics, container metrics, logs, Traefik stats |
| Loki + Promtail | 3100 | Log aggregation from all containers |
| AlertManager | 9093 | Alerts for memory, disk, CPU, container restarts |
| cAdvisor | -- | Container resource usage metrics |
| Node Exporter | -- | Host system metrics |

## Trading strategies

### Mean reversion (Bollinger Bands)

The primary strategy uses a 20-period, 2-standard-deviation Bollinger Band indicator on 15-minute candles:

- **Entry**: When price crosses below the lower band, buy. When price crosses above the upper band, sell.
- **Pairs**: NG, BRN, WTI, XAGUSD, XAUUSD, XAUEUR, EURUSD, EURGBP, USDJPY, USDCAD, USDCHF, AUDUSD, NZDUSD
- **Position sizing**: $100 capital per trade at 200x leverage
- **Risk**: Stop-loss set to cap loss at 50% of capital ($50); take-profit at 50% of capital ($50)

### Automated trailing stops

A 16-step trailing stop system runs every 15 seconds. As profit grows, the stop-loss ratchets upward to lock in gains. For example, when profit reaches 1x capital ($100), the stop moves to lock in 0.75x ($75). At 4x ($400), it locks in 3.5x ($350).

### Execution schedule (Celery Beat)

| Task | Interval |
|---|---|
| Entry algorithm | 60 seconds |
| Trailing stop algorithm | 15 seconds |
| Close detection algorithm | 15 seconds |

## Dashboard

The web dashboard at port 3080 provides five views:

- **Overview** -- Open position count, total P&L, market tick data, positions table (auto-refreshes every 5s)
- **Positions** -- Active positions with per-row close/modify actions and a "close all" button
- **Order** -- Manual market order form with live bid/ask preview, configurable SL/TP
- **History** -- Deal and order lookup by ticket, deal history by position with date range filtering
- **Chart** -- TradingView Lightweight Charts with candlesticks + volume overlay, configurable symbol/timeframe/bar count

## Quick start

```bash
git clone <repo-url>
cd metatrader5-quant-server-python
cp .env.example .env
# Edit .env with your MT5 credentials and domain names

docker network create traefik-public
docker compose up -d
```

For local development without SSL, the `docker-compose.override.yml` disables TLS and exposes services directly on their host ports.

## Environment variables

| Variable | Description |
|---|---|
| `CUSTOM_USER` | MT5 container login username |
| `PASSWORD` | MT5 container login password |
| `VNC_DOMAIN` | Domain for MT5 VNC web access |
| `API_DOMAIN` | Domain for MT5 Flask API |
| `DJANGO_DOMAIN` | Domain for Django REST API |
| `GRAFANA_DOMAIN` | Domain for Grafana dashboards |
| `TRAEFIK_DOMAIN` | Domain for Traefik dashboard |
| `TRAEFIK_USERNAME` | Traefik dashboard HTTP basic auth username |
| `ACME_EMAIL` | Email for Let's Encrypt certificate notifications |
| `POSTGRES_DB` | PostgreSQL database name |
| `POSTGRES_USER` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `MT5_API_URL` | Internal URL for Flask API (default: `http://mt5:5001`) |
| `CELERY_BROKER_URL` | Redis URL for Celery broker (default: `redis://redis:6379/0`) |
| `CELERY_RESULT_BACKEND` | Redis URL for Celery results (default: `redis://redis:6379/0`) |

Generate the Traefik hashed password before starting:

```bash
export TRAEFIK_HASHED_PASSWORD=$(openssl passwd -apr1 $PASSWORD)
```

## License

This project is licensed under the [MIT License](LICENSE.md).

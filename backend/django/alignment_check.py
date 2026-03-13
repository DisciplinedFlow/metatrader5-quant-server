"""Comprehensive alignment check: DB trades vs backtest vs ML."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

import django
django.setup()

from app.nexus.models import Trade, BacktestResult, StrategyConfig, MarketRegime
from django.db.models import Sum, Count, Avg
from datetime import datetime, timedelta
import json, redis

SEP = "=" * 60

# 1. TRADE DATABASE
print(f"\n{SEP}")
print("1. TRADE DATABASE")
print("-" * 40)
closed = Trade.objects.filter(close_time__isnull=False)
total = closed.count()
print(f"Total closed trades: {total}")

if total > 0:
    total_pnl = closed.aggregate(t=Sum("pnl"))["t"] or 0
    wins = closed.filter(pnl__gt=0).count()
    wr = wins / total * 100
    print(f"Overall: WR={wr:.1f}% PnL=${total_pnl:.2f}")

    # By strategy field
    strats = closed.values("strategy").annotate(
        cnt=Count("id"), total_pnl=Sum("pnl"),
    ).order_by("-total_pnl")
    print(f"\nBy Strategy:")
    for s in strats:
        name = s["strategy"] or "NONE"
        cnt = s["cnt"]
        pnl = s["total_pnl"] or 0
        w = closed.filter(strategy=s["strategy"], pnl__gt=0).count()
        wr2 = w / cnt * 100 if cnt > 0 else 0
        print(f"  {name}: {cnt}t WR={wr2:.1f}% PnL=${pnl:.2f}")

    # By symbol
    by_sym = closed.values("symbol").annotate(
        cnt=Count("id"), total_pnl=Sum("pnl"),
    ).order_by("-total_pnl")
    print(f"\nBy Symbol:")
    for s in by_sym:
        sym = s["symbol"]
        cnt = s["cnt"]
        pnl = s["total_pnl"] or 0
        w = closed.filter(symbol=sym, pnl__gt=0).count()
        wr2 = w / cnt * 100 if cnt > 0 else 0
        print(f"  {sym}: {cnt}t WR={wr2:.1f}% PnL=${pnl:.2f}")

    # Recent (last 7 days)
    week = datetime.now() - timedelta(days=7)
    recent = closed.filter(close_time__gte=week)
    rc = recent.count()
    if rc > 0:
        rpnl = recent.aggregate(t=Sum("pnl"))["t"] or 0
        rw = recent.filter(pnl__gt=0).count()
        rwr = rw / rc * 100
        print(f"\nLast 7 days: {rc}t WR={rwr:.1f}% PnL=${rpnl:.2f}")

# Open positions
open_trades = Trade.objects.filter(close_time__isnull=True)
print(f"\nOpen positions: {open_trades.count()}")
for t in open_trades:
    p = t.pnl or 0
    print(f"  {t.symbol} {t.type} vol={t.order_volume} id={t.transaction_broker_id} pnl=${p:.2f}")

# 2. BACKTEST RESULTS
print(f"\n{SEP}")
print("2. STORED BACKTEST RESULTS")
print("-" * 40)
results = BacktestResult.objects.all().order_by("-run_time")[:10]
for r in results:
    name = r.strategy.name if r.strategy else "?"
    src = r.data_source
    ts = r.run_time.strftime("%m/%d %H:%M")
    print(f"  {name}: {r.total_trades}t WR={r.win_rate:.1%} PnL={r.total_pnl:.4f} {'PASS' if r.passed else 'FAIL'} src={src} @ {ts}")

# 3. ML + HMM STATUS
print(f"\n{SEP}")
print("3. ML MODEL + HMM REGIME")
print("-" * 40)
try:
    rc = redis.Redis(host="redis", port=6379, db=0)
    ml_meta = rc.get("ml:model_meta")
    if ml_meta:
        meta = json.loads(ml_meta)
        ver = meta.get("version", "?")
        mt = meta.get("model_type", "?")
        acc = meta.get("accuracy", "?")
        tc = meta.get("trade_count", "?")
        ta = meta.get("trained_at", "?")
        print(f"ML Model: v{ver} {mt}")
        print(f"  Accuracy: {acc}")
        print(f"  Trade count: {tc}")
        print(f"  Trained at: {ta}")
        feats = meta.get("features", [])
        if feats:
            print(f"  Features ({len(feats)}): {', '.join(feats[:8])}...")
    else:
        print("ML Model: No model trained yet")

    print(f"\nHMM Regimes:")
    for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "AUDUSD"]:
        key = f"hmm:regime:{sym}:H1"
        data = rc.get(key)
        if data:
            d = json.loads(data)
            reg = d.get("regime", "?")
            conf = d.get("confidence", "?")
            print(f"  {sym}: {reg} conf={conf}")
        else:
            mr = MarketRegime.objects.filter(symbol=sym, timeframe="H1").first()
            if mr:
                print(f"  {sym}: {mr.regime} conf={mr.confidence:.2f} (DB fallback)")
            else:
                print(f"  {sym}: no regime data")

    ml_preds = rc.get("ml:predictions")
    if ml_preds:
        preds = json.loads(ml_preds)
        print(f"\nML Predictions: {len(preds)} entries")
        if isinstance(preds, dict):
            for k, v in list(preds.items())[:5]:
                print(f"  {k}: {v}")
    else:
        print(f"\nML Predictions: none cached")
except Exception as e:
    print(f"Redis/ML error: {e}")

# 4. ACTIVE STRATEGIES
print(f"\n{SEP}")
print("4. ACTIVE STRATEGIES")
print("-" * 40)
active = StrategyConfig.objects.filter(is_active=True)
for s in active:
    print(f"  [{s.id}] {s.name} max_pos={s.max_positions} regime={s.regime_filter}")

# 5. BOT CONTROL
print(f"\n{SEP}")
print("5. BOT CONTROL STATUS")
print("-" * 40)
try:
    rc2 = redis.Redis(host="redis", port=6379, db=0)
    for key_name, label in [
        ("bot:paused", "Bot paused"),
        ("ai_brain:enabled", "AI Brain"),
        ("daily_halt_active", "Daily halt"),
        ("circuit_breaker:active", "Circuit breaker"),
    ]:
        val = rc2.get(key_name)
        if val:
            print(f"  {label}: {val.decode()}")
        else:
            print(f"  {label}: not set")
except Exception as e:
    print(f"  Redis error: {e}")

# 6. ALIGNMENT SUMMARY
print(f"\n{SEP}")
print("6. ALIGNMENT ASSESSMENT")
print("-" * 40)

# Compare DB trade win rates vs backtest win rates for CVD strategies
cvd_trades = closed.filter(strategy__icontains="cvd")
cvd_count = cvd_trades.count()
if cvd_count > 0:
    cvd_pnl = cvd_trades.aggregate(t=Sum("pnl"))["t"] or 0
    cvd_wins = cvd_trades.filter(pnl__gt=0).count()
    cvd_wr = cvd_wins / cvd_count * 100
    print(f"DB CVD trades: {cvd_count}t WR={cvd_wr:.1f}% PnL=${cvd_pnl:.2f}")
else:
    print("DB CVD trades: none found")

# Check if backtest WR aligns with live WR
latest_bt = BacktestResult.objects.filter(
    strategy__name__icontains="CVD"
).order_by("-run_time").first()
if latest_bt:
    print(f"Latest CVD backtest: {latest_bt.total_trades}t WR={latest_bt.win_rate:.1%}")
    if cvd_count > 0:
        diff = abs(cvd_wr - latest_bt.win_rate * 100)
        status = "ALIGNED" if diff < 15 else "DIVERGENT"
        print(f"Live vs Backtest WR gap: {diff:.1f}pp -> {status}")

print(f"\n{SEP}")

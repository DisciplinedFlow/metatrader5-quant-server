import os
from collections import deque

from django.conf import settings
from django.db.models import Sum
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import CryptoPosition, CryptoTrade, CryptoBacktestResult
from .serializers import (
    CryptoPositionSerializer,
    CryptoTradeSerializer,
    CryptoBacktestResultSerializer,
    CryptoBacktestResultSummarySerializer,
)
from .bot_control import get_crypto_bot_status, set_crypto_bot_paused

import logging

logger = logging.getLogger('app.crypto')


class CryptoPositionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CryptoPosition.objects.all()
    serializer_class = CryptoPositionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        position_status = self.request.query_params.get('status')
        if position_status:
            qs = qs.filter(status=position_status.upper())
        return qs


class CryptoTradeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CryptoTrade.objects.all()
    serializer_class = CryptoTradeSerializer


class CryptoBotControlView(views.APIView):
    def get(self, request):
        return Response(get_crypto_bot_status())

    def post(self, request):
        paused = request.data.get('paused')
        if paused is None:
            return Response({'error': 'paused field required'}, status=status.HTTP_400_BAD_REQUEST)
        set_crypto_bot_paused(bool(paused))
        bot_status = get_crypto_bot_status()

        # Sync lighter proxy in-memory flag: paused → standby, unpaused → active
        self._sync_lighter_proxy(active=not bool(paused))

        try:
            from app.ws.publish import publish_bot_status
            publish_bot_status(bot_status)
        except Exception:
            pass
        return Response(bot_status)

    @staticmethod
    def _sync_lighter_proxy(active: bool):
        """Sync the lighter signer proxy state with bot pause. Scoped to port 5555 only."""
        import requests as _requests
        proxy_url = os.environ.get('LIGHTER_SIGNER_PROXY_URL', 'http://host.docker.internal:5555')
        try:
            _requests.post(f'{proxy_url}/toggle', json={'active': active}, timeout=2)
        except Exception:
            pass  # Proxy may be offline — not critical
        # Also sync Django cache flag so entry_algorithm() respects pause
        try:
            from django.core.cache import cache
            if active:
                cache.delete('lighter:disabled')
            else:
                cache.set('lighter:disabled', True, timeout=None)
        except Exception:
            pass


class CryptoLogsView(views.APIView):
    LOG_FILE = os.path.join(settings.BASE_DIR, 'logs', 'crypto.log')

    def get(self, request):
        lines = min(int(request.query_params.get('lines', 200)), 2000)
        try:
            with open(self.LOG_FILE, 'r') as f:
                tail = deque(f, maxlen=lines)
            return Response({'logs': list(tail)})
        except FileNotFoundError:
            return Response({'logs': []})


class CryptoBacktestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CryptoBacktestResult.objects.all()
    serializer_class = CryptoBacktestResultSummarySerializer

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CryptoBacktestResultSerializer
        return CryptoBacktestResultSummarySerializer

    @action(detail=False, methods=['post'], url_path='run')
    def run_backtest(self, request):
        from .tasks import run_crypto_backtest
        run_crypto_backtest.delay()
        return Response({'status': 'backtest started'}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'], url_path='run-all')
    def run_all_backtests(self, request):
        """Run all strategies across all symbols."""
        from .tasks import run_crypto_backtest_all
        symbols = request.data.get('symbols')  # optional override
        run_crypto_backtest_all.delay(symbols)
        from app.quant.algorithms.crypto.strategies import STRATEGY_REGISTRY
        return Response({
            'status': 'multi-strategy backtest started',
            'strategies': list(STRATEGY_REGISTRY.keys()),
        }, status=status.HTTP_202_ACCEPTED)


class CryptoStrategyConfigView(views.APIView):
    def get(self, request):
        from app.quant.algorithms.crypto.config import (
            CRYPTO_PAIRS, CRYPTO_CAPITAL_USD, CRYPTO_MAX_POSITIONS,
            CRYPTO_LEVERAGE, CRYPTO_STRATEGY, CRYPTO_FAST_MA,
            CRYPTO_SLOW_MA, CRYPTO_LOOKBACK, CRYPTO_MAX_POSITION_PCT,
        )
        return Response({
            'pairs': CRYPTO_PAIRS,
            'capital_usd': CRYPTO_CAPITAL_USD,
            'max_positions': CRYPTO_MAX_POSITIONS,
            'leverage': CRYPTO_LEVERAGE,
            'strategy': CRYPTO_STRATEGY,
            'fast_ma': CRYPTO_FAST_MA,
            'slow_ma': CRYPTO_SLOW_MA,
            'lookback': CRYPTO_LOOKBACK,
            'max_position_pct': CRYPTO_MAX_POSITION_PCT,
        })

    def post(self, request):
        import redis as _redis
        from django.conf import settings as _settings
        import json
        r = _redis.Redis.from_url(_settings.CELERY_BROKER_URL)
        data = {
            'pairs': request.data.get('pairs', ['BTC', 'ETH', 'SOL']),
            'capital_usd': float(request.data.get('capital_usd', 1000)),
            'max_positions': int(request.data.get('max_positions', 3)),
            'leverage': int(request.data.get('leverage', 1)),
            'strategy': request.data.get('strategy', 'momentum'),
            'fast_ma': int(request.data.get('fast_ma', 50)),
            'slow_ma': int(request.data.get('slow_ma', 200)),
            'lookback': int(request.data.get('lookback', 252)),
            'max_position_pct': float(request.data.get('max_position_pct', 0.10)),
        }
        r.set('crypto:strategy:config', json.dumps(data))
        return Response(data)


class CryptoDashboardView(views.APIView):
    def get(self, request):
        open_positions = CryptoPosition.objects.filter(status='OPEN').count()
        # pnl_usd already includes exit fee deduction (exit.py line 148)
        # Entry fees are tracked in CryptoTrade.fee for transparency
        gross_pnl = CryptoPosition.objects.filter(
            status='CLOSED', pnl_usd__isnull=False
        ).aggregate(total=Sum('pnl_usd'))['total'] or 0.0
        total_fees = CryptoTrade.objects.filter(fee__gt=0).aggregate(total=Sum('fee'))['total'] or 0.0
        total_pnl = gross_pnl  # pnl_usd is already net (exit fee deducted)
        open_positions_data = CryptoPosition.objects.filter(status='OPEN').values(
            'symbol', 'side', 'entry_price', 'size', 'pnl_usd'
        )
        return Response({
            'open_positions': open_positions,
            'total_pnl': total_pnl,
            'gross_pnl': gross_pnl,
            'total_fees': total_fees,
            'positions': list(open_positions_data),
        })


class CryptoFundingArbView(views.APIView):
    """Return latest funding rate arbitrage scan results from Redis."""

    def get(self, request):
        from app.quant.algorithms.crypto.funding_arb import get_latest_arb_data
        data = get_latest_arb_data()
        if data is None:
            return Response(
                {'error': 'No funding arb data available. Scan may not have run yet.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(data)


class HyperliquidControlView(views.APIView):
    """Enable/disable Hyperliquid trading via Redis flag."""

    def get(self, request):
        from django.core.cache import cache
        enabled = not cache.get('hyperliquid:disabled', False)
        return Response({'enabled': enabled})

    def post(self, request):
        from django.core.cache import cache
        enabled = request.data.get('enabled')
        if enabled is None:
            return Response({'error': 'enabled field required'}, status=status.HTTP_400_BAD_REQUEST)
        if bool(enabled):
            cache.delete('hyperliquid:disabled')
        else:
            cache.set('hyperliquid:disabled', True, timeout=None)
        return Response({
            'enabled': bool(enabled),
            'message': f"Hyperliquid trading {'enabled' if enabled else 'disabled'}",
        })


class LighterProxyView(views.APIView):
    """Check Lighter signer proxy health and enable/disable Lighter trading."""

    PROXY_URL = os.environ.get('LIGHTER_SIGNER_PROXY_URL', 'http://host.docker.internal:5555')

    def get(self, request):
        import requests as _requests
        from django.core.cache import cache

        enabled = not cache.get('lighter:disabled', False)
        proxy_status = 'offline'
        latency = None
        account = None
        equity = None
        available = None
        margin_used_pct = None
        unrealized_pnl = None
        positions = []

        try:
            start = __import__('time').time()
            resp = _requests.get(f'{self.PROXY_URL}/health', timeout=3)
            latency = round((__import__('time').time() - start) * 1000)
            if resp.ok:
                data = resp.json()
                proxy_status = 'connected'
                account = data.get('account')
        except _requests.ConnectionError:
            proxy_status = 'offline'
        except Exception:
            proxy_status = 'error'

        # Fetch account balance from Lighter API
        if proxy_status == 'connected':
            try:
                from app.quant.algorithms.lighter.client import get_account_info
                from app.quant.algorithms.lighter.config import LIGHTER_MARKETS
                id_to_sym = {v['id']: k for k, v in LIGHTER_MARKETS.items()}

                acct = get_account_info()
                a = acct.accounts[0] if hasattr(acct, 'accounts') and acct.accounts else None
                if a:
                    equity = float(a.cross_asset_value) if hasattr(a, 'cross_asset_value') else None
                    available = float(a.available_balance) if hasattr(a, 'available_balance') else None
                    collateral = float(a.collateral) if hasattr(a, 'collateral') else None
                    if equity and collateral:
                        margin_used_pct = round((1 - available / equity) * 100, 1) if equity > 0 else 0

                    # Get live positions
                    pnl_total = 0
                    for pos in (a.positions or []):
                        size = float(pos.position)
                        if size != 0:
                            mid = int(pos.market_id)
                            sym = id_to_sym.get(mid, f'?{mid}')
                            side = 'LONG' if size > 0 else 'SHORT'
                            entry = float(pos.avg_entry_price) if hasattr(pos, 'avg_entry_price') else 0
                            positions.append({
                                'symbol': sym,
                                'side': side,
                                'size': abs(size),
                                'entry_price': entry,
                            })
                    unrealized_pnl = round(equity - (collateral or equity), 2) if equity else 0
            except Exception as e:
                logger.debug(f"Lighter account fetch error: {e}")

        return Response({
            'proxy_status': proxy_status,
            'enabled': enabled,
            'latency_ms': latency,
            'account': account,
            'equity': equity,
            'available_balance': available,
            'margin_used_pct': margin_used_pct,
            'unrealized_pnl': unrealized_pnl,
            'positions': positions,
        })

    def post(self, request):
        from django.core.cache import cache

        enabled = request.data.get('enabled')
        if enabled is None:
            return Response({'error': 'enabled field required'}, status=status.HTTP_400_BAD_REQUEST)

        if bool(enabled):
            cache.delete('lighter:disabled')
        else:
            cache.set('lighter:disabled', True, timeout=None)

        return Response({
            'enabled': bool(enabled),
            'message': f"Lighter trading {'enabled' if enabled else 'disabled'}",
        })


class CryptoFundingRatesView(views.APIView):
    """Return funding rates as a flat array for the dashboard."""

    def get(self, request):
        from app.quant.algorithms.crypto.funding_arb import get_latest_arb_data
        data = get_latest_arb_data()
        if data is None:
            return Response([])
        rates = data.get('rates', {})
        result = []
        for symbol, info in rates.items():
            result.append({
                'symbol': symbol,
                'hyperliquid': info.get('hyperliquid_rate'),
                'lighter': info.get('lighter_rate'),
            })
        return Response(result)


class CryptoWalletView(views.APIView):
    """Live wallet data from Hyperliquid: prices, account state, on-chain positions."""

    TRACKED_COINS = ['BTC', 'ETH', 'SOL', 'AVAX', 'DOGE', 'ARB', 'MATIC', 'LINK', 'OP', 'SUI']

    def get(self, request):
        from app.quant.algorithms.crypto.config import HYPERLIQUID_WALLET_ADDRESS
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        if not HYPERLIQUID_WALLET_ADDRESS:
            return Response({'error': 'HYPERLIQUID_WALLET_ADDRESS not configured'}, status=400)

        try:
            info = Info(constants.MAINNET_API_URL, skip_ws=True)

            # Fetch prices and account state in parallel-ish (sequential but fast)
            all_mids = info.all_mids()
            user_state = info.user_state(HYPERLIQUID_WALLET_ADDRESS)

            # Build price list for tracked coins
            prices = []
            for coin in self.TRACKED_COINS:
                mid = all_mids.get(coin)
                if mid:
                    prices.append({'coin': coin, 'price': float(mid)})

            # Parse account state
            margin = user_state.get('marginSummary', {})
            positions = []
            for pos in user_state.get('assetPositions', []):
                p = pos.get('position', {})
                size = float(p.get('szi', 0))
                if size != 0:
                    positions.append({
                        'coin': p.get('coin'),
                        'size': size,
                        'side': 'LONG' if size > 0 else 'SHORT',
                        'entry_price': float(p.get('entryPx', 0)),
                        'mark_price': float(all_mids.get(p.get('coin'), 0)),
                        'unrealized_pnl': float(p.get('unrealizedPnl', 0)),
                        'margin_used': float(p.get('marginUsed', 0)),
                        'leverage': p.get('leverage', {}).get('value', 1),
                    })

            return Response({
                'wallet_address': HYPERLIQUID_WALLET_ADDRESS,
                'account_value': float(margin.get('accountValue', 0)),
                'total_margin_used': float(margin.get('totalMarginUsed', 0)),
                'total_ntl_pos': float(margin.get('totalNtlPos', 0)),
                'withdrawable': float(user_state.get('withdrawable', 0)),
                'positions': positions,
                'prices': prices,
            })
        except Exception as e:
            logger.error(f"Wallet data error: {e}")
            return Response({'error': str(e)}, status=500)


class CryptoMLStatsView(views.APIView):
    """Live crypto ML pipeline stats from training data + DB."""

    def get(self, request):
        import json as _json

        # Read training data JSONL
        ml_file = '/app/ml_models/crypto_training_data/trades.jsonl'
        training_trades = []
        try:
            with open(ml_file) as f:
                for line in f:
                    training_trades.append(_json.loads(line))
        except FileNotFoundError:
            pass

        # Stats from training data
        total = len(training_trades)
        wins = sum(1 for t in training_trades if t.get('won'))
        losses = total - wins
        win_rate = round(wins / total * 100, 1) if total else 0
        net_pnl = round(sum(t.get('pnl', 0) for t in training_trades), 4)
        avg_duration = round(sum(t.get('duration_min', 0) for t in training_trades) / total, 1) if total else 0

        # Per-symbol breakdown
        by_symbol = {}
        by_strategy = {}
        for t in training_trades:
            sym = t.get('symbol', '?')
            strat = t.get('strategy', '?')
            for group, key in [(by_symbol, sym), (by_strategy, strat)]:
                if key not in group:
                    group[key] = {'wins': 0, 'losses': 0, 'pnl': 0}
                group[key]['pnl'] += t.get('pnl', 0)
                if t.get('won'):
                    group[key]['wins'] += 1
                else:
                    group[key]['losses'] += 1

        # Find best symbol and strategy
        best_symbol = max(by_symbol, key=lambda s: by_symbol[s]['pnl']) if by_symbol else '-'
        best_strategy = max(by_strategy, key=lambda s: by_strategy[s]['wins'] / max(by_strategy[s]['wins'] + by_strategy[s]['losses'], 1)) if by_strategy else '-'

        # DB stats (current session)
        from .models import CryptoPosition
        from django.db.models import Sum
        db_closed = CryptoPosition.objects.filter(status='CLOSED')
        db_total = db_closed.count()
        db_wins = db_closed.filter(pnl_usd__gt=0).count()
        db_pnl = db_closed.aggregate(s=Sum('pnl_usd'))['s'] or 0

        return Response({
            'training': {
                'total': total,
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'net_pnl': net_pnl,
                'avg_duration_min': avg_duration,
                'by_symbol': by_symbol,
                'by_strategy': by_strategy,
                'best_symbol': best_symbol,
                'best_strategy': best_strategy,
                'target': 200,
                'progress_pct': round(total / 200 * 100, 1),
            },
            'session': {
                'total': db_total,
                'wins': db_wins,
                'losses': db_total - db_wins,
                'win_rate': round(db_wins / db_total * 100, 1) if db_total else 0,
                'net_pnl': round(db_pnl, 4),
            },
            'features': ['rsi2', 'ema50', 'trend', 'funding_mult', 'flow_mult',
                         'session_hour', 'day_of_week', 'leverage', 'position_usd'],
            'model_ready': total >= 200,
        })


class CryptoMLStatusView(views.APIView):
    """Crypto ML pipeline status — mirrors forex MLStatusView structure."""

    FEATURES = ['rsi2', 'ema50', 'trend', 'funding_mult', 'flow_mult',
                'session_hour', 'day_of_week', 'leverage', 'position_usd']
    ML_FILE = '/app/ml_models/crypto_training_data/trades.jsonl'
    MODEL_FILE = '/app/ml_models/crypto_model.joblib'

    @staticmethod
    def _safe_float(val):
        if val is None:
            return None
        import math
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f

    def get(self, request):
        import json as _json

        # ── Active model info ──
        model_info = None
        try:
            import joblib
            meta_path = self.MODEL_FILE.replace('.joblib', '_meta.json')
            model_exists = os.path.exists(self.MODEL_FILE)
            if model_exists:
                sf = self._safe_float
                meta = {}
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        meta = _json.load(f)

                # Try to extract feature importance from the model itself
                feature_importance = {}
                try:
                    model = joblib.load(self.MODEL_FILE)
                    importances = getattr(model, 'feature_importances_', None)
                    if importances is not None:
                        feature_importance = {
                            name: sf(float(imp))
                            for name, imp in zip(self.FEATURES, importances)
                        }
                except Exception:
                    feature_importance = meta.get('feature_importance', {})

                model_info = {
                    'version': meta.get('version', 'v1'),
                    'model_type': meta.get('model_type', 'XGBoost'),
                    'trade_count': meta.get('trade_count', 0),
                    'accuracy': sf(meta.get('accuracy')),
                    'cv_accuracy': sf(meta.get('cv_accuracy')),
                    'cv_std': sf(meta.get('cv_std')),
                    'walk_forward_accuracy': sf(meta.get('walk_forward_accuracy')),
                    'precision': sf(meta.get('precision')),
                    'recall': sf(meta.get('recall')),
                    'f1_score': sf(meta.get('f1_score')),
                    'feature_importance': feature_importance,
                    'shap_summary': meta.get('shap_summary', []),
                    'learning_curve': meta.get('learning_curve'),
                    'win_rate_baseline': sf(meta.get('win_rate_baseline')),
                    'trained_at': meta.get('trained_at'),
                }
        except Exception:
            pass

        # ── Training data stats (from JSONL) ──
        training_trades = []
        try:
            with open(self.ML_FILE) as f:
                for line in f:
                    training_trades.append(_json.loads(line))
        except FileNotFoundError:
            pass

        total = len(training_trades)
        wins = sum(1 for t in training_trades if t.get('won'))
        losses = total - wins
        win_rate = round(wins / total * 100, 1) if total else 0
        net_pnl = round(sum(t.get('pnl', 0) for t in training_trades), 4)
        avg_duration = round(
            sum(t.get('duration_min', 0) for t in training_trades) / total, 1
        ) if total else 0

        by_symbol = {}
        by_strategy = {}
        for t in training_trades:
            sym = t.get('symbol', '?')
            strat = t.get('strategy', '?')
            for group, key in [(by_symbol, sym), (by_strategy, strat)]:
                if key not in group:
                    group[key] = {'wins': 0, 'losses': 0, 'pnl': 0}
                group[key]['pnl'] += t.get('pnl', 0)
                if t.get('won'):
                    group[key]['wins'] += 1
                else:
                    group[key]['losses'] += 1

        best_symbol = max(by_symbol, key=lambda s: by_symbol[s]['pnl']) if by_symbol else '-'
        best_strategy = max(
            by_strategy,
            key=lambda s: by_strategy[s]['wins'] / max(by_strategy[s]['wins'] + by_strategy[s]['losses'], 1)
        ) if by_strategy else '-'

        # ── Feature stats (count labeled / unlabeled from JSONL) ──
        labeled = sum(1 for t in training_trades if t.get('won') is not None)
        ml_rejected = sum(1 for t in training_trades if not t.get('ml_accepted', True))

        # ── Predictions from recent closed positions ──
        from .models import CryptoPosition
        predictions = []
        recent = CryptoPosition.objects.filter(status='CLOSED').order_by('-closed_at')[:50]
        for pos in recent:
            predictions.append({
                'symbol': pos.symbol,
                'direction': pos.side,
                'score': None,  # no per-trade ML score stored yet
                'actual_win': pos.pnl_usd > 0 if pos.pnl_usd is not None else None,
                'pnl': round(pos.pnl_usd, 4) if pos.pnl_usd else 0,
                'close_reason': pos.close_reason,
                'timestamp': pos.closed_at.isoformat() if pos.closed_at else None,
            })

        # ── Model history (none yet — placeholder) ──
        model_history = []
        if model_info:
            model_history.append({
                'version': model_info['version'],
                'model_type': model_info['model_type'],
                'trade_count': model_info['trade_count'],
                'accuracy': model_info['accuracy'],
                'cv_accuracy': model_info['cv_accuracy'],
                'walk_forward_accuracy': model_info['walk_forward_accuracy'],
                'trained_at': model_info['trained_at'],
                'is_active': True,
            })

        # ── DB session stats ──
        from django.db.models import Sum
        db_closed = CryptoPosition.objects.filter(status='CLOSED')
        db_total = db_closed.count()
        db_wins = db_closed.filter(pnl_usd__gt=0).count()
        db_pnl = db_closed.aggregate(s=Sum('pnl_usd'))['s'] or 0

        return Response({
            'active_model': model_info,
            'features': {
                'total': total,
                'labeled': labeled,
                'wins': wins,
                'losses': losses,
                'ml_rejected': ml_rejected,
                'unlabeled': total - labeled,
            },
            'predictions': predictions,
            'model_history': model_history,
            'training': {
                'total': total,
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'net_pnl': net_pnl,
                'avg_duration_min': avg_duration,
                'by_symbol': {k: {sk: round(sv, 4) if isinstance(sv, float) else sv
                                  for sk, sv in v.items()} for k, v in by_symbol.items()},
                'by_strategy': {k: {sk: round(sv, 4) if isinstance(sv, float) else sv
                                    for sk, sv in v.items()} for k, v in by_strategy.items()},
                'best_symbol': best_symbol,
                'best_strategy': best_strategy,
                'target': 200,
                'progress_pct': round(total / 200 * 100, 1),
            },
            'session': {
                'total': db_total,
                'wins': db_wins,
                'losses': db_total - db_wins,
                'win_rate': round(db_wins / db_total * 100, 1) if db_total else 0,
                'net_pnl': round(float(db_pnl), 4),
            },
        })


class CryptoMLPredictionsView(views.APIView):
    """Recent crypto ML predictions with outcomes."""

    def get(self, request):
        from .models import CryptoPosition
        limit = int(request.query_params.get('limit', 50))

        positions = CryptoPosition.objects.filter(status='CLOSED').order_by('-closed_at')[:limit]
        data = []
        for pos in positions:
            data.append({
                'trade_id': pos.id,
                'symbol': pos.symbol,
                'type': pos.side,
                'ml_score': None,  # crypto doesn't store per-trade ML score yet
                'ml_accepted': True,
                'actual_win': pos.pnl_usd > 0 if pos.pnl_usd is not None else None,
                'pnl': round(pos.pnl_usd, 4) if pos.pnl_usd else 0,
                'entry_time': pos.opened_at.isoformat() if pos.opened_at else None,
                'close_time': pos.closed_at.isoformat() if pos.closed_at else None,
                'strategy': pos.entry_signal,
            })

        return Response(data)


class LighterAPITradesView(views.APIView):
    """Trade history pulled directly from the Lighter API — source of truth."""

    PROXY_URL = os.environ.get('LIGHTER_SIGNER_PROXY_URL', 'http://host.docker.internal:5555')
    ACCOUNT_INDEX = int(os.environ.get('LIGHTER_ACCOUNT_INDEX', '718566'))
    # Clean slate: BTC/ETH removed, bot restarted with SOL,AVAX,LINK,DOGE,XAU only
    CLEAN_SLATE_TS = int(os.environ.get('LIGHTER_CLEAN_SLATE_TS', '1773947000'))  # ~2026-03-19 18:23 UTC

    MKT = {0: 'ETH', 1: 'BTC', 2: 'SOL', 3: 'DOGE', 7: 'XRP', 8: 'LINK',
           9: 'AVAX', 10: 'NEAR', 11: 'DOT', 12: 'TON', 16: 'SUI', 24: 'HYPE',
           25: 'BNB', 27: 'AAVE', 39: 'ADA', 48: 'PAXG', 50: 'ARB', 55: 'OP',
           92: 'XAU', 93: 'XAG', 96: 'EURUSD', 97: 'GBPUSD', 98: 'USDJPY',
           99: 'USDCHF', 100: 'USDCAD', 106: 'AUDUSD', 107: 'NZDUSD',
           110: 'NVDA', 112: 'TSLA', 113: 'AAPL', 114: 'AMZN', 115: 'MSFT',
           116: 'GOOGL', 117: 'META', 128: 'SPY', 129: 'QQQ', 145: 'WTI'}

    def get(self, request):
        import requests as _requests

        try:
            resp = _requests.get(f'{self.PROXY_URL}/trades?limit=100', timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except _requests.ConnectionError:
            return Response({'error': 'Lighter proxy offline'}, status=503)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

        fills = data.get('trades', [])
        if not fills:
            return Response({'error': data.get('message', 'No fills returned')}, status=400)

        fills.reverse()  # oldest first
        positions = self._reconstruct_positions(fills)

        all_trades = positions
        clean_slate = [t for t in positions if t['closed_ts'] >= self.CLEAN_SLATE_TS * 1000]

        return Response({
            'all': self._build_stats(all_trades),
            'clean_slate': self._build_stats(clean_slate),
            'clean_slate_since': self.CLEAN_SLATE_TS,
        })

    def _reconstruct_positions(self, fills):
        tracking = {}
        closed = []

        for fill in fills:
            mid = fill.get('market_id', -1)
            sym = self.MKT.get(mid, f'?{mid}')
            ts_ms = fill.get('timestamp', 0)
            price = float(fill.get('price', 0))
            size = float(fill.get('size', 0))
            usd = float(fill.get('usd_amount', 0))

            we_bid = fill.get('bid_account_id') == self.ACCOUNT_INDEX
            we_ask = fill.get('ask_account_id') == self.ACCOUNT_INDEX
            if we_bid:
                pnl_str = fill.get('bid_account_pnl', '')
            elif we_ask:
                pnl_str = fill.get('ask_account_pnl', '')
            else:
                continue

            pnl = float(pnl_str) if pnl_str else None

            if sym not in tracking:
                tracking[sym] = {'size': 0.0, 'cost': 0.0, 'opened_ts': None}

            trk = tracking[sym]

            if pnl is not None:
                side = 'SHORT' if we_bid else 'LONG'
                if trk['size'] > 0 and trk['cost'] > 0:
                    entry = trk['cost'] / trk['size']
                elif size > 0:
                    entry = price - (pnl / size) if side == 'LONG' else price + (pnl / size)
                else:
                    entry = price

                opened_ts = trk['opened_ts'] or (ts_ms - 60000)
                dur_s = (ts_ms - opened_ts) / 1000

                closed.append({
                    'symbol': sym,
                    'side': side,
                    'entry': round(entry, 6),
                    'close': price,
                    'size': trk['size'] or size,
                    'pnl': round(pnl, 6),
                    'duration_m': round(dur_s / 60),
                    'opened_ts': opened_ts,
                    'closed_ts': ts_ms,
                })
                tracking[sym] = {'size': 0.0, 'cost': 0.0, 'opened_ts': None}
            else:
                trk['size'] += size
                trk['cost'] += usd
                if trk['opened_ts'] is None:
                    trk['opened_ts'] = ts_ms

        return closed

    @staticmethod
    def _build_stats(trades):
        if not trades:
            return {'trades': [], 'total': 0, 'wins': 0, 'losses': 0,
                    'win_rate': 0, 'net_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                    'by_symbol': {}}

        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] <= 0]
        net_pnl = sum(t['pnl'] for t in trades)
        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0

        by_symbol = {}
        for t in trades:
            s = t['symbol']
            if s not in by_symbol:
                by_symbol[s] = {'wins': 0, 'losses': 0, 'pnl': 0}
            by_symbol[s]['pnl'] += t['pnl']
            if t['pnl'] > 0:
                by_symbol[s]['wins'] += 1
            else:
                by_symbol[s]['losses'] += 1

        return {
            'trades': sorted(trades, key=lambda t: t['closed_ts'], reverse=True),
            'total': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(trades) * 100, 1),
            'net_pnl': round(net_pnl, 4),
            'avg_win': round(avg_win, 4),
            'avg_loss': round(avg_loss, 4),
            'by_symbol': by_symbol,
        }

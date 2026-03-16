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
        return Response(get_crypto_bot_status())


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
        total_pnl = CryptoPosition.objects.filter(
            status='CLOSED', pnl_usd__isnull=False
        ).aggregate(total=Sum('pnl_usd'))['total'] or 0.0
        open_positions_data = CryptoPosition.objects.filter(status='OPEN').values(
            'symbol', 'side', 'entry_price', 'size', 'pnl_usd'
        )
        return Response({
            'open_positions': open_positions,
            'total_pnl': total_pnl,
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

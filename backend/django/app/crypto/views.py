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

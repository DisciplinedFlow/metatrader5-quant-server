import os
from collections import deque

from django.conf import settings
from django.db.models import Sum, Count
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import PolyMarket, PolyPosition, PolyTrade, PolyProbabilityLog, PolyBacktestResult
from .serializers import (
    PolyMarketSerializer,
    PolyPositionSerializer,
    PolyTradeSerializer,
    PolyProbabilityLogSerializer,
    PolyBacktestResultSerializer,
    PolyBacktestResultSummarySerializer,
)
from .bot_control import get_polymarket_bot_status, set_polymarket_bot_paused

import logging

logger = logging.getLogger('app.polymarket')


class PolyMarketViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PolyMarket.objects.all()
    serializer_class = PolyMarketSerializer

    @action(detail=False, methods=['post'], url_path='sync')
    def sync(self, request):
        from .tasks import sync_polymarket_markets
        sync_polymarket_markets.delay()
        return Response({'status': 'sync task queued'}, status=status.HTTP_202_ACCEPTED)


class PolyPositionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PolyPosition.objects.all()
    serializer_class = PolyPositionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        position_status = self.request.query_params.get('status')
        if position_status:
            qs = qs.filter(status=position_status.upper())
        return qs


class PolyTradeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PolyTrade.objects.all()
    serializer_class = PolyTradeSerializer


class PolyBotControlView(views.APIView):
    def get(self, request):
        return Response(get_polymarket_bot_status())

    def post(self, request):
        paused = request.data.get('paused')
        if paused is None:
            return Response({'error': 'paused field required'}, status=status.HTTP_400_BAD_REQUEST)
        set_polymarket_bot_paused(bool(paused))
        return Response(get_polymarket_bot_status())


class PolyLogsView(views.APIView):
    LOG_FILE = os.path.join(settings.BASE_DIR, 'logs', 'polymarket.log')

    def get(self, request):
        lines = min(int(request.query_params.get('lines', 200)), 2000)
        try:
            with open(self.LOG_FILE, 'r') as f:
                tail = deque(f, maxlen=lines)
            return Response({'logs': list(tail)})
        except FileNotFoundError:
            return Response({'logs': []})


class PolyBacktestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PolyBacktestResult.objects.all()
    serializer_class = PolyBacktestResultSummarySerializer

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PolyBacktestResultSerializer
        return PolyBacktestResultSummarySerializer

    @action(detail=False, methods=['post'], url_path='run')
    def run_backtest(self, request):
        from .tasks import run_polymarket_backtest
        run_polymarket_backtest.delay()
        return Response({'status': 'backtest started'}, status=status.HTTP_202_ACCEPTED)


class PolyStrategyConfigView(views.APIView):
    """GET/POST the current strategy config (reads from env defaults, overridable)."""

    def get(self, request):
        from app.quant.algorithms.polymarket.config import (
            EV_THRESHOLD, KELLY_FRACTION, MAX_POSITIONS, CAPITAL_USD, STOP_LOSS_THRESHOLD,
        )
        return Response({
            'ev_threshold': EV_THRESHOLD,
            'kelly_fraction': KELLY_FRACTION,
            'max_positions': MAX_POSITIONS,
            'capital_usd': CAPITAL_USD,
            'stop_loss_threshold': abs(STOP_LOSS_THRESHOLD),
        })

    def post(self, request):
        # Store config overrides in Redis for runtime use
        import redis as _redis
        from django.conf import settings as _settings
        import json
        r = _redis.Redis.from_url(_settings.CELERY_BROKER_URL)
        data = {
            'ev_threshold': float(request.data.get('ev_threshold', 0.05)),
            'kelly_fraction': float(request.data.get('kelly_fraction', 0.15)),
            'max_positions': int(request.data.get('max_positions', 5)),
            'capital_usd': float(request.data.get('capital_usd', 500)),
            'stop_loss_threshold': float(request.data.get('stop_loss_threshold', 0.15)),
        }
        r.set('polymarket:strategy:config', json.dumps(data))
        return Response(data)


class PolyDashboardView(views.APIView):
    def get(self, request):
        open_positions = PolyPosition.objects.filter(status='OPEN').count()
        total_pnl = PolyPosition.objects.filter(
            status='CLOSED', pnl_usd__isnull=False
        ).aggregate(total=Sum('pnl_usd'))['total'] or 0.0
        markets_tracked = PolyMarket.objects.filter(is_active=True).count()
        return Response({
            'open_positions': open_positions,
            'total_pnl': total_pnl,
            'markets_tracked': markets_tracked,
        })

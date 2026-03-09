import os
from collections import deque

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Trade, TradeClosePricesMutation, StrategyConfig, BacktestResult, CustomStrategy
from .serializers import (
    TradeSerializer,
    TradeClosePricesMutationSerializer,
    StrategyConfigSerializer,
    BacktestResultSerializer,
    CustomStrategySerializer,
)
from .filters import TradeFilter
from app.utils.api.order import send_market_order, modify_sl_tp

class TradeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Trade.objects.all()
    serializer_class = TradeSerializer
    filterset_class = TradeFilter
    ordering_fields = ['entry_time', 'close_time', 'pnl', 'symbol']
    ordering = ['-entry_time']  # default ordering

    def get_queryset(self):
        # Ensure we prefetch the related mutations to avoid N+1 queries
        return Trade.objects.prefetch_related('close_prices_mutations').all()

class SendMarketOrderView(views.APIView):
    def post(self, request):
        data = request.data
        required_fields = ['symbol', 'volume', 'order_type']
        for field in required_fields:
            if field not in data:
                return Response({'error': f'Missing field: {field}'}, status=status.HTTP_400_BAD_REQUEST)

        symbol = data.get('symbol')
        volume = data.get('volume')
        order_type = data.get('order_type')
        sl = data.get('sl', 0.0)
        tp = data.get('tp', 0.0)
        deviation = data.get('deviation', 20)
        comment = data.get('comment', '')
        magic = data.get('magic', 0)
        type_filling = data.get('type_filling', '2')

        order_response = send_market_order(
            symbol=symbol,
            volume=volume,
            order_type=order_type,
            sl=sl,
            tp=tp,
            deviation=deviation,
            comment=comment,
            magic=magic,
            type_filling=type_filling
        )

        if not order_response:
            return Response({'error': 'Failed to send market order.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            trade = Trade.objects.get(symbol=symbol, entry_price=order_response['price'])
            trade_serializer = TradeSerializer(trade)

            mutations = trade.close_prices_mutations.all()
            mutations_serializer = TradeClosePricesMutationSerializer(mutations, many=True)

            return Response({
                'trade': trade_serializer.data,
                'mutations': mutations_serializer.data
            }, status=status.HTTP_201_CREATED)
        except Trade.DoesNotExist:
            return Response({'error': 'Trade created but not found in database.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ModifySLTPView(views.APIView):
    def post(self, request):
        data = request.data
        required_fields = ['id', 'ticket', 'stop_loss', 'take_profit']
        for field in required_fields:
            if field not in data:
                return Response({'error': f'Missing field: {field}'}, status=status.HTTP_400_BAD_REQUEST)

        id = data.get('id')
        ticket = data.get('ticket')
        stop_loss = data.get('stop_loss')
        take_profit = data.get('take_profit')

        modify_response = modify_sl_tp(
            id=id,
            ticket=ticket,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        if not modify_response:
            return Response({'error': 'Failed to modify SL/TP.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            mutation = TradeClosePricesMutation.objects.filter(trade__id=id).latest('mutation_time')
            mutation_serializer = TradeClosePricesMutationSerializer(mutation)

            return Response({'mutation': mutation_serializer.data}, status=status.HTTP_201_CREATED)
        except TradeClosePricesMutation.DoesNotExist:
            return Response({'error': 'Mutation created but not found in database.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogsView(views.APIView):
    """Return the last N lines of the quant algorithm log file."""

    LOG_FILE = os.path.join(settings.BASE_DIR, 'logs', 'quant.log')

    def get(self, request):
        lines = min(int(request.query_params.get('lines', 200)), 2000)
        try:
            with open(self.LOG_FILE, 'r') as f:
                tail = deque(f, maxlen=lines)
            return Response({'logs': list(tail)})
        except FileNotFoundError:
            return Response({'logs': []})


class StrategyViewSet(viewsets.ReadOnlyModelViewSet):
    """List built-in strategies with their latest backtest result."""
    queryset = StrategyConfig.objects.filter(custom_definition__isnull=True)
    serializer_class = StrategyConfigSerializer

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """Toggle a strategy's active state."""
        strategy = self.get_object()
        strategy.is_active = not strategy.is_active
        if strategy.is_active:
            strategy.last_activated = timezone.now()
        strategy.save()
        return Response(StrategyConfigSerializer(strategy).data)

    @action(detail=True, methods=['post'], url_path='backtest')
    def run_backtest(self, request, pk=None):
        """Trigger a backtest for this strategy on demand."""
        strategy = self.get_object()
        from app.quant.tasks import run_backtest as run_backtest_task
        run_backtest_task.delay(strategy_name=strategy.name)
        return Response({'status': 'Backtest started'}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='backtest-results')
    def backtest_results(self, request, pk=None):
        """List backtest history for a strategy."""
        strategy = self.get_object()
        results = BacktestResult.objects.filter(strategy=strategy).order_by('-run_time')[:20]
        return Response(BacktestResultSerializer(results, many=True).data)

    @action(detail=True, methods=['get'], url_path='backtest-results/(?P<result_id>[^/.]+)')
    def backtest_detail(self, request, pk=None, result_id=None):
        result = BacktestResult.objects.filter(strategy_id=pk, id=result_id).first()
        if not result:
            return Response({'error': 'Not found'}, status=404)
        return Response(BacktestResultSerializer(result).data)


class BotControlView(views.APIView):
    def get(self, request):
        from app.utils.bot_control import get_bot_status
        return Response(get_bot_status())

    def post(self, request):
        from app.utils.bot_control import set_bot_paused
        paused = request.data.get('paused', True)
        set_bot_paused(paused)
        return Response({'paused': paused})


class AIBrainControlView(views.APIView):
    """Toggle the AI Brain on/off and retrieve latest analysis."""

    def get(self, request):
        from app.quant.ai_bot_control import get_ai_brain_status
        return Response(get_ai_brain_status())

    def post(self, request):
        from app.quant.ai_bot_control import set_ai_brain_enabled, get_ai_brain_status
        enabled = request.data.get('enabled', False)
        set_ai_brain_enabled(enabled)
        # Optionally trigger an immediate analysis
        if enabled and request.data.get('run_now', False):
            from app.quant.tasks import run_ai_brain
            run_ai_brain.delay()
        return Response(get_ai_brain_status())


class AIBrainLogsView(views.APIView):
    """Return AI Brain log file."""

    LOG_FILE = os.path.join(settings.BASE_DIR, 'logs', 'ai_brain.log')

    def get(self, request):
        lines = min(int(request.query_params.get('lines', 200)), 2000)
        try:
            with open(self.LOG_FILE, 'r') as f:
                from collections import deque
                tail = deque(f, maxlen=lines)
            return Response({'logs': list(tail)})
        except FileNotFoundError:
            return Response({'logs': []})


class YahooDataView(views.APIView):
    def get(self, request):
        from app.utils.api.yahoo import fetch_yahoo_data
        symbol = request.query_params.get('symbol')
        period = request.query_params.get('period', '60d')
        interval = request.query_params.get('interval', '5m')
        if not symbol:
            return Response({'error': 'symbol required'}, status=status.HTTP_400_BAD_REQUEST)
        df = fetch_yahoo_data(symbol, period=period, interval=interval)
        if df is None or df.empty:
            return Response([])
        records = []
        for idx, row in df.iterrows():
            records.append({
                'time': idx.isoformat() if hasattr(idx, 'isoformat') else str(idx),
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
            })
        return Response(records)


class CustomStrategyViewSet(viewsets.ModelViewSet):
    queryset = CustomStrategy.objects.all()
    serializer_class = CustomStrategySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        domain = self.request.query_params.get('domain')
        if domain:
            qs = qs.filter(domain=domain.upper())
        return qs

    @action(detail=True, methods=['post'], url_path='backtest')
    def run_backtest(self, request, pk=None):
        custom = self.get_object()
        from app.quant.tasks import run_custom_backtest
        run_custom_backtest.delay(custom_strategy_id=custom.id)
        return Response({'status': 'Backtest started'}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """Activate a custom strategy — FOREX sets StrategyConfig, others write to Redis."""
        import redis
        import json
        custom = self.get_object()
        domain = custom.domain
        definition = custom.definition or {}

        if domain == 'FOREX':
            if not custom.strategy_config:
                return Response({'error': 'No StrategyConfig linked to this custom strategy'}, status=status.HTTP_400_BAD_REQUEST)
            custom.strategy_config.is_active = not custom.strategy_config.is_active
            if custom.strategy_config.is_active:
                custom.strategy_config.last_activated = timezone.now()
            custom.strategy_config.save()
            status_label = 'activated' if custom.strategy_config.is_active else 'deactivated'
            return Response({'status': status_label, 'domain': domain, 'strategy': custom.name})

        r = redis.Redis.from_url(settings.CACHES.get('default', {}).get('LOCATION', 'redis://redis:6379/0'))

        if domain == 'POLYMARKET':
            config = {
                'ev_threshold': definition.get('ev_threshold', 0.05),
                'kelly_fraction': definition.get('kelly_fraction', 0.15),
                'max_positions': definition.get('max_positions', 5),
                'capital_usd': definition.get('capital_usd', 500),
                'stop_loss_threshold': definition.get('stop_loss_threshold', 0.15),
            }
            r.set('polymarket:strategy:config', json.dumps(config))
        elif domain == 'CRYPTO':
            config = {
                'pairs': definition.get('pairs', ['BTC', 'ETH', 'SOL']),
                'capital_usd': definition.get('capital_usd', 1000),
                'leverage': definition.get('leverage', 1),
                'fast_ma': definition.get('fast_ma', 50),
                'slow_ma': definition.get('slow_ma', 200),
                'max_position_pct': definition.get('max_position_pct', 0.10),
            }
            r.set('crypto:strategy:config', json.dumps(config))
        else:
            return Response({'error': f'Activation not supported for domain: {domain}'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'status': 'activated', 'domain': domain})


class MarketPulseView(views.APIView):
    """Serve cached market pulse data (news + economic calendar)."""

    def get(self, request):
        news = cache.get('market_pulse:news', [])
        calendar = cache.get('market_pulse:calendar', [])
        return Response({
            'news': news,
            'calendar': calendar,
        })


class MarketRegimeView(views.APIView):
    """Return current market regime classification for all pairs."""

    def get(self, request):
        from .models import MarketRegime
        regimes = MarketRegime.objects.all().order_by('symbol')
        data = [
            {
                'symbol': r.symbol,
                'timeframe': r.timeframe,
                'regime': r.regime,
                'adx': r.adx,
                'bb_width': r.bb_width,
                'atr_ratio': r.atr_ratio,
                'confidence': r.confidence,
                'computed_at': r.computed_at.isoformat() if r.computed_at else None,
            }
            for r in regimes
        ]
        return Response(data)


class PairLocksView(views.APIView):
    """Return current pair locks (which pairs are locked by which strategies)."""

    def get(self, request):
        from .models import PairLock
        locks = PairLock.objects.select_related('strategy').all()
        data = [
            {
                'symbol': lock.symbol,
                'strategy': lock.strategy.name,
                'ticket': lock.ticket,
                'locked_at': lock.locked_at.isoformat() if lock.locked_at else None,
            }
            for lock in locks
        ]
        return Response(data)

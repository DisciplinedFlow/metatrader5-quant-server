import os
from collections import deque

from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Trade, TradeClosePricesMutation, StrategyConfig, BacktestResult
from .serializers import (
    TradeSerializer,
    TradeClosePricesMutationSerializer,
    StrategyConfigSerializer,
    BacktestResultSerializer,
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
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

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
    """List strategies with their latest backtest result."""
    queryset = StrategyConfig.objects.all()
    serializer_class = StrategyConfigSerializer

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """Activate a strategy (deactivates all others)."""
        strategy = self.get_object()
        StrategyConfig.objects.update(is_active=False)
        strategy.is_active = True
        strategy.last_activated = timezone.now()
        strategy.save()
        return Response(StrategyConfigSerializer(strategy).data)

    @action(detail=True, methods=['post'], url_path='backtest')
    def run_backtest(self, request, pk=None):
        """Trigger a backtest for this strategy on demand."""
        strategy = self.get_object()
        if strategy.name != 'SCALPING':
            return Response(
                {'error': 'Backtest is only supported for the SCALPING strategy.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from app.quant.tasks import run_backtest as run_backtest_task
        run_backtest_task.delay()
        return Response({'status': 'Backtest started'}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='backtest-results')
    def backtest_results(self, request, pk=None):
        """List backtest history for a strategy."""
        strategy = self.get_object()
        results = BacktestResult.objects.filter(strategy=strategy).order_by('-run_time')[:20]
        return Response(BacktestResultSerializer(results, many=True).data)

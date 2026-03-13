import json
import os
from collections import deque

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Trade, TradeClosePricesMutation, StrategyConfig, BacktestResult, CustomStrategy, MarketRegime
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
    pagination_class = None  # Return all trades — table handles scrolling
    ordering_fields = ['entry_time', 'close_time', 'pnl', 'symbol']
    ordering = ['-entry_time']  # default ordering

    def get_queryset(self):
        # select_related for FK (strategy_config accessed by serializer)
        # prefetch_related for reverse FK (close_prices_mutations)
        return (
            Trade.objects
            .select_related('strategy_config')
            .prefetch_related('close_prices_mutations')
            .all()
        )

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

    def get_queryset(self):
        # prefetch backtest_results to avoid N+1 in serializer's get_latest_backtest
        return (
            StrategyConfig.objects
            .filter(custom_definition__isnull=True)
            .prefetch_related('backtest_results')
        )

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
        # select_related for FK (strategy_config accessed by serializer for is_active)
        qs = CustomStrategy.objects.select_related('strategy_config')
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

        if domain == 'CRYPTO':
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


class ICTScanView(views.APIView):
    """Return cached ICT 5-step scanner results for the dashboard."""

    def get(self, request):
        results = cache.get('ict_scan_results', [])
        limit = int(request.query_params.get('limit', 10))
        return Response(results[:limit])


class MLStatusView(views.APIView):
    """ML learning pipeline status — model info, training data stats, predictions."""

    @staticmethod
    def _safe_float(val):
        """Convert to float, replacing NaN/inf with None for JSON safety."""
        if val is None:
            return None
        import math
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f

    def get(self, request):
        from .models import MLModel, TradeFeature

        # Active model info
        active_model = MLModel.objects.filter(is_active=True).first()
        model_info = None
        if active_model:
            # Separate SHAP summary and walk-forward accuracy from feature importance dict
            fi = active_model.feature_importance or {}
            shap_summary = fi.pop('_shap_summary', [])
            walk_forward_accuracy = fi.pop('_walk_forward_accuracy', None)
            sf = self._safe_float
            model_info = {
                'version': active_model.version,
                'model_type': active_model.model_type,
                'trade_count': active_model.trade_count,
                'accuracy': sf(active_model.accuracy),
                'cv_accuracy': sf(active_model.cv_accuracy),
                'cv_std': sf(active_model.cv_std),
                'walk_forward_accuracy': sf(walk_forward_accuracy),
                'precision': sf(active_model.precision),
                'recall': sf(active_model.recall),
                'f1_score': sf(active_model.f1_score),
                'feature_importance': fi,
                'shap_summary': shap_summary,
                'learning_curve': active_model.learning_curve,
                'win_rate_baseline': sf(active_model.win_rate_baseline),
                'trained_at': active_model.trained_at.isoformat() if active_model.trained_at else None,
            }

        # Feature stats
        total_features = TradeFeature.objects.count()
        labeled = TradeFeature.objects.filter(actual_win__isnull=False).count()
        wins = TradeFeature.objects.filter(actual_win=True).count()
        losses = TradeFeature.objects.filter(actual_win=False).count()
        ml_rejected = TradeFeature.objects.filter(ml_accepted=False).count()

        # LLM training data stats
        from app.quant.ml.data_collector import get_training_data_stats
        llm_stats = get_training_data_stats()

        # Model history — include walk-forward accuracy per model
        all_models = MLModel.objects.all()[:10]
        model_history = []
        for m in all_models:
            m_fi = m.feature_importance or {}
            wf_acc = m_fi.get('_walk_forward_accuracy', None)
            sf = self._safe_float
            model_history.append({
                'version': m.version,
                'model_type': m.model_type,
                'trade_count': m.trade_count,
                'accuracy': sf(m.accuracy),
                'cv_accuracy': sf(m.cv_accuracy),
                'walk_forward_accuracy': sf(wf_acc),
                'trained_at': m.trained_at.isoformat() if m.trained_at else None,
                'is_active': m.is_active,
            })

        return Response({
            'active_model': model_info,
            'features': {
                'total': total_features,
                'labeled': labeled,
                'wins': wins,
                'losses': losses,
                'ml_rejected': ml_rejected,
                'unlabeled': total_features - labeled,
            },
            'llm_training_data': llm_stats,
            'model_history': model_history,
        })


class MLBackfillLLMView(views.APIView):
    """Backfill LLM training data for closed trades missing examples."""

    def post(self, request):
        from .models import TradeFeature
        from app.quant.ml.data_collector import generate_training_example, save_training_example, get_training_data_stats

        # Get count of existing examples before backfill
        before = get_training_data_stats()

        labeled = TradeFeature.objects.filter(actual_win__isnull=False).select_related('trade')
        generated = 0
        skipped = 0
        for tf in labeled:
            example = generate_training_example(tf.trade, tf)
            if example:
                save_training_example(example)
                generated += 1
            else:
                skipped += 1

        after = get_training_data_stats()
        new_examples = after['total_examples'] - before['total_examples']

        return Response({
            'generated': generated,
            'skipped': skipped,
            'new_examples': new_examples,
            'stats': after,
        })


class MLPredictionsView(views.APIView):
    """Recent ML predictions with outcomes."""

    def get(self, request):
        from .models import TradeFeature
        limit = int(request.query_params.get('limit', 50))

        features = TradeFeature.objects.select_related('trade').order_by('-created_at')[:limit]
        data = []
        for tf in features:
            trade = tf.trade
            data.append({
                'trade_id': trade.id,
                'symbol': trade.symbol,
                'type': trade.type,
                'ml_score': tf.ml_score,
                'ml_accepted': tf.ml_accepted,
                'actual_win': tf.actual_win,
                'pnl': trade.pnl,
                'entry_time': trade.entry_time.isoformat() if trade.entry_time else None,
                'close_time': trade.close_time.isoformat() if trade.close_time else None,
                'strategy': trade.strategy,
            })

        return Response(data)


class ConfluenceScoreView(views.APIView):
    """Return confluence score distribution from recent trades.

    Reads TradeFeature.features_json to extract the confluence_score field
    and returns a histogram-style distribution plus band breakdown.
    """

    def get(self, request):
        from .models import TradeFeature

        limit = min(int(request.query_params.get('limit', 200)), 1000)

        features = (
            TradeFeature.objects
            .select_related('trade')
            .filter(trade__market_type='FOREX')
            .order_by('-created_at')[:limit]
        )

        # Extract confluence scores from features_json
        scores = []
        band_counts = {'skip': 0, 'reduced': 0, 'full': 0, 'enhanced': 0}
        for tf in features:
            fj = tf.features_json or {}
            cs = fj.get('confluence_score')
            if cs is not None:
                try:
                    cs = int(cs)
                except (TypeError, ValueError):
                    continue
                scores.append({
                    'score': cs,
                    'symbol': tf.trade.symbol,
                    'actual_win': tf.actual_win,
                    'pnl': tf.trade.pnl,
                    'entry_time': tf.trade.entry_time.isoformat() if tf.trade.entry_time else None,
                })
                # Classify into bands
                if cs <= 3:
                    band_counts['skip'] += 1
                elif cs <= 6:
                    band_counts['reduced'] += 1
                elif cs <= 8:
                    band_counts['full'] += 1
                else:
                    band_counts['enhanced'] += 1

        # Build distribution histogram (scores 0-11)
        distribution = {str(i): 0 for i in range(12)}
        for s in scores:
            key = str(min(s['score'], 11))
            distribution[key] = distribution.get(key, 0) + 1

        # Win rate per band
        band_wins = {'skip': 0, 'reduced': 0, 'full': 0, 'enhanced': 0}
        band_total = {'skip': 0, 'reduced': 0, 'full': 0, 'enhanced': 0}
        for s in scores:
            cs = s['score']
            if cs <= 3:
                band = 'skip'
            elif cs <= 6:
                band = 'reduced'
            elif cs <= 8:
                band = 'full'
            else:
                band = 'enhanced'
            if s['actual_win'] is not None:
                band_total[band] += 1
                if s['actual_win']:
                    band_wins[band] += 1

        band_winrates = {}
        for band in band_counts:
            total = band_total[band]
            band_winrates[band] = round(band_wins[band] / total * 100, 1) if total > 0 else None

        return Response({
            'total_scored': len(scores),
            'distribution': distribution,
            'band_counts': band_counts,
            'band_winrates': band_winrates,
            'avg_score': round(sum(s['score'] for s in scores) / len(scores), 1) if scores else 0,
        })


class HMMRegimeView(views.APIView):
    """Return current HMM regime state per forex pair and cross-pair consensus.

    Reads from Redis cache keys:
    - hmm_regime_detail:{symbol} -- full result dict (JSON)
    - hmm_regime_consensus -- cross-pair consensus dict (JSON)
    """

    FOREX_PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'USDCAD', 'USDCHF']

    # Map DB regime → HMM-style label + direction (matching widget's REGIME_COLORS/DIRECTION_ARROWS keys)
    REGIME_MAP = {
        'TRENDING_UP':   ('TRENDING', 'UP'),
        'TRENDING_DOWN': ('TRENDING', 'DOWN'),
        'RANGING':       ('RANGING',  'NEUTRAL'),
        'VOLATILE':      ('VOLATILE', 'NEUTRAL'),
        'UNKNOWN':       ('UNKNOWN',  'NEUTRAL'),
    }

    def _db_fallback(self, symbol):
        """Fall back to MarketRegime DB model when Redis cache is empty."""
        try:
            mr = MarketRegime.objects.filter(symbol=symbol, timeframe='H1').first()
            if mr:
                label, direction = self.REGIME_MAP.get(mr.regime, ('UNKNOWN', 'NEUTRAL'))
                return {
                    'label': label,
                    'confidence': mr.confidence,  # 0-1 float, widget multiplies by 100
                    'direction': direction,
                    'atr_override': False,
                    'state': None,
                    'source': 'db',
                }
        except Exception:
            pass
        return {'label': 'UNKNOWN', 'confidence': 0, 'direction': 'NEUTRAL'}

    def get(self, request):
        per_pair = {}
        for symbol in self.FOREX_PAIRS:
            detail_raw = cache.get(f'hmm_regime_detail:{symbol}')
            if detail_raw:
                try:
                    detail = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
                    per_pair[symbol] = {
                        'label': detail.get('label', 'UNKNOWN'),
                        'confidence': detail.get('confidence', 0),
                        'direction': detail.get('direction', 'NEUTRAL'),
                        'atr_override': detail.get('atr_override', False),
                        'state': detail.get('state'),
                    }
                except (json.JSONDecodeError, TypeError):
                    per_pair[symbol] = self._db_fallback(symbol)
            else:
                per_pair[symbol] = self._db_fallback(symbol)

        # Cross-pair consensus — build from per_pair data if Redis empty
        consensus_raw = cache.get('hmm_regime_consensus')
        consensus = {'dominant_regime': 'UNKNOWN', 'consensus_pct': 0, 'weighted_votes': {}}
        if consensus_raw:
            try:
                consensus = json.loads(consensus_raw) if isinstance(consensus_raw, str) else consensus_raw
            except (json.JSONDecodeError, TypeError):
                pass

        if consensus.get('dominant_regime') == 'UNKNOWN' and per_pair:
            # Build consensus from available per_pair data
            votes = {}
            for data in per_pair.values():
                label = data.get('label', 'UNKNOWN')
                if label != 'UNKNOWN':
                    votes[label] = votes.get(label, 0) + 1
            if votes:
                dominant = max(votes, key=votes.get)
                consensus = {
                    'dominant_regime': dominant,
                    'consensus_pct': votes[dominant] / len(per_pair),  # 0-1 float, widget multiplies by 100
                    'weighted_votes': votes,
                }

        return Response({
            'per_pair': per_pair,
            'consensus': consensus,
        })


class RotationLogView(views.APIView):
    """Return recent strategy rotation logs and trigger manual rotations."""

    def get(self, request):
        from .models import RotationLog
        limit = min(int(request.query_params.get('limit', 20)), 100)
        logs = RotationLog.objects.all()[:limit]
        return Response([{
            'id': log.id,
            'timestamp': log.timestamp.isoformat(),
            'session_name': log.session_name,
            'dominant_regime': log.dominant_regime,
            'strategies_scored': log.strategies_scored,
            'strategies_activated': log.strategies_activated,
            'strategies_deactivated': log.strategies_deactivated,
            'scores': log.scores,
            'reason': log.reason,
            'duration_seconds': log.duration_seconds,
        } for log in logs])

    def post(self, request):
        """Trigger a manual rotation run."""
        session_name = request.data.get('session_name')
        from app.quant.tasks import run_strategy_rotation
        run_strategy_rotation.delay(session_name=session_name)
        return Response({'status': 'Rotation started'}, status=status.HTTP_202_ACCEPTED)


class FinnhubEconomicCalendarView(views.APIView):
    """Return upcoming economic events from Finnhub."""

    def get(self, request):
        from app.utils.api.finnhub import get_economic_calendar
        days = int(request.query_params.get('days', 7))
        events = get_economic_calendar(days_ahead=days)
        return Response(events)


class FinnhubMarketNewsView(views.APIView):
    """Return latest market news from Finnhub."""

    def get(self, request):
        from app.utils.api.finnhub import get_market_news
        category = request.query_params.get('category', 'forex')
        articles = get_market_news(category=category)
        return Response(articles)


class FinnhubCandlesView(views.APIView):
    """Return forex candle data from Finnhub (alternative to Yahoo)."""

    def get(self, request):
        from app.utils.api.finnhub import fetch_forex_candles
        symbol = request.query_params.get('symbol')
        resolution = request.query_params.get('resolution', '15')
        days = int(request.query_params.get('days', 60))
        if not symbol:
            return Response({'error': 'symbol required'}, status=status.HTTP_400_BAD_REQUEST)
        df = fetch_forex_candles(symbol, resolution=resolution, days_back=days)
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
                'volume': row['volume'],
            })
        return Response(records)


class FinnhubIndicatorsView(views.APIView):
    """Return aggregate technical indicators from Finnhub."""

    def get(self, request):
        from app.utils.api.finnhub import get_aggregate_indicators
        symbol = request.query_params.get('symbol')
        resolution = request.query_params.get('resolution', '60')
        if not symbol:
            return Response({'error': 'symbol required'}, status=status.HTTP_400_BAD_REQUEST)
        result = get_aggregate_indicators(symbol, resolution=resolution)
        if result is None:
            return Response({'error': 'no data'}, status=status.HTTP_404_NOT_FOUND)
        return Response(result)


class MultiSourceBacktestView(views.APIView):
    """Trigger multi-source backtest for a strategy and poll results."""

    VALID_SOURCES = ('auto', 'mt5', 'yahoo', 'finnhub')

    def post(self, request):
        strategy_id = request.data.get('strategy_id')
        if not strategy_id:
            return Response({'error': 'strategy_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate strategy exists
        try:
            strategy = StrategyConfig.objects.get(id=strategy_id)
        except StrategyConfig.DoesNotExist:
            return Response({'error': f'Strategy {strategy_id} not found'}, status=status.HTTP_404_NOT_FOUND)

        period_days = request.data.get('period_days', 90)
        try:
            period_days = int(period_days)
            if not (30 <= period_days <= 365):
                return Response(
                    {'error': 'period_days must be between 30 and 365'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (TypeError, ValueError):
            return Response({'error': 'period_days must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

        data_source = request.data.get('data_source', 'auto')
        if data_source not in self.VALID_SOURCES:
            return Response(
                {'error': f'data_source must be one of: {", ".join(self.VALID_SOURCES)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        walk_forward = request.data.get('walk_forward', True)
        if isinstance(walk_forward, str):
            walk_forward = walk_forward.lower() in ('true', '1', 'yes')

        from app.quant.tasks import run_multi_source_backtest
        task = run_multi_source_backtest.delay(
            strategy_config_id=strategy.id,
            period_days=period_days,
            data_source=data_source,
            walk_forward=bool(walk_forward),
        )

        return Response(
            {
                'task_id': task.id,
                'strategy': strategy.name,
                'period_days': period_days,
                'data_source': data_source,
                'walk_forward': walk_forward,
                'status': 'PENDING',
            },
            status=status.HTTP_202_ACCEPTED,
        )

    def get(self, request):
        task_id = request.query_params.get('task_id')
        if not task_id:
            return Response({'error': 'task_id query parameter is required'}, status=status.HTTP_400_BAD_REQUEST)

        from celery.result import AsyncResult
        result = AsyncResult(task_id)

        response = {'task_id': task_id, 'status': result.status}

        if result.ready():
            if result.successful():
                response['result'] = result.result
            else:
                response['error'] = str(result.result)
        elif result.status == 'PENDING':
            response['message'] = 'Task is queued or does not exist'

        return Response(response)


class BacktestAllView(views.APIView):
    """Backtest ALL active strategies and return comparative results."""

    VALID_SOURCES = ('auto', 'mt5', 'yahoo', 'finnhub')

    def post(self, request):
        period_days = request.data.get('period_days', 90)
        try:
            period_days = int(period_days)
            if not (30 <= period_days <= 365):
                return Response(
                    {'error': 'period_days must be between 30 and 365'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (TypeError, ValueError):
            return Response({'error': 'period_days must be an integer'}, status=status.HTTP_400_BAD_REQUEST)

        data_source = request.data.get('data_source', 'auto')
        if data_source not in self.VALID_SOURCES:
            return Response(
                {'error': f'data_source must be one of: {", ".join(self.VALID_SOURCES)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        walk_forward = request.data.get('walk_forward', True)
        if isinstance(walk_forward, str):
            walk_forward = walk_forward.lower() in ('true', '1', 'yes')

        active_strategies = StrategyConfig.objects.filter(is_active=True)
        if not active_strategies.exists():
            return Response({'error': 'No active strategies found'}, status=status.HTTP_404_NOT_FOUND)

        from app.quant.tasks import run_multi_source_backtest
        tasks = []
        for strategy in active_strategies:
            task = run_multi_source_backtest.delay(
                strategy_config_id=strategy.id,
                period_days=period_days,
                data_source=data_source,
                walk_forward=bool(walk_forward),
            )
            tasks.append({
                'task_id': task.id,
                'strategy_id': strategy.id,
                'strategy_name': strategy.name,
            })

        return Response(
            {
                'total_strategies': len(tasks),
                'period_days': period_days,
                'data_source': data_source,
                'walk_forward': walk_forward,
                'tasks': tasks,
            },
            status=status.HTTP_202_ACCEPTED,
        )


# ── Training Infrastructure ──────────────────────────────────────────

class TrainingConfigView(views.APIView):
    """GET/POST training configuration (SSH host, mode, options)."""

    def get(self, request):
        from .models import TrainingConfig
        config = TrainingConfig.load()
        return Response({
            'mode': config.mode,
            'ssh_host': config.ssh_host,
            'ssh_user': config.ssh_user,
            'ssh_key_path': config.ssh_key_path,
            'ssh_port': config.ssh_port,
            'remote_training_dir': config.remote_training_dir,
            'train_xgboost': config.train_xgboost,
            'train_llm': config.train_llm,
            'updated_at': config.updated_at.isoformat() if config.updated_at else None,
        })

    def post(self, request):
        from .models import TrainingConfig
        config = TrainingConfig.load()
        fields = ['mode', 'ssh_host', 'ssh_user', 'ssh_key_path', 'ssh_port',
                   'remote_training_dir', 'train_xgboost', 'train_llm']
        for field in fields:
            if field in request.data:
                setattr(config, field, request.data[field])
        config.save()
        return Response({'status': 'ok'})


class TrainingStartView(views.APIView):
    """POST to trigger a new training run."""

    def post(self, request):
        from .models import TrainingConfig, TrainingRun

        # Check if a run is already in progress
        active = TrainingRun.objects.filter(status__in=['pending', 'running']).first()
        if active:
            return Response(
                {'error': f'Training already in progress (#{active.pk})', 'run_id': active.pk},
                status=status.HTTP_409_CONFLICT,
            )

        config = TrainingConfig.load()
        if config.mode == 'remote' and not config.ssh_host:
            return Response(
                {'error': 'SSH host not configured. Go to Settings to configure remote training.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Allow overriding what to train
        train_xgboost = request.data.get('train_xgboost', config.train_xgboost)
        train_llm = request.data.get('train_llm', config.train_llm)

        run = TrainingRun.objects.create(
            train_xgboost=train_xgboost,
            train_llm=train_llm,
            mode=config.mode,
        )

        # Dispatch to Celery
        from app.quant.tasks import run_remote_training
        run_remote_training.delay(run.pk)

        return Response({'run_id': run.pk, 'status': 'pending'}, status=status.HTTP_202_ACCEPTED)


class TrainingStatusView(views.APIView):
    """GET current/latest training run status with logs."""

    def get(self, request):
        from .models import TrainingRun

        run_id = request.query_params.get('run_id')
        if run_id:
            try:
                run = TrainingRun.objects.get(pk=run_id)
            except TrainingRun.DoesNotExist:
                return Response({'error': 'Run not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            run = TrainingRun.objects.first()
            if not run:
                return Response({'run': None})

        return Response({
            'run': {
                'id': run.pk,
                'status': run.status,
                'step': run.step,
                'mode': run.mode,
                'train_xgboost': run.train_xgboost,
                'train_llm': run.train_llm,
                'started_at': run.started_at.isoformat(),
                'completed_at': run.completed_at.isoformat() if run.completed_at else None,
                'error': run.error,
                'log': run.log,
                'xgboost_result': run.xgboost_result,
                'llm_result': run.llm_result,
            },
        })


class TrainingHistoryView(views.APIView):
    """GET past training runs."""

    def get(self, request):
        from .models import TrainingRun

        limit = int(request.query_params.get('limit', 20))
        runs = TrainingRun.objects.all()[:limit]

        return Response({
            'runs': [{
                'id': r.pk,
                'status': r.status,
                'step': r.step,
                'mode': r.mode,
                'train_xgboost': r.train_xgboost,
                'train_llm': r.train_llm,
                'started_at': r.started_at.isoformat(),
                'completed_at': r.completed_at.isoformat() if r.completed_at else None,
                'error': r.error,
                'xgboost_result': r.xgboost_result,
                'llm_result': r.llm_result,
            } for r in runs],
        })

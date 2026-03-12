from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TradeViewSet, SendMarketOrderView, ModifySLTPView, LogsView, StrategyViewSet, CustomStrategyViewSet, BotControlView, YahooDataView, AIBrainControlView, AIBrainLogsView, MarketPulseView, MarketRegimeView, PairLocksView, ICTScanView, MLStatusView, MLPredictionsView, MLBackfillLLMView, ConfluenceScoreView, HMMRegimeView

router = DefaultRouter()
router.register(r'trades', TradeViewSet)
router.register(r'strategies', StrategyViewSet)
router.register(r'custom-strategies', CustomStrategyViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('send_market_order/', SendMarketOrderView.as_view(), name='send_market_order'),
    path('modify_sl_tp/', ModifySLTPView.as_view(), name='modify_sl_tp'),
    path('logs/', LogsView.as_view(), name='logs'),
    path('bot/status/', BotControlView.as_view(), name='bot-status'),
    path('ai-brain/', AIBrainControlView.as_view(), name='ai-brain'),
    path('ai-brain/logs/', AIBrainLogsView.as_view(), name='ai-brain-logs'),
    path('yahoo-data/', YahooDataView.as_view(), name='yahoo-data'),
    path('market-pulse/', MarketPulseView.as_view(), name='market-pulse'),
    path('market-regime/', MarketRegimeView.as_view(), name='market-regime'),
    path('pair-locks/', PairLocksView.as_view(), name='pair-locks'),
    path('ict/scan/', ICTScanView.as_view(), name='ict-scan'),
    path('ml/status/', MLStatusView.as_view(), name='ml-status'),
    path('ml/predictions/', MLPredictionsView.as_view(), name='ml-predictions'),
    path('ml/backfill-llm/', MLBackfillLLMView.as_view(), name='ml-backfill-llm'),
    path('confluence-scores/', ConfluenceScoreView.as_view(), name='confluence-scores'),
    path('hmm-regimes/', HMMRegimeView.as_view(), name='hmm-regimes'),
]

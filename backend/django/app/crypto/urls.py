from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CryptoPositionViewSet,
    CryptoTradeViewSet,
    CryptoBacktestViewSet,
    CryptoBotControlView,
    CryptoFundingArbView,
    CryptoFundingRatesView,
    CryptoLogsView,
    CryptoDashboardView,
    CryptoStrategyConfigView,
    CryptoWalletView,
    HyperliquidControlView,
    LighterProxyView,
    LighterAPITradesView,
    CryptoMLStatsView,
    CryptoMLStatusView,
    CryptoMLPredictionsView,
)

router = DefaultRouter()
router.register(r'positions', CryptoPositionViewSet)
router.register(r'trades', CryptoTradeViewSet)
router.register(r'backtests', CryptoBacktestViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('bot/status/', CryptoBotControlView.as_view(), name='crypto-bot-status'),
    path('funding-arb/', CryptoFundingArbView.as_view(), name='crypto-funding-arb'),
    path('funding-rates/', CryptoFundingRatesView.as_view(), name='crypto-funding-rates'),
    path('logs/', CryptoLogsView.as_view(), name='crypto-logs'),
    path('dashboard/', CryptoDashboardView.as_view(), name='crypto-dashboard'),
    path('wallet/', CryptoWalletView.as_view(), name='crypto-wallet'),
    path('strategy/', CryptoStrategyConfigView.as_view(), name='crypto-strategy'),
    path('lighter/proxy/', LighterProxyView.as_view(), name='lighter-proxy'),
    path('hyperliquid/control/', HyperliquidControlView.as_view(), name='hyperliquid-control'),
    path('lighter/trades/', LighterAPITradesView.as_view(), name='lighter-api-trades'),
    path('ml/stats/', CryptoMLStatsView.as_view(), name='crypto-ml-stats'),
    path('ml/status/', CryptoMLStatusView.as_view(), name='crypto-ml-status'),
    path('ml/predictions/', CryptoMLPredictionsView.as_view(), name='crypto-ml-predictions'),
]

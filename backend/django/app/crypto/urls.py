from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CryptoPositionViewSet,
    CryptoTradeViewSet,
    CryptoBacktestViewSet,
    CryptoBotControlView,
    CryptoLogsView,
    CryptoDashboardView,
    CryptoStrategyConfigView,
    CryptoWalletView,
)

router = DefaultRouter()
router.register(r'positions', CryptoPositionViewSet)
router.register(r'trades', CryptoTradeViewSet)
router.register(r'backtests', CryptoBacktestViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('bot/status/', CryptoBotControlView.as_view(), name='crypto-bot-status'),
    path('logs/', CryptoLogsView.as_view(), name='crypto-logs'),
    path('dashboard/', CryptoDashboardView.as_view(), name='crypto-dashboard'),
    path('wallet/', CryptoWalletView.as_view(), name='crypto-wallet'),
    path('strategy/', CryptoStrategyConfigView.as_view(), name='crypto-strategy'),
]

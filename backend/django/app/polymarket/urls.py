from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PolyMarketViewSet,
    PolyPositionViewSet,
    PolyTradeViewSet,
    PolyBacktestViewSet,
    PolyBotControlView,
    PolyLogsView,
    PolyDashboardView,
    PolyStrategyConfigView,
)

router = DefaultRouter()
router.register(r'markets', PolyMarketViewSet)
router.register(r'positions', PolyPositionViewSet)
router.register(r'trades', PolyTradeViewSet)
router.register(r'backtests', PolyBacktestViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('bot/status/', PolyBotControlView.as_view(), name='polymarket-bot-status'),
    path('logs/', PolyLogsView.as_view(), name='polymarket-logs'),
    path('dashboard/', PolyDashboardView.as_view(), name='polymarket-dashboard'),
    path('strategy/', PolyStrategyConfigView.as_view(), name='polymarket-strategy'),
]

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TradeViewSet, SendMarketOrderView, ModifySLTPView, LogsView, StrategyViewSet, CustomStrategyViewSet, BotControlView, YahooDataView

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
    path('yahoo-data/', YahooDataView.as_view(), name='yahoo-data'),
]

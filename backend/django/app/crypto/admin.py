from django.contrib import admin
from .models import CryptoPosition, CryptoTrade, CryptoBacktestResult


@admin.register(CryptoPosition)
class CryptoPositionAdmin(admin.ModelAdmin):
    list_display = ['id', 'symbol', 'side', 'entry_price', 'size', 'leverage', 'status', 'pnl_usd', 'opened_at']
    list_filter = ['status', 'side', 'symbol']
    search_fields = ['symbol']
    ordering = ('-opened_at',)


@admin.register(CryptoTrade)
class CryptoTradeAdmin(admin.ModelAdmin):
    list_display = ['id', 'position', 'order_id', 'side', 'price', 'size', 'fee', 'status', 'created_at']
    list_filter = ['status', 'side']
    ordering = ('-created_at',)


@admin.register(CryptoBacktestResult)
class CryptoBacktestResultAdmin(admin.ModelAdmin):
    list_display = ['id', 'run_time', 'symbol', 'strategy_name', 'total_trades', 'win_rate', 'total_pnl', 'passed']
    list_filter = ['passed', 'symbol']
    ordering = ('-run_time',)

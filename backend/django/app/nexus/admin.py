from django.contrib import admin
from .models import Trade, TradeClosePricesMutation, StrategyConfig, BacktestResult

@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = [field.name for field in Trade._meta.fields]
    list_filter = [field.name for field in Trade._meta.fields]
    search_fields = [field.name for field in Trade._meta.fields]

    ordering = ('-entry_time',)

@admin.register(TradeClosePricesMutation)
class TradeClosePricesMutationAdmin(admin.ModelAdmin):
    list_display = [field.name for field in TradeClosePricesMutation._meta.fields]
    list_filter = [field.name for field in TradeClosePricesMutation._meta.fields]
    search_fields = [field.name for field in TradeClosePricesMutation._meta.fields]

    ordering = ('-mutation_time',)

@admin.register(StrategyConfig)
class StrategyConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'last_activated']
    list_filter = ['is_active']

@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display = ['strategy', 'run_time', 'win_rate', 'total_trades', 'passed']
    list_filter = ['passed', 'strategy']
    ordering = ('-run_time',)

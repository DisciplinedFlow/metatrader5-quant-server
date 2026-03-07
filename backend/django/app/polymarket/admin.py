from django.contrib import admin
from .models import PolyMarket, PolyPosition, PolyTrade, PolyProbabilityLog, PolyBacktestResult


@admin.register(PolyMarket)
class PolyMarketAdmin(admin.ModelAdmin):
    list_display = [field.name for field in PolyMarket._meta.fields]
    list_filter = [field.name for field in PolyMarket._meta.fields]
    search_fields = [field.name for field in PolyMarket._meta.fields]
    ordering = ('-created_at',)


@admin.register(PolyPosition)
class PolyPositionAdmin(admin.ModelAdmin):
    list_display = [field.name for field in PolyPosition._meta.fields]
    list_filter = [field.name for field in PolyPosition._meta.fields]
    search_fields = [field.name for field in PolyPosition._meta.fields]
    ordering = ('-opened_at',)


@admin.register(PolyTrade)
class PolyTradeAdmin(admin.ModelAdmin):
    list_display = [field.name for field in PolyTrade._meta.fields]
    list_filter = [field.name for field in PolyTrade._meta.fields]
    search_fields = [field.name for field in PolyTrade._meta.fields]
    ordering = ('-created_at',)


@admin.register(PolyProbabilityLog)
class PolyProbabilityLogAdmin(admin.ModelAdmin):
    list_display = [field.name for field in PolyProbabilityLog._meta.fields]
    list_filter = [field.name for field in PolyProbabilityLog._meta.fields]
    search_fields = [field.name for field in PolyProbabilityLog._meta.fields]
    ordering = ('-created_at',)


@admin.register(PolyBacktestResult)
class PolyBacktestResultAdmin(admin.ModelAdmin):
    list_display = ['id', 'run_time', 'total_trades', 'win_rate', 'total_pnl', 'passed']
    list_filter = ['passed']
    ordering = ('-run_time',)

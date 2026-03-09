from rest_framework import serializers
from .models import Trade, TradeClosePricesMutation, StrategyConfig, BacktestResult, CustomStrategy, PairLock, MarketRegime

class TradeClosePricesMutationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeClosePricesMutation
        fields = '__all__'

class TradeSerializer(serializers.ModelSerializer):
    close_prices_mutations = TradeClosePricesMutationSerializer(many=True, read_only=True)
    strategy_config_name = serializers.CharField(source='strategy_config.name', read_only=True, default=None)

    class Meta:
        model = Trade
        fields = '__all__'

class BacktestResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestResult
        fields = '__all__'

class StrategyConfigSerializer(serializers.ModelSerializer):
    latest_backtest = serializers.SerializerMethodField()

    class Meta:
        model = StrategyConfig
        fields = ['id', 'name', 'is_active', 'description', 'last_activated',
                  'priority', 'max_positions', 'capital_allocation_pct', 'regime_filter',
                  'latest_backtest']

    def get_latest_backtest(self, obj):
        latest = obj.backtest_results.order_by('-run_time').first()
        if latest:
            data = BacktestResultSerializer(latest).data
            data.pop('trades', None)
            return data
        return None


class CustomStrategySerializer(serializers.ModelSerializer):
    latest_backtest = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = CustomStrategy
        fields = '__all__'

    def get_is_active(self, obj):
        if not obj.strategy_config_id:
            return False
        return obj.strategy_config.is_active

    def get_latest_backtest(self, obj):
        if not obj.strategy_config_id:
            return None
        latest = BacktestResult.objects.filter(
            strategy_id=obj.strategy_config_id
        ).order_by('-run_time').first()
        if latest:
            data = BacktestResultSerializer(latest).data
            data.pop('trades', None)
            return data
        return None


class PairLockSerializer(serializers.ModelSerializer):
    strategy_name = serializers.CharField(source='strategy.name', read_only=True)

    class Meta:
        model = PairLock
        fields = '__all__'


class MarketRegimeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketRegime
        fields = '__all__'

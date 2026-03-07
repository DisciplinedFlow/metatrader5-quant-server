from rest_framework import serializers
from .models import Trade, TradeClosePricesMutation, StrategyConfig, BacktestResult

class TradeClosePricesMutationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradeClosePricesMutation
        fields = '__all__'

class TradeSerializer(serializers.ModelSerializer):
    close_prices_mutations = TradeClosePricesMutationSerializer(many=True, read_only=True)

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
        fields = ['id', 'name', 'is_active', 'description', 'last_activated', 'latest_backtest']

    def get_latest_backtest(self, obj):
        latest = obj.backtest_results.order_by('-run_time').first()
        if latest:
            return BacktestResultSerializer(latest).data
        return None

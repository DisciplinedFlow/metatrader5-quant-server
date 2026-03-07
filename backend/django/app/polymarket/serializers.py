from rest_framework import serializers
from .models import PolyMarket, PolyPosition, PolyTrade, PolyProbabilityLog, PolyBacktestResult


class PolyMarketSerializer(serializers.ModelSerializer):
    positions_count = serializers.SerializerMethodField()

    class Meta:
        model = PolyMarket
        fields = '__all__'

    def get_positions_count(self, obj):
        return obj.positions.count()


class PolyPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolyPosition
        fields = '__all__'


class PolyTradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolyTrade
        fields = '__all__'


class PolyProbabilityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolyProbabilityLog
        fields = '__all__'


class PolyBacktestResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolyBacktestResult
        fields = '__all__'


class PolyBacktestResultSummarySerializer(serializers.ModelSerializer):
    """Excludes trades/equity_curve for list views."""
    class Meta:
        model = PolyBacktestResult
        exclude = ['trades', 'equity_curve']

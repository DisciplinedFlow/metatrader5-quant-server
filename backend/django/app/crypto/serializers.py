from rest_framework import serializers
from .models import CryptoPosition, CryptoTrade, CryptoBacktestResult


class CryptoPositionSerializer(serializers.ModelSerializer):
    total_fees = serializers.SerializerMethodField()

    class Meta:
        model = CryptoPosition
        fields = '__all__'

    def get_total_fees(self, obj):
        return sum(float(t.fee or 0) for t in obj.trades.all())


class CryptoTradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CryptoTrade
        fields = '__all__'


class CryptoBacktestResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = CryptoBacktestResult
        fields = '__all__'


class CryptoBacktestResultSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = CryptoBacktestResult
        exclude = ['trades', 'equity_curve']

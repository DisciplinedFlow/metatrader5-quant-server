from rest_framework import serializers
from .models import CryptoPosition, CryptoTrade, CryptoBacktestResult


class CryptoPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CryptoPosition
        fields = '__all__'


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

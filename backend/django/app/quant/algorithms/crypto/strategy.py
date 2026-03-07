import pandas as pd
import numpy as np
import logging

from .indicators import calculate_sma, calculate_ema, calculate_momentum

logger = logging.getLogger('app.crypto')


class MomentumStrategy:
    """
    Time-series momentum strategy ported from QuantHub.
    Uses MA crossover or returns-based momentum signals.
    """

    def __init__(
        self,
        signal_type: str = 'ma_crossover',
        lookback: int = 252,
        fast_ma: int = 50,
        slow_ma: int = 200,
        threshold: float = 0.0,
        allow_short: bool = False,
        max_position_pct: float = 0.10,
    ):
        self.signal_type = signal_type
        self.lookback = lookback
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.threshold = threshold
        self.allow_short = allow_short
        self.max_position_pct = max_position_pct

    def generate_signal(self, prices: pd.Series) -> int:
        """
        Generate signal for a single asset.
        Returns: 1 (long), -1 (short), 0 (neutral)
        """
        if len(prices) < self.slow_ma:
            return 0

        if self.signal_type == 'ma_crossover':
            fast = calculate_sma(prices, self.fast_ma)
            slow = calculate_sma(prices, self.slow_ma)
            if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]):
                return 0
            if fast.iloc[-1] > slow.iloc[-1]:
                return 1
            elif self.allow_short and fast.iloc[-1] < slow.iloc[-1]:
                return -1
            return 0

        elif self.signal_type == 'returns':
            mom = calculate_momentum(prices, self.lookback)
            if pd.isna(mom.iloc[-1]):
                return 0
            if mom.iloc[-1] > self.threshold:
                return 1
            elif self.allow_short and mom.iloc[-1] < -self.threshold:
                return -1
            return 0

        return 0

    def calculate_position_size(
        self, signal: int, capital: float, current_price: float
    ) -> float:
        if signal == 0:
            return 0.0
        position_value = capital * self.max_position_pct
        size = position_value / current_price
        return size * signal

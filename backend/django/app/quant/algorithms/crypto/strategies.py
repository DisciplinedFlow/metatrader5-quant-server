"""
Multi-strategy crypto trading system.

Strategies designed for 500 hourly candles (~21 days) from Hyperliquid.
Each strategy implements generate_signal(data) -> int and has its own
SL/TP logic via get_exit_params().

Draws from:
  - Trading in the Zone (Mark Douglas) — process over outcome, no revenge trading
  - Crypto Trading KB — funding rate, liquidation cascades, BTC correlation
  - Elite Trader Research — risk-first sizing, asymmetric R:R
"""

import pandas as pd
import numpy as np
import logging

from .indicators import (
    calculate_sma, calculate_ema, calculate_rsi, calculate_atr,
    calculate_bollinger_bands, calculate_macd, calculate_stochastic_rsi,
    calculate_adx, calculate_obv, calculate_volume_sma,
)

logger = logging.getLogger('app.crypto')


class BaseStrategy:
    """Interface for all crypto strategies."""
    name = 'base'
    description = ''
    min_bars = 50

    def generate_signal(self, data: dict) -> int:
        """Return 1 (long), -1 (short), or 0 (neutral).
        `data` contains: close, high, low, volume (all pd.Series)."""
        raise NotImplementedError

    def get_exit_params(self):
        """Return dict with stop_loss_pct, take_profit_pct."""
        return {'stop_loss_pct': 0.03, 'take_profit_pct': 0.06}

    def calculate_position_size(self, signal, capital, price, max_pct=0.10):
        if signal == 0:
            return 0.0
        return abs(capital * max_pct / price) * signal


# ─────────────────────────────────────────────────
# Strategy 1: RSI Mean Reversion + Bollinger Bands
# ─────────────────────────────────────────────────
class RSIMeanReversion(BaseStrategy):
    """
    Buy oversold (RSI < 30) near lower Bollinger Band.
    Sell overbought (RSI > 70) near upper Bollinger Band.
    Best in ranging/choppy markets. Tight stops since reversals are risky.

    From crypto_trading_kb: "Mean reversion works in crypto ranges but fails
    spectacularly in trending markets. Always have a stop."
    """
    name = 'rsi_mean_reversion'
    description = 'RSI oversold/overbought + Bollinger Band confirmation'
    min_bars = 30

    def __init__(self, rsi_period=14, bb_period=20, bb_std=2.0,
                 rsi_oversold=30, rsi_overbought=70, allow_short=True):
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.allow_short = allow_short

    def generate_signal(self, data):
        close = data['close']
        if len(close) < self.min_bars:
            return 0

        rsi = calculate_rsi(close, self.rsi_period)
        _, upper, lower, _, pct_b = calculate_bollinger_bands(close, self.bb_period, self.bb_std)

        rsi_now = rsi.iloc[-1]
        pct_b_now = pct_b.iloc[-1]

        if pd.isna(rsi_now) or pd.isna(pct_b_now):
            return 0

        # Long: RSI oversold AND price near lower band (%b < 0.2)
        if rsi_now < self.rsi_oversold and pct_b_now < 0.2:
            return 1

        # Short: RSI overbought AND price near upper band (%b > 0.8)
        if self.allow_short and rsi_now > self.rsi_overbought and pct_b_now > 0.8:
            return -1

        return 0

    def get_exit_params(self):
        return {'stop_loss_pct': 0.025, 'take_profit_pct': 0.05}


# ─────────────────────────────────────────────────
# Strategy 2: EMA Ribbon Trend Following
# ─────────────────────────────────────────────────
class EMARibbonTrend(BaseStrategy):
    """
    4-EMA ribbon (8/13/21/55) alignment for trend direction.
    Enter on pullback to middle EMAs when ribbon is aligned.
    ADX > 20 confirms real trend (not chop).

    From crypto_trading_kb: "Trend following captures the 80/20 of crypto profits.
    Most gains come from holding through the trend, not timing entries."
    """
    name = 'ema_ribbon_trend'
    description = 'EMA ribbon alignment + pullback entry + ADX filter'
    min_bars = 60

    def __init__(self, ema_fast=8, ema_mid1=13, ema_mid2=21, ema_slow=55,
                 adx_period=14, adx_threshold=20, allow_short=True):
        self.ema_fast = ema_fast
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_slow = ema_slow
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.allow_short = allow_short

    def generate_signal(self, data):
        close = data['close']
        high = data.get('high', close)
        low = data.get('low', close)

        if len(close) < self.min_bars:
            return 0

        e_fast = calculate_ema(close, self.ema_fast)
        e_mid1 = calculate_ema(close, self.ema_mid1)
        e_mid2 = calculate_ema(close, self.ema_mid2)
        e_slow = calculate_ema(close, self.ema_slow)
        adx = calculate_adx(high, low, close, self.adx_period)

        f, m1, m2, s = e_fast.iloc[-1], e_mid1.iloc[-1], e_mid2.iloc[-1], e_slow.iloc[-1]
        adx_now = adx.iloc[-1]
        price = close.iloc[-1]

        if any(pd.isna(v) for v in [f, m1, m2, s, adx_now]):
            return 0

        # Require trend strength
        if adx_now < self.adx_threshold:
            return 0

        # Bullish ribbon: fast > mid1 > mid2 > slow
        if f > m1 > m2 > s:
            # Pullback: price touched mid EMAs (between mid1 and mid2) but closed above fast
            if price > f and close.iloc[-2] <= m1.item() if hasattr(m1, 'item') else m1:
                return 1
            # Or: just aligned and price above fast
            if price > f:
                return 1

        # Bearish ribbon: fast < mid1 < mid2 < slow
        if self.allow_short and f < m1 < m2 < s:
            if price < f:
                return -1

        return 0

    def get_exit_params(self):
        return {'stop_loss_pct': 0.035, 'take_profit_pct': 0.08}


# ─────────────────────────────────────────────────
# Strategy 3: MACD Momentum Crossover
# ─────────────────────────────────────────────────
class MACDMomentum(BaseStrategy):
    """
    MACD histogram crossover with EMA trend filter.
    Only trade MACD crosses in the direction of the prevailing trend.

    Classic momentum strategy adapted for crypto's higher volatility
    with wider stops and a fast EMA trend gate.
    """
    name = 'macd_momentum'
    description = 'MACD histogram crossover + EMA(50) trend filter'
    min_bars = 55

    def __init__(self, macd_fast=12, macd_slow=26, macd_signal=9,
                 trend_ema=50, allow_short=True):
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.trend_ema = trend_ema
        self.allow_short = allow_short

    def generate_signal(self, data):
        close = data['close']
        if len(close) < self.min_bars:
            return 0

        _, _, histogram = calculate_macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        trend = calculate_ema(close, self.trend_ema)

        hist_now = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2]
        trend_now = trend.iloc[-1]
        price = close.iloc[-1]

        if any(pd.isna(v) for v in [hist_now, hist_prev, trend_now]):
            return 0

        # Bullish: histogram crosses above zero AND price above trend EMA
        if hist_prev <= 0 < hist_now and price > trend_now:
            return 1

        # Bearish: histogram crosses below zero AND price below trend EMA
        if self.allow_short and hist_prev >= 0 > hist_now and price < trend_now:
            return -1

        return 0

    def get_exit_params(self):
        return {'stop_loss_pct': 0.04, 'take_profit_pct': 0.08}


# ─────────────────────────────────────────────────
# Strategy 4: Bollinger Squeeze Breakout
# ─────────────────────────────────────────────────
class BollingerSqueezeBreakout(BaseStrategy):
    """
    Detects Bollinger Band squeeze (low bandwidth = compression).
    Enters when price breaks out of the bands after a squeeze period.
    Volume confirmation: breakout bar volume > 1.5x average.

    From crypto_trading_kb: "Volatility compression always precedes expansion.
    The squeeze is the setup, the breakout is the trigger."
    """
    name = 'bollinger_squeeze_breakout'
    description = 'Bollinger squeeze detection + volume breakout'
    min_bars = 30

    def __init__(self, bb_period=20, bb_std=2.0, squeeze_lookback=10,
                 squeeze_percentile=25, volume_factor=1.3, allow_short=True):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_lookback = squeeze_lookback
        self.squeeze_percentile = squeeze_percentile
        self.volume_factor = volume_factor
        self.allow_short = allow_short

    def generate_signal(self, data):
        close = data['close']
        volume = data.get('volume')

        if len(close) < self.min_bars:
            return 0

        _, upper, lower, bandwidth, _ = calculate_bollinger_bands(
            close, self.bb_period, self.bb_std
        )

        bw = bandwidth.dropna()
        if len(bw) < self.squeeze_lookback + 1:
            return 0

        # Check for squeeze: recent bandwidth in bottom percentile of lookback
        recent_bw = bw.iloc[-self.squeeze_lookback:-1]
        historical_bw = bw.iloc[:-1]
        threshold = historical_bw.quantile(self.squeeze_percentile / 100)
        is_squeezed = recent_bw.mean() < threshold

        if not is_squeezed:
            return 0

        price = close.iloc[-1]
        upper_now = upper.iloc[-1]
        lower_now = lower.iloc[-1]

        if pd.isna(upper_now) or pd.isna(lower_now):
            return 0

        # Volume confirmation (if available)
        vol_ok = True
        if volume is not None and len(volume) >= 20:
            vol_avg = calculate_volume_sma(volume, 20)
            v_avg = vol_avg.iloc[-1]
            if not pd.isna(v_avg) and v_avg > 0:
                vol_ok = volume.iloc[-1] > v_avg * self.volume_factor

        # Breakout above upper band
        if price > upper_now and vol_ok:
            return 1

        # Breakout below lower band
        if self.allow_short and price < lower_now and vol_ok:
            return -1

        return 0

    def get_exit_params(self):
        return {'stop_loss_pct': 0.03, 'take_profit_pct': 0.07}


# ─────────────────────────────────────────────────
# Strategy 5: Multi-Signal Confluence Scorer
# ─────────────────────────────────────────────────
class ConfluenceScorer(BaseStrategy):
    """
    Combines multiple independent signals into a confluence score.
    Only trades when score >= threshold (high-conviction setups only).

    Signals scored:
      - RSI direction (oversold/overbought)       [+1/-1]
      - MACD histogram direction                   [+1/-1]
      - EMA(8/21) alignment                        [+1/-1]
      - Price vs SMA(50) trend                     [+1/-1]
      - Volume above average                       [+1]
      - Stochastic RSI extreme                     [+1/-1]

    Max score: +6 (strong long) to -6 (strong short).
    Default threshold: 4 (requires 4 of 6 bullish signals).

    From crypto_trading_kb: "The best crypto trades combine multiple
    independent confirmations. Single-indicator strategies get wrecked
    by noise and manipulation."
    """
    name = 'confluence_scorer'
    description = 'Multi-indicator confluence scoring (RSI + MACD + EMA + volume)'
    min_bars = 55

    def __init__(self, threshold=4, allow_short=True):
        self.threshold = threshold
        self.allow_short = allow_short

    def generate_signal(self, data):
        close = data['close']
        volume = data.get('volume')
        high = data.get('high', close)
        low = data.get('low', close)

        if len(close) < self.min_bars:
            return 0

        score = 0

        # 1. RSI
        rsi = calculate_rsi(close, 14)
        rsi_now = rsi.iloc[-1]
        if not pd.isna(rsi_now):
            if rsi_now < 40:
                score += 1
            elif rsi_now > 60:
                score -= 1

        # 2. MACD histogram
        _, _, histogram = calculate_macd(close, 12, 26, 9)
        hist_now = histogram.iloc[-1]
        hist_prev = histogram.iloc[-2] if len(histogram) > 1 else np.nan
        if not pd.isna(hist_now) and not pd.isna(hist_prev):
            if hist_now > 0 and hist_now > hist_prev:
                score += 1
            elif hist_now < 0 and hist_now < hist_prev:
                score -= 1

        # 3. EMA alignment (8 > 21 = bullish)
        ema8 = calculate_ema(close, 8)
        ema21 = calculate_ema(close, 21)
        if not pd.isna(ema8.iloc[-1]) and not pd.isna(ema21.iloc[-1]):
            if ema8.iloc[-1] > ema21.iloc[-1]:
                score += 1
            else:
                score -= 1

        # 4. Price vs SMA(50) trend
        sma50 = calculate_sma(close, 50)
        if not pd.isna(sma50.iloc[-1]):
            if close.iloc[-1] > sma50.iloc[-1]:
                score += 1
            else:
                score -= 1

        # 5. Volume surge
        if volume is not None and len(volume) >= 20:
            vol_avg = calculate_volume_sma(volume, 20)
            if not pd.isna(vol_avg.iloc[-1]) and vol_avg.iloc[-1] > 0:
                if volume.iloc[-1] > vol_avg.iloc[-1] * 1.2:
                    score += 1  # Volume confirms (direction neutral)

        # 6. Stochastic RSI
        stoch_k, stoch_d = calculate_stochastic_rsi(close)
        if not pd.isna(stoch_k.iloc[-1]):
            if stoch_k.iloc[-1] < 20:
                score += 1  # Oversold
            elif stoch_k.iloc[-1] > 80:
                score -= 1  # Overbought

        # Convert to signal
        if score >= self.threshold:
            return 1
        if self.allow_short and score <= -self.threshold:
            return -1
        return 0

    def get_exit_params(self):
        return {'stop_loss_pct': 0.03, 'take_profit_pct': 0.07}


# ─────────────────────────────────────────────────
# Registry of all strategies
# ─────────────────────────────────────────────────
STRATEGY_REGISTRY = {
    'rsi_mean_reversion': RSIMeanReversion,
    'ema_ribbon_trend': EMARibbonTrend,
    'macd_momentum': MACDMomentum,
    'bollinger_squeeze_breakout': BollingerSqueezeBreakout,
    'confluence_scorer': ConfluenceScorer,
}


def get_all_strategies():
    """Instantiate all strategies with default parameters."""
    return {name: cls() for name, cls in STRATEGY_REGISTRY.items()}


def get_strategy(name: str, **kwargs):
    """Get a strategy by name with optional parameter overrides."""
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    return cls(**kwargs)

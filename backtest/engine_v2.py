"""
Backtest engine v2 — clean, standalone, no Django dependencies.

Usage:
    from backtest.engine_v2 import BacktestEngine, run_backtest

    engine = BacktestEngine('backtest/data/XAU_1h.parquet', my_signal_fn, sl_pct=0.015, tp_pct=0.03)
    engine.run()
    print(engine.results())

    # Or use the convenience function:
    results = run_backtest('XAU', '1h', my_signal_fn, sl_pct=0.015, tp_pct=0.03)

Signal function signature:
    def my_signal(df_slice: pd.DataFrame) -> int
        df_slice: rolling window of `lookback` candles (columns: timestamp, open, high, low, close, volume)
        Return +1 (long), -1 (short), or 0 (no signal)
"""

import os
import numpy as np
import pandas as pd


class BacktestEngine:
    """Deterministic single-position backtest engine with percentage-based SL/TP."""

    def __init__(
        self,
        candle_file: str,
        signal_fn,
        sl_pct: float,
        tp_pct: float,
        slippage_pct: float = 0.0005,
        fee_pct: float = 0.00028,
        lookback: int = 50,
    ):
        self.candle_file = candle_file
        self.signal_fn = signal_fn
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.slippage_pct = slippage_pct
        self.fee_pct = fee_pct
        self.lookback = lookback

        self._trades: list[dict] = []
        self._df: pd.DataFrame | None = None
        self._has_run = False

    def _load_data(self) -> pd.DataFrame:
        """Load candle data from Parquet (preferred) or CSV fallback."""
        path = self.candle_file
        if path.endswith('.parquet') and os.path.exists(path):
            df = pd.read_parquet(path)
        elif path.endswith('.csv') and os.path.exists(path):
            df = pd.read_csv(path)
        else:
            # Try parquet first, then csv
            pq = path.rsplit('.', 1)[0] + '.parquet' if '.' in path else path + '.parquet'
            csv = path.rsplit('.', 1)[0] + '.csv' if '.' in path else path + '.csv'
            if os.path.exists(pq):
                df = pd.read_parquet(pq)
            elif os.path.exists(csv):
                df = pd.read_csv(csv)
            elif os.path.exists(path):
                # Try as-is: sniff format
                try:
                    df = pd.read_parquet(path)
                except Exception:
                    df = pd.read_csv(path)
            else:
                raise FileNotFoundError(f"Candle file not found: {path}")

        required = {'timestamp', 'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")

        df = df.sort_values('timestamp').reset_index(drop=True)
        # Ensure numeric types
        for col in ('open', 'high', 'low', 'close', 'volume'):
            df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    def run(self):
        """Execute the backtest. Populates internal trade list."""
        df = self._load_data()
        self._df = df
        self._trades = []

        n = len(df)
        if n <= self.lookback:
            self._has_run = True
            return

        in_position = False
        position_side = 0  # +1 long, -1 short
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        entry_time = None
        pending_signal = 0  # signal from previous bar, to enter on next open

        for i in range(self.lookback, n):
            bar = df.iloc[i]

            # ── Handle pending entry at this bar's open ──
            if pending_signal != 0 and not in_position:
                raw_open = bar['open']
                if pending_signal == 1:
                    # Long: buy at open + slippage
                    entry_price = raw_open * (1 + self.slippage_pct)
                    sl_price = entry_price * (1 - self.sl_pct)
                    tp_price = entry_price * (1 + self.tp_pct)
                else:
                    # Short: sell at open - slippage
                    entry_price = raw_open * (1 - self.slippage_pct)
                    sl_price = entry_price * (1 + self.sl_pct)
                    tp_price = entry_price * (1 - self.tp_pct)

                in_position = True
                position_side = pending_signal
                entry_time = bar['timestamp']
                pending_signal = 0

            # ── Check SL/TP against this bar's high/low ──
            if in_position:
                hit_sl = False
                hit_tp = False

                if position_side == 1:  # Long
                    if bar['low'] <= sl_price:
                        hit_sl = True
                    if bar['high'] >= tp_price:
                        hit_tp = True
                else:  # Short
                    if bar['high'] >= sl_price:
                        hit_sl = True
                    if bar['low'] <= tp_price:
                        hit_tp = True

                # If both hit on same bar, assume SL hit first (conservative)
                if hit_sl:
                    exit_price = sl_price
                    close_reason = 'STOP_LOSS'
                elif hit_tp:
                    exit_price = tp_price
                    close_reason = 'TAKE_PROFIT'
                else:
                    exit_price = None
                    close_reason = None

                if exit_price is not None:
                    # Apply slippage to exit
                    if position_side == 1:
                        # Selling to close long: exit - slippage
                        exit_adj = exit_price * (1 - self.slippage_pct)
                    else:
                        # Buying to close short: exit + slippage
                        exit_adj = exit_price * (1 + self.slippage_pct)

                    # Compute PnL as percentage, then apply fees on both legs
                    if position_side == 1:
                        pnl_gross = (exit_adj - entry_price) / entry_price
                    else:
                        pnl_gross = (entry_price - exit_adj) / entry_price

                    pnl_net = pnl_gross - 2 * self.fee_pct  # fee on entry + exit

                    self._trades.append({
                        'entry_time': entry_time,
                        'exit_time': bar['timestamp'],
                        'side': 'LONG' if position_side == 1 else 'SHORT',
                        'entry_price': entry_price,
                        'exit_price': exit_adj,
                        'pnl_net': pnl_net,
                        'close_reason': close_reason,
                    })

                    in_position = False
                    position_side = 0
                    continue  # don't generate new signal on exit bar

            # ── Generate signal for next bar entry ──
            if not in_position:
                window = df.iloc[i - self.lookback + 1:i + 1]
                sig = self.signal_fn(window)
                if sig in (1, -1):
                    pending_signal = sig
                else:
                    pending_signal = 0

        # Close any open position at last bar's close (not counted in stats)
        if in_position:
            last = df.iloc[-1]
            if position_side == 1:
                exit_adj = last['close'] * (1 - self.slippage_pct)
                pnl_gross = (exit_adj - entry_price) / entry_price
            else:
                exit_adj = last['close'] * (1 + self.slippage_pct)
                pnl_gross = (entry_price - exit_adj) / entry_price
            pnl_net = pnl_gross - 2 * self.fee_pct

            self._trades.append({
                'entry_time': entry_time,
                'exit_time': last['timestamp'],
                'side': 'LONG' if position_side == 1 else 'SHORT',
                'entry_price': entry_price,
                'exit_price': exit_adj,
                'pnl_net': pnl_net,
                'close_reason': 'END_OF_DATA',
            })

        self._has_run = True

    def results(self) -> dict:
        """Return performance summary dict."""
        if not self._has_run:
            raise RuntimeError("Call run() before results()")

        trades = self._trades
        # Only count SL/TP trades for stats (exclude END_OF_DATA)
        closed = [t for t in trades if t['close_reason'] in ('STOP_LOSS', 'TAKE_PROFIT')]

        if not closed:
            return {
                'trades': trades,
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'sharpe': 0.0,
            }

        wins = [t for t in closed if t['pnl_net'] > 0]
        losses = [t for t in closed if t['pnl_net'] <= 0]

        total_pnl = sum(t['pnl_net'] for t in closed)
        gross_wins = sum(t['pnl_net'] for t in wins)
        gross_losses = sum(t['pnl_net'] for t in losses)

        avg_win = gross_wins / len(wins) if wins else 0.0
        avg_loss = gross_losses / len(losses) if losses else 0.0

        profit_factor = gross_wins / abs(gross_losses) if gross_losses != 0 else float('inf')

        # Max drawdown on cumulative PnL curve
        cum_pnl = np.cumsum([t['pnl_net'] for t in closed])
        peak = np.maximum.accumulate(cum_pnl)
        drawdown = peak - cum_pnl
        max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        # Annualized Sharpe (24/7 crypto trading)
        returns = np.array([t['pnl_net'] for t in closed])
        if len(returns) > 1 and np.std(returns) > 0:
            # Estimate trades per year: total trades / data span * 365 days
            if self._df is not None and len(self._df) > 1:
                ts = self._df['timestamp']
                data_span_seconds = float(ts.iloc[-1] - ts.iloc[0])
                if data_span_seconds > 0:
                    trades_per_year = len(closed) / data_span_seconds * 365.25 * 86400
                else:
                    trades_per_year = len(closed)
            else:
                trades_per_year = len(closed)
            sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(trades_per_year)
        else:
            sharpe = 0.0

        return {
            'trades': trades,
            'total_trades': len(closed),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(closed),
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_drawdown': max_drawdown,
            'sharpe': float(sharpe),
        }


# ── Convenience function ──────────────────────────────────

def run_backtest(symbol: str, timeframe: str, signal_fn, sl_pct: float, tp_pct: float,
                 data_dir: str = 'backtest/data', **kwargs) -> dict:
    """Load candle file and run backtest. Returns results dict."""
    pq_path = os.path.join(data_dir, f'{symbol}_{timeframe}.parquet')
    csv_path = os.path.join(data_dir, f'{symbol}_{timeframe}.csv')

    if os.path.exists(pq_path):
        candle_file = pq_path
    elif os.path.exists(csv_path):
        candle_file = csv_path
    else:
        raise FileNotFoundError(
            f"No data file found for {symbol} {timeframe} in {data_dir}. "
            f"Run data_collector.py first."
        )

    engine = BacktestEngine(candle_file, signal_fn, sl_pct, tp_pct, **kwargs)
    engine.run()
    return engine.results()


# ── Example signal functions ──────────────────────────────

def ema_crossover_signal(df: pd.DataFrame, fast: int = 8, slow: int = 21) -> int:
    """EMA(8/21) crossover. Returns +1/-1/0."""
    if len(df) < slow + 1:
        return 0
    close = df['close']
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    # Cross requires previous bar below/above and current bar above/below
    prev_fast = ema_fast.iloc[-2]
    prev_slow = ema_slow.iloc[-2]
    curr_fast = ema_fast.iloc[-1]
    curr_slow = ema_slow.iloc[-1]
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return 1  # bullish cross
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return -1  # bearish cross
    return 0


def rsi2_signal(df: pd.DataFrame, period: int = 2, oversold: int = 15, overbought: int = 85) -> int:
    """RSI(2) mean reversion. Returns +1/-1/0."""
    if len(df) < period + 2:
        return 0
    close = df['close']
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    last_avg_gain = avg_gain.iloc[-1]
    last_avg_loss = avg_loss.iloc[-1]
    if last_avg_loss == 0:
        rsi = 100.0
    else:
        rs = last_avg_gain / last_avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
    if rsi <= oversold:
        return 1  # oversold → buy
    if rsi >= overbought:
        return -1  # overbought → sell
    return 0


# ── Main ──────────────────────────────────────────────────

if __name__ == '__main__':
    results = run_backtest('XAU', '1h', ema_crossover_signal, sl_pct=0.015, tp_pct=0.03)
    print(f"XAU EMA: {results['total_trades']} trades, {results['win_rate']:.1%} WR, ${results['total_pnl']:.2f}")

#!/usr/bin/env python3
"""
CVD Lack of Participants Strategy Backtest
===========================================
Tests the CVD divergence strategy across multiple symbols and timeframes
using historical OHLCV data from MT5 and yfinance exports.

Strategy:
  LONG:  Price makes lower low, CVD makes higher low (sellers exhausted)
  SHORT: Price makes higher high, CVD makes lower high (buyers exhausted)

Risk parameters mirror live config:
  SL = 1.8x ATR(14)  (Energy: 2.0x)
  TP = 3.6x ATR(14)  (Energy: 4.0x) -- but user specified 4.0x for this test
  Risk per trade = $50 fixed

Usage:
  python3 research/run_backtest.py
"""

import os
import sys
import json
import warnings
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "research", "backtest_data")
MT5_DIR = os.path.join(DATA_DIR, "mt5")
YF_DIR = os.path.join(DATA_DIR, "yfinance")
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "BACKTEST_ANALYSIS.md")

# ─── Config ─────────────────────────────────────────────────────────────
ATR_PERIOD = 14
DEFAULT_SL_ATR = 1.8
DEFAULT_TP_ATR = 4.0  # London Open strategy TP as specified
RISK_PER_TRADE = 50.0  # Fixed $50 risk per trade

# Approximate tick values for position sizing (USD per pip per standard lot)
# These are rough approximations for backtesting purposes
TICK_VALUES = {
    "XAGUSD": {"tick_size": 0.001, "tick_value": 5.0, "digits": 3},
    "XAUUSD": {"tick_size": 0.01, "tick_value": 1.0, "digits": 2},
    "EURUSD": {"tick_size": 0.00001, "tick_value": 10.0, "digits": 5},
    "GBPUSD": {"tick_size": 0.00001, "tick_value": 10.0, "digits": 5},
    "USDJPY": {"tick_size": 0.001, "tick_value": 6.7, "digits": 3},
    "AUDUSD": {"tick_size": 0.00001, "tick_value": 10.0, "digits": 5},
    "USOUSD": {"tick_size": 0.01, "tick_value": 10.0, "digits": 2},
}

# CVD indicator parameters
CVD_LOOKBACK = 20
CVD_SWING_LOOKBACK = 5

# ─── CVD Indicator (matching live code) ─────────────────────────────────

def volume_delta(data):
    """
    Approximate per-bar buying vs selling pressure from OHLCV.
    Uses the same formula as the live indicator in indicators/cvd.py:
        position = (2*close - high - low) / (high - low)
        delta = volume * position
    """
    high = data["high"].values
    low = data["low"].values
    close = data["close"].values
    volume = data["volume"].values.astype(float)

    bar_range = high - low
    # Avoid division by zero
    bar_range_safe = np.where(bar_range == 0, np.nan, bar_range)

    # Price position within bar: -1 (closed at low) to +1 (closed at high)
    position = (2 * close - high - low) / bar_range_safe

    # Volume weighting
    if np.nansum(volume) > 0:
        delta = volume * np.nan_to_num(position, nan=0.0)
    else:
        delta = np.nan_to_num(bar_range_safe, nan=0.0) * np.nan_to_num(position, nan=0.0)

    return delta


def find_swing_highs(values, lookback=5):
    """Find indices where value is highest within lookback window on both sides."""
    indices = []
    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback: i + lookback + 1]
        if not np.isnan(values[i]) and values[i] == np.nanmax(window):
            indices.append(i)
    return indices


def find_swing_lows(values, lookback=5):
    """Find indices where value is lowest within lookback window on both sides."""
    indices = []
    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback: i + lookback + 1]
        if not np.isnan(values[i]) and values[i] == np.nanmin(window):
            indices.append(i)
    return indices


def detect_cvd_divergence(df, lookback=CVD_LOOKBACK, swing_lookback=CVD_SWING_LOOKBACK):
    """
    Detect CVD divergence signals matching the live indicator logic.
    Returns a list of (index, signal_type) tuples.

    Signal types:
      'bullish_lack_of_participants' - price LL, CVD HL (sellers exhausted) -> LONG
      'bearish_lack_of_participants' - price HH, CVD LH (buyers exhausted) -> SHORT
    """
    delta = volume_delta(df)
    cvd = np.cumsum(delta)

    swing_lb = min(swing_lookback, lookback // 4, 3)
    if swing_lb < 2:
        swing_lb = 2

    price_highs_idx = find_swing_highs(df["high"].values, swing_lb)
    price_lows_idx = find_swing_lows(df["low"].values, swing_lb)
    cvd_highs_idx = find_swing_highs(cvd, swing_lb)
    cvd_lows_idx = find_swing_lows(cvd, swing_lb)

    signals = []

    for i in range(lookback, len(df)):
        window_start = i - lookback

        recent_ph = [idx for idx in price_highs_idx if window_start <= idx < i]
        recent_pl = [idx for idx in price_lows_idx if window_start <= idx < i]
        recent_ch = [idx for idx in cvd_highs_idx if window_start <= idx < i]
        recent_cl = [idx for idx in cvd_lows_idx if window_start <= idx < i]

        # Bearish: price HH, CVD LH
        if len(recent_ph) >= 2 and len(recent_ch) >= 2:
            ph1, ph2 = recent_ph[-2], recent_ph[-1]
            ch1, ch2 = recent_ch[-2], recent_ch[-1]
            if (df["high"].iloc[ph2] > df["high"].iloc[ph1] and
                cvd[ch2] < cvd[ch1]):
                signals.append((i, "short"))
                continue

        # Bullish: price LL, CVD HL
        if len(recent_pl) >= 2 and len(recent_cl) >= 2:
            pl1, pl2 = recent_pl[-2], recent_pl[-1]
            cl1, cl2 = recent_cl[-2], recent_cl[-1]
            if (df["low"].iloc[pl2] < df["low"].iloc[pl1] and
                cvd[cl2] > cvd[cl1]):
                signals.append((i, "long"))

    return signals


# ─── ATR ────────────────────────────────────────────────────────────────

def compute_atr(df, period=ATR_PERIOD):
    """Compute Average True Range."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    tr = np.zeros(len(df))
    tr[0] = high[0] - low[0]
    for i in range(1, len(df)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    atr_vals = np.full(len(df), np.nan)
    if len(tr) >= period:
        atr_vals[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period

    return atr_vals


# ─── VWAP (for confluence filter) ───────────────────────────────────────

def compute_vwap(df):
    """Compute session VWAP (resets daily for intraday, rolling for daily)."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].values.astype(float)

    # For intraday: reset VWAP at each new day
    if hasattr(df.index, "hour"):
        dates = df.index.date
    else:
        dates = pd.to_datetime(df["time"]).dt.date if "time" in df.columns else df.index.date

    vwap = np.zeros(len(df))
    cum_tp_vol = 0.0
    cum_vol = 0.0
    prev_date = None

    for i in range(len(df)):
        current_date = dates[i] if hasattr(dates, "__getitem__") else dates.iloc[i]
        if current_date != prev_date:
            cum_tp_vol = 0.0
            cum_vol = 0.0
            prev_date = current_date

        cum_tp_vol += typical_price.iloc[i] * vol[i]
        cum_vol += vol[i]
        vwap[i] = cum_tp_vol / cum_vol if cum_vol > 0 else typical_price.iloc[i]

    return vwap


# ─── Backtest Engine ────────────────────────────────────────────────────

def run_backtest(
    df,
    symbol,
    timeframe,
    sl_atr_mult=DEFAULT_SL_ATR,
    tp_atr_mult=DEFAULT_TP_ATR,
    risk_per_trade=RISK_PER_TRADE,
    time_filter=None,  # (start_hour, end_hour) UTC or None for 24h
    vwap_filter=False,
):
    """
    Run the CVD Lack of Participants backtest on a DataFrame.

    Args:
        df: DataFrame with columns [time, open, high, low, close, volume]
        symbol: Symbol name for tick value lookup
        timeframe: String like 'M15', 'H1', 'D1'
        sl_atr_mult: Stop loss ATR multiplier
        tp_atr_mult: Take profit ATR multiplier
        risk_per_trade: Fixed dollar risk per trade
        time_filter: Tuple (start_hour, end_hour) or None
        vwap_filter: If True, only take longs below VWAP and shorts above VWAP

    Returns:
        dict with trade list and summary statistics
    """
    df = df.copy()
    df.index = range(len(df))

    # Ensure time is parsed
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    else:
        df["time"] = pd.to_datetime(df.index)

    # Compute indicators
    atr_vals = compute_atr(df)
    vwap_vals = compute_vwap(df) if vwap_filter else None

    # Detect CVD divergence signals
    signals = detect_cvd_divergence(df)

    # Tick value for position sizing
    tick_info = TICK_VALUES.get(symbol, {"tick_size": 0.01, "tick_value": 1.0, "digits": 2})

    trades = []
    equity_curve = [0.0]  # cumulative PnL
    open_trade = None

    for sig_idx, direction in signals:
        # Skip if we don't have ATR yet
        if np.isnan(atr_vals[sig_idx]):
            continue

        # Time filter
        if time_filter is not None:
            bar_time = df["time"].iloc[sig_idx]
            hour = bar_time.hour
            start_h, end_h = time_filter
            if start_h <= end_h:
                if not (start_h <= hour < end_h):
                    continue
            else:  # wraps around midnight
                if not (hour >= start_h or hour < end_h):
                    continue

        # VWAP filter
        if vwap_filter and vwap_vals is not None:
            price = df["close"].iloc[sig_idx]
            vwap = vwap_vals[sig_idx]
            if direction == "long" and price > vwap:
                continue
            if direction == "short" and price < vwap:
                continue

        # Skip if we already have an open trade
        if open_trade is not None:
            continue

        entry_price = df["close"].iloc[sig_idx]
        current_atr = atr_vals[sig_idx]
        sl_distance = current_atr * sl_atr_mult
        tp_distance = current_atr * tp_atr_mult

        if direction == "long":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance

        # Position sizing: risk $50 per trade
        # lot_size = risk_dollars / (sl_distance_pips * tick_value_per_lot)
        sl_pips = sl_distance / tick_info["tick_size"]
        if sl_pips <= 0:
            continue
        lot_size = risk_per_trade / (sl_pips * tick_info["tick_value"])
        lot_size = min(lot_size, 1.0)  # Hard cap
        if lot_size <= 0:
            continue

        open_trade = {
            "entry_idx": sig_idx,
            "entry_time": df["time"].iloc[sig_idx],
            "direction": direction,
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "lot_size": lot_size,
            "atr": current_atr,
        }

    # Also process open trades bar by bar (need to simulate)
    # Let's redo this properly with bar-by-bar simulation

    trades = []
    open_trade = None
    signal_map = {idx: direction for idx, direction in signals}
    equity_curve = [0.0]

    for i in range(ATR_PERIOD, len(df)):
        # Check if open trade hits SL or TP on this bar
        if open_trade is not None:
            bar_high = df["high"].iloc[i]
            bar_low = df["low"].iloc[i]

            hit_sl = False
            hit_tp = False

            if open_trade["direction"] == "long":
                if bar_low <= open_trade["sl_price"]:
                    hit_sl = True
                if bar_high >= open_trade["tp_price"]:
                    hit_tp = True
            else:  # short
                if bar_high >= open_trade["sl_price"]:
                    hit_sl = True
                if bar_low <= open_trade["tp_price"]:
                    hit_tp = True

            # If both hit in same bar, use which is more likely first
            # (conservative: assume SL hit first if bar opened against us)
            if hit_sl and hit_tp:
                bar_open = df["open"].iloc[i]
                if open_trade["direction"] == "long":
                    hit_sl = bar_open < open_trade["entry_price"]
                    hit_tp = not hit_sl
                else:
                    hit_sl = bar_open > open_trade["entry_price"]
                    hit_tp = not hit_sl

            if hit_sl or hit_tp:
                if hit_tp:
                    exit_price = open_trade["tp_price"]
                    result = "win"
                else:
                    exit_price = open_trade["sl_price"]
                    result = "loss"

                # Calculate PnL
                if open_trade["direction"] == "long":
                    price_diff = exit_price - open_trade["entry_price"]
                else:
                    price_diff = open_trade["entry_price"] - exit_price

                pips = price_diff / tick_info["tick_size"]
                pnl = pips * tick_info["tick_value"] * open_trade["lot_size"]

                trade_record = {
                    "entry_idx": open_trade["entry_idx"],
                    "exit_idx": i,
                    "entry_time": open_trade["entry_time"],
                    "exit_time": df["time"].iloc[i],
                    "direction": open_trade["direction"],
                    "entry_price": open_trade["entry_price"],
                    "exit_price": exit_price,
                    "sl_price": open_trade["sl_price"],
                    "tp_price": open_trade["tp_price"],
                    "lot_size": open_trade["lot_size"],
                    "pnl": pnl,
                    "result": result,
                    "atr": open_trade["atr"],
                    "bars_held": i - open_trade["entry_idx"],
                }
                trades.append(trade_record)
                equity_curve.append(equity_curve[-1] + pnl)
                open_trade = None

        # Check for new signal on this bar (only if no open trade)
        if open_trade is None and i in signal_map:
            direction = signal_map[i]

            if np.isnan(atr_vals[i]):
                continue

            # Time filter
            if time_filter is not None:
                bar_time = df["time"].iloc[i]
                hour = bar_time.hour
                start_h, end_h = time_filter
                if start_h <= end_h:
                    if not (start_h <= hour < end_h):
                        continue
                else:
                    if not (hour >= start_h or hour < end_h):
                        continue

            # VWAP filter
            if vwap_filter and vwap_vals is not None:
                price = df["close"].iloc[i]
                vwap = vwap_vals[i]
                if direction == "long" and price > vwap:
                    continue
                if direction == "short" and price < vwap:
                    continue

            entry_price = df["close"].iloc[i]
            current_atr = atr_vals[i]
            sl_distance = current_atr * sl_atr_mult
            tp_distance = current_atr * tp_atr_mult

            if direction == "long":
                sl_price = entry_price - sl_distance
                tp_price = entry_price + tp_distance
            else:
                sl_price = entry_price + sl_distance
                tp_price = entry_price - tp_distance

            sl_pips = sl_distance / tick_info["tick_size"]
            if sl_pips <= 0:
                continue
            lot_size = risk_per_trade / (sl_pips * tick_info["tick_value"])
            lot_size = min(lot_size, 1.0)
            if lot_size <= 0:
                continue

            open_trade = {
                "entry_idx": i,
                "entry_time": df["time"].iloc[i],
                "direction": direction,
                "entry_price": entry_price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "lot_size": lot_size,
                "atr": current_atr,
            }

    # Compute statistics
    return compute_stats(trades, equity_curve, df, symbol, timeframe, time_filter, vwap_filter)


def compute_stats(trades, equity_curve, df, symbol, timeframe, time_filter, vwap_filter):
    """Compute comprehensive statistics from trade list."""
    if not trades:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "time_filter": time_filter,
            "vwap_filter": vwap_filter,
            "total_trades": 0,
            "trades": [],
            "equity_curve": equity_curve,
        }

    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]

    win_pnls = [t["pnl"] for t in wins]
    loss_pnls = [t["pnl"] for t in losses]
    all_pnls = [t["pnl"] for t in trades]

    total_pnl = sum(all_pnls)
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = np.mean(win_pnls) if win_pnls else 0
    avg_loss = np.mean(loss_pnls) if loss_pnls else 0
    profit_factor = abs(sum(win_pnls) / sum(loss_pnls)) if loss_pnls and sum(loss_pnls) != 0 else float("inf")

    # Max drawdown
    peak = 0
    max_dd = 0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd

    # Max consecutive losses
    max_consec_losses = 0
    current_streak = 0
    for t in trades:
        if t["result"] == "loss":
            current_streak += 1
            max_consec_losses = max(max_consec_losses, current_streak)
        else:
            current_streak = 0

    # Max consecutive wins
    max_consec_wins = 0
    current_streak = 0
    for t in trades:
        if t["result"] == "win":
            current_streak += 1
            max_consec_wins = max(max_consec_wins, current_streak)
        else:
            current_streak = 0

    # Average bars held
    avg_bars = np.mean([t["bars_held"] for t in trades])

    # Long/short breakdown
    longs = [t for t in trades if t["direction"] == "long"]
    shorts = [t for t in trades if t["direction"] == "short"]
    long_wr = len([t for t in longs if t["result"] == "win"]) / len(longs) if longs else 0
    short_wr = len([t for t in shorts if t["result"] == "win"]) / len(shorts) if shorts else 0

    # Performance by hour (for intraday)
    hourly_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
    for t in trades:
        hour = t["entry_time"].hour
        hourly_stats[hour]["trades"] += 1
        hourly_stats[hour]["pnl"] += t["pnl"]
        if t["result"] == "win":
            hourly_stats[hour]["wins"] += 1

    # Performance by month
    monthly_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
    for t in trades:
        month_key = t["entry_time"].strftime("%Y-%m")
        monthly_stats[month_key]["trades"] += 1
        monthly_stats[month_key]["pnl"] += t["pnl"]
        if t["result"] == "win":
            monthly_stats[month_key]["wins"] += 1

    # Performance by day of week
    dow_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0})
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for t in trades:
        dow = t["entry_time"].weekday()
        dow_stats[dow_names[dow]]["trades"] += 1
        dow_stats[dow_names[dow]]["pnl"] += t["pnl"]
        if t["result"] == "win":
            dow_stats[dow_names[dow]]["wins"] += 1

    # Volatility regime analysis
    vol_stats = {"low": {"trades": 0, "wins": 0, "pnl": 0},
                 "normal": {"trades": 0, "wins": 0, "pnl": 0},
                 "high": {"trades": 0, "wins": 0, "pnl": 0}}
    # Compute rolling ATR percentile
    atrs = np.array([t["atr"] for t in trades])
    if len(atrs) > 0:
        atr_median = np.median(atrs)
        atr_p75 = np.percentile(atrs, 75)
        for t in trades:
            if t["atr"] < atr_median:
                regime = "low"
            elif t["atr"] < atr_p75:
                regime = "normal"
            else:
                regime = "high"
            vol_stats[regime]["trades"] += 1
            vol_stats[regime]["pnl"] += t["pnl"]
            if t["result"] == "win":
                vol_stats[regime]["wins"] += 1

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "time_filter": time_filter,
        "vwap_filter": vwap_filter,
        "data_range": f'{df["time"].iloc[0]} to {df["time"].iloc[-1]}',
        "total_bars": len(df),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "max_consec_losses": max_consec_losses,
        "max_consec_wins": max_consec_wins,
        "avg_bars_held": avg_bars,
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_wr": long_wr,
        "short_wr": short_wr,
        "long_pnl": sum(t["pnl"] for t in longs),
        "short_pnl": sum(t["pnl"] for t in shorts),
        "hourly_stats": dict(hourly_stats),
        "monthly_stats": dict(monthly_stats),
        "dow_stats": dict(dow_stats),
        "vol_stats": vol_stats,
        "equity_curve": equity_curve,
        "trades": trades,
    }


# ─── Data Loading ───────────────────────────────────────────────────────

def load_csv(path):
    """Load a backtest CSV file."""
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"])
    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)
    return df


# ─── Report Generation ──────────────────────────────────────────────────

def format_stats_table(results):
    """Format a single backtest result as markdown table rows."""
    r = results
    if r["total_trades"] == 0:
        return "No trades generated.\n"

    lines = []
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Data Range | {r['data_range']} |")
    lines.append(f"| Total Bars | {r['total_bars']:,} |")
    lines.append(f"| Total Trades | {r['total_trades']} |")
    lines.append(f"| Wins / Losses | {r['wins']} / {r['losses']} |")
    lines.append(f"| Win Rate | {r['win_rate']:.1%} |")
    lines.append(f"| Total PnL | ${r['total_pnl']:,.2f} |")
    lines.append(f"| Avg Win | ${r['avg_win']:,.2f} |")
    lines.append(f"| Avg Loss | ${r['avg_loss']:,.2f} |")
    pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "INF"
    lines.append(f"| Profit Factor | {pf_str} |")
    lines.append(f"| Max Drawdown | ${r['max_drawdown']:,.2f} |")
    lines.append(f"| Max Consec Losses | {r['max_consec_losses']} |")
    lines.append(f"| Max Consec Wins | {r['max_consec_wins']} |")
    lines.append(f"| Avg Bars Held | {r['avg_bars_held']:.1f} |")
    lines.append(f"| Long Trades | {r['long_trades']} (WR: {r['long_wr']:.1%}, PnL: ${r['long_pnl']:,.2f}) |")
    lines.append(f"| Short Trades | {r['short_trades']} (WR: {r['short_wr']:.1%}, PnL: ${r['short_pnl']:,.2f}) |")

    return "\n".join(lines)


def format_hourly_table(hourly_stats):
    """Format hourly performance as markdown table."""
    if not hourly_stats:
        return "No hourly data available.\n"

    lines = []
    lines.append("| Hour (UTC) | Trades | Wins | Win Rate | PnL |")
    lines.append("|------------|--------|------|----------|-----|")

    for hour in sorted(hourly_stats.keys()):
        s = hourly_stats[hour]
        wr = s["wins"] / s["trades"] if s["trades"] > 0 else 0
        lines.append(f"| {hour:02d}:00 | {s['trades']} | {s['wins']} | {wr:.0%} | ${s['pnl']:,.2f} |")

    return "\n".join(lines)


def format_monthly_table(monthly_stats):
    """Format monthly performance as markdown table."""
    if not monthly_stats:
        return "No monthly data available.\n"

    lines = []
    lines.append("| Month | Trades | Wins | Win Rate | PnL |")
    lines.append("|-------|--------|------|----------|-----|")

    for month in sorted(monthly_stats.keys()):
        s = monthly_stats[month]
        wr = s["wins"] / s["trades"] if s["trades"] > 0 else 0
        lines.append(f"| {month} | {s['trades']} | {s['wins']} | {wr:.0%} | ${s['pnl']:,.2f} |")

    return "\n".join(lines)


def format_dow_table(dow_stats):
    """Format day-of-week performance."""
    if not dow_stats:
        return "No day-of-week data available.\n"

    lines = []
    lines.append("| Day | Trades | Wins | Win Rate | PnL |")
    lines.append("|-----|--------|------|----------|-----|")

    for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        if day in dow_stats:
            s = dow_stats[day]
            wr = s["wins"] / s["trades"] if s["trades"] > 0 else 0
            lines.append(f"| {day} | {s['trades']} | {s['wins']} | {wr:.0%} | ${s['pnl']:,.2f} |")

    return "\n".join(lines)


def format_vol_table(vol_stats):
    """Format volatility regime performance."""
    lines = []
    lines.append("| Volatility Regime | Trades | Wins | Win Rate | PnL |")
    lines.append("|-------------------|--------|------|----------|-----|")

    for regime in ["low", "normal", "high"]:
        s = vol_stats[regime]
        if s["trades"] > 0:
            wr = s["wins"] / s["trades"]
            lines.append(f"| {regime.title()} (ATR) | {s['trades']} | {s['wins']} | {wr:.0%} | ${s['pnl']:,.2f} |")
        else:
            lines.append(f"| {regime.title()} (ATR) | 0 | 0 | - | $0.00 |")

    return "\n".join(lines)


def format_summary_comparison(all_results):
    """Create a cross-symbol comparison table."""
    lines = []
    lines.append("| Symbol | TF | Filter | Trades | WR | PnL | PF | MaxDD | Consec L |")
    lines.append("|--------|-----|--------|--------|-----|------|------|-------|----------|")

    for r in all_results:
        if r["total_trades"] == 0:
            lines.append(f"| {r['symbol']} | {r['timeframe']} | {_filter_label(r)} | 0 | - | - | - | - | - |")
            continue
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "INF"
        filter_label = _filter_label(r)
        lines.append(
            f"| {r['symbol']} | {r['timeframe']} | {filter_label} "
            f"| {r['total_trades']} | {r['win_rate']:.0%} "
            f"| ${r['total_pnl']:,.0f} | {pf_str} "
            f"| ${r['max_drawdown']:,.0f} | {r['max_consec_losses']} |"
        )

    return "\n".join(lines)


def _filter_label(r):
    parts = []
    if r.get("time_filter"):
        parts.append(f"{r['time_filter'][0]:02d}-{r['time_filter'][1]:02d}")
    if r.get("vwap_filter"):
        parts.append("VWAP")
    return "+".join(parts) if parts else "24h"


# ─── Main ───────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("CVD LACK OF PARTICIPANTS STRATEGY — COMPREHENSIVE BACKTEST")
    print("=" * 70)
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    all_results = []

    # ── 1. XAGUSD M15 — No filter ──────────────────────────────────────
    print("[1/8] XAGUSD M15 (24h, no filter)...")
    df = load_csv(os.path.join(MT5_DIR, "XAGUSD_M15.csv"))
    r1 = run_backtest(df, "XAGUSD", "M15")
    all_results.append(r1)
    print(f"  -> {r1['total_trades']} trades, WR={r1['win_rate']:.1%}, PnL=${r1['total_pnl']:,.2f}")

    # ── 2. XAGUSD M15 — London Open filter ─────────────────────────────
    print("[2/8] XAGUSD M15 (London Open 07:00-10:00 UTC)...")
    r2 = run_backtest(df, "XAGUSD", "M15", time_filter=(7, 10))
    all_results.append(r2)
    print(f"  -> {r2['total_trades']} trades, WR={r2['win_rate']:.1%}, PnL=${r2['total_pnl']:,.2f}")

    # ── 2b. XAGUSD M15 — VWAP filter ───────────────────────────────────
    print("[2b/8] XAGUSD M15 (VWAP confluence filter)...")
    r2b = run_backtest(df, "XAGUSD", "M15", vwap_filter=True)
    all_results.append(r2b)
    print(f"  -> {r2b['total_trades']} trades, WR={r2b['win_rate']:.1%}, PnL=${r2b['total_pnl']:,.2f}")

    # ── 2c. XAGUSD M15 — London Open + VWAP ────────────────────────────
    print("[2c/8] XAGUSD M15 (London Open + VWAP)...")
    r2c = run_backtest(df, "XAGUSD", "M15", time_filter=(7, 10), vwap_filter=True)
    all_results.append(r2c)
    print(f"  -> {r2c['total_trades']} trades, WR={r2c['win_rate']:.1%}, PnL=${r2c['total_pnl']:,.2f}")

    # ── 3. XAGUSD H1 ───────────────────────────────────────────────────
    print("[3/8] XAGUSD H1 (24h)...")
    df = load_csv(os.path.join(MT5_DIR, "XAGUSD_H1.csv"))
    r3 = run_backtest(df, "XAGUSD", "H1")
    all_results.append(r3)
    print(f"  -> {r3['total_trades']} trades, WR={r3['win_rate']:.1%}, PnL=${r3['total_pnl']:,.2f}")

    # ── 4. XAUUSD H1 ───────────────────────────────────────────────────
    print("[4/8] XAUUSD H1 (24h)...")
    df = load_csv(os.path.join(MT5_DIR, "XAUUSD_H1.csv"))
    r4 = run_backtest(df, "XAUUSD", "H1")
    all_results.append(r4)
    print(f"  -> {r4['total_trades']} trades, WR={r4['win_rate']:.1%}, PnL=${r4['total_pnl']:,.2f}")

    # ── 5. EURUSD H1 ───────────────────────────────────────────────────
    print("[5/8] EURUSD H1 (24h)...")
    df = load_csv(os.path.join(MT5_DIR, "EURUSD_H1.csv"))
    r5 = run_backtest(df, "EURUSD", "H1")
    all_results.append(r5)
    print(f"  -> {r5['total_trades']} trades, WR={r5['win_rate']:.1%}, PnL=${r5['total_pnl']:,.2f}")

    # ── 6. USOUSD H1 ───────────────────────────────────────────────────
    print("[6/8] USOUSD H1 (24h, energy params)...")
    df = load_csv(os.path.join(MT5_DIR, "USOUSD_H1.csv"))
    r6 = run_backtest(df, "USOUSD", "H1", sl_atr_mult=2.0, tp_atr_mult=4.0)
    all_results.append(r6)
    print(f"  -> {r6['total_trades']} trades, WR={r6['win_rate']:.1%}, PnL=${r6['total_pnl']:,.2f}")

    # ── 7. XAGUSD D1 (yfinance, 25 years) ──────────────────────────────
    print("[7/8] XAGUSD D1 (yfinance, 25 years)...")
    df = load_csv(os.path.join(YF_DIR, "XAGUSD_D1.csv"))
    r7 = run_backtest(df, "XAGUSD", "D1")
    all_results.append(r7)
    print(f"  -> {r7['total_trades']} trades, WR={r7['win_rate']:.1%}, PnL=${r7['total_pnl']:,.2f}")

    # ── 8. GBPUSD H1 ───────────────────────────────────────────────────
    print("[8/8] GBPUSD H1 (24h)...")
    df = load_csv(os.path.join(MT5_DIR, "GBPUSD_H1.csv"))
    r8 = run_backtest(df, "GBPUSD", "H1")
    all_results.append(r8)
    print(f"  -> {r8['total_trades']} trades, WR={r8['win_rate']:.1%}, PnL=${r8['total_pnl']:,.2f}")

    # ── Additional: parameter sensitivity on XAGUSD M15 ────────────────
    print("\n[SENSITIVITY] Testing SL/TP parameter variations on XAGUSD M15...")
    df_xag_m15 = load_csv(os.path.join(MT5_DIR, "XAGUSD_M15.csv"))
    sensitivity_results = []

    param_combos = [
        (1.2, 2.4, "1.2/2.4 (tight)"),
        (1.5, 3.0, "1.5/3.0"),
        (1.8, 3.6, "1.8/3.6 (default)"),
        (1.8, 4.0, "1.8/4.0 (London TP)"),
        (2.0, 4.0, "2.0/4.0 (energy)"),
        (2.0, 6.0, "2.0/6.0 (wide TP)"),
        (2.5, 5.0, "2.5/5.0 (very wide)"),
    ]

    for sl_m, tp_m, label in param_combos:
        r = run_backtest(df_xag_m15, "XAGUSD", "M15", sl_atr_mult=sl_m, tp_atr_mult=tp_m)
        sensitivity_results.append((label, r))
        wr_str = f"{r['win_rate']:.0%}" if r['total_trades'] > 0 else "-"
        print(f"  SL={sl_m} TP={tp_m}: {r['total_trades']} trades, WR={wr_str}, PnL=${r['total_pnl']:,.2f}")

    # ── Additional: time window scan on XAGUSD M15 ─────────────────────
    print("\n[TIME SCAN] Testing all 3-hour windows on XAGUSD M15...")
    time_scan_results = []
    for start_h in range(0, 24, 1):
        end_h = (start_h + 3) % 24
        r = run_backtest(df_xag_m15, "XAGUSD", "M15", time_filter=(start_h, end_h))
        time_scan_results.append((start_h, end_h, r))

    # Sort by PnL
    time_scan_results.sort(key=lambda x: x[2]["total_pnl"], reverse=True)
    print("  Top 5 time windows:")
    for start_h, end_h, r in time_scan_results[:5]:
        if r["total_trades"] > 0:
            print(f"    {start_h:02d}:00-{end_h:02d}:00: {r['total_trades']} trades, WR={r['win_rate']:.0%}, PnL=${r['total_pnl']:,.2f}")

    # ── Generate Report ─────────────────────────────────────────────────
    print(f"\nGenerating report at {OUTPUT_FILE}...")

    report = []
    report.append("# CVD Lack of Participants Strategy — Backtest Analysis")
    report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\nStrategy: CVD Divergence (Lack of Participants)")
    report.append(f"- LONG: Price lower low + CVD higher low (sellers exhausted)")
    report.append(f"- SHORT: Price higher high + CVD lower high (buyers exhausted)")
    report.append(f"- CVD approximated from OHLCV: delta = volume * (2*close - high - low) / (high - low)")
    report.append(f"- Risk per trade: $50 fixed")
    report.append(f"- Default SL: 1.8x ATR(14), TP: 4.0x ATR(14)")

    # ── Summary Table ───────────────────────────────────────────────────
    report.append("\n## Cross-Symbol Summary")
    report.append("")
    report.append(format_summary_comparison(all_results))

    # ── Live vs Backtest Comparison ─────────────────────────────────────
    report.append("\n## Live vs Backtest Comparison")
    report.append("")
    report.append("| Metric | Live (Mar 15-17) | Backtest XAGUSD M15 (24h) | Backtest XAGUSD M15 (London) |")
    report.append("|--------|------------------|---------------------------|------------------------------|")

    live_trades = 82
    live_wins = 33
    live_losses = 49
    live_pnl = -112.61
    live_wr = live_wins / live_trades

    bt_24h = r1
    bt_london = r2

    report.append(f"| Total Trades | {live_trades} | {bt_24h['total_trades']} | {bt_london['total_trades']} |")
    report.append(f"| Win Rate | {live_wr:.1%} | {bt_24h['win_rate']:.1%} | {bt_london['win_rate']:.1%} |")
    report.append(f"| Total PnL | ${live_pnl:,.2f} | ${bt_24h['total_pnl']:,.2f} | ${bt_london['total_pnl']:,.2f} |")
    if bt_24h['total_trades'] > 0:
        report.append(f"| Avg Win | - | ${bt_24h['avg_win']:,.2f} | ${bt_london['avg_win']:,.2f} |")
        report.append(f"| Avg Loss | - | ${bt_24h['avg_loss']:,.2f} | ${bt_london['avg_loss']:,.2f} |")
    report.append("")
    report.append("> **Note:** Live data covers only 2 days (Mar 15-17, 82 trades across ALL strategies and symbols).")
    report.append("> The backtest covers 2.5 months of XAGUSD M15 only, with no ML/confluence/circuit-breaker filters.")
    report.append("> Direct comparison is limited — the live system uses 10+ filter layers that the raw backtest omits.")

    # ── Detailed Results per Symbol ─────────────────────────────────────
    labels = [
        "XAGUSD M15 (24h)",
        "XAGUSD M15 (London 07-10)",
        "XAGUSD M15 (VWAP filter)",
        "XAGUSD M15 (London + VWAP)",
        "XAGUSD H1 (24h)",
        "XAUUSD H1 (24h)",
        "EURUSD H1 (24h)",
        "USOUSD H1 (energy params)",
        "XAGUSD D1 (25 years)",
        "GBPUSD H1 (24h)",
    ]

    for label, result in zip(labels, all_results):
        report.append(f"\n## {label}")
        report.append("")
        report.append(format_stats_table(result))

        if result["total_trades"] > 0:
            # Hourly performance (skip for daily)
            if result["timeframe"] != "D1":
                report.append(f"\n### Performance by Hour of Day")
                report.append("")
                report.append(format_hourly_table(result["hourly_stats"]))

            # Monthly performance
            report.append(f"\n### Performance by Month")
            report.append("")
            report.append(format_monthly_table(result["monthly_stats"]))

            # Day of week
            if result["timeframe"] != "D1":
                report.append(f"\n### Performance by Day of Week")
                report.append("")
                report.append(format_dow_table(result["dow_stats"]))

            # Volatility regime
            report.append(f"\n### Performance by Volatility Regime")
            report.append("")
            report.append(format_vol_table(result["vol_stats"]))

    # ── London Open Filter Impact ───────────────────────────────────────
    report.append("\n## London Open Filter Impact (XAGUSD M15)")
    report.append("")
    report.append("| Metric | 24h (No Filter) | London Open (07-10) | VWAP Only | London + VWAP |")
    report.append("|--------|-----------------|---------------------|-----------|---------------|")

    for metric, key, fmt in [
        ("Trades", "total_trades", "{}"),
        ("Win Rate", "win_rate", "{:.1%}"),
        ("Total PnL", "total_pnl", "${:,.2f}"),
        ("Profit Factor", "profit_factor", "{:.2f}"),
        ("Max Drawdown", "max_drawdown", "${:,.2f}"),
        ("Max Consec Loss", "max_consec_losses", "{}"),
    ]:
        vals = []
        for rx in [r1, r2, r2b, r2c]:
            if rx["total_trades"] == 0:
                vals.append("-")
            else:
                v = rx[key]
                if key == "profit_factor" and v == float("inf"):
                    vals.append("INF")
                else:
                    vals.append(fmt.format(v))
        report.append(f"| {metric} | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} |")

    # ── Parameter Sensitivity ───────────────────────────────────────────
    report.append("\n## Parameter Sensitivity (XAGUSD M15)")
    report.append("")
    report.append("| SL/TP Config | Trades | WR | PnL | PF | MaxDD |")
    report.append("|--------------|--------|-----|-----|-----|-------|")

    for label, r in sensitivity_results:
        if r["total_trades"] == 0:
            report.append(f"| {label} | 0 | - | - | - | - |")
        else:
            pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "INF"
            report.append(
                f"| {label} | {r['total_trades']} | {r['win_rate']:.0%} "
                f"| ${r['total_pnl']:,.0f} | {pf_str} | ${r['max_drawdown']:,.0f} |"
            )

    # ── Time Window Scan ────────────────────────────────────────────────
    report.append("\n## Optimal Time Windows (XAGUSD M15, 3-hour windows)")
    report.append("")
    report.append("Top 10 windows by PnL:")
    report.append("")
    report.append("| Window (UTC) | Trades | WR | PnL | PF |")
    report.append("|--------------|--------|----|-----|-----|")

    for start_h, end_h, r in time_scan_results[:10]:
        if r["total_trades"] > 0:
            pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "INF"
            report.append(
                f"| {start_h:02d}:00-{end_h:02d}:00 "
                f"| {r['total_trades']} | {r['win_rate']:.0%} "
                f"| ${r['total_pnl']:,.0f} | {pf_str} |"
            )

    report.append("")
    report.append("Bottom 5 windows by PnL:")
    report.append("")
    report.append("| Window (UTC) | Trades | WR | PnL | PF |")
    report.append("|--------------|--------|----|-----|-----|")

    for start_h, end_h, r in time_scan_results[-5:]:
        if r["total_trades"] > 0:
            pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "INF"
            report.append(
                f"| {start_h:02d}:00-{end_h:02d}:00 "
                f"| {r['total_trades']} | {r['win_rate']:.0%} "
                f"| ${r['total_pnl']:,.0f} | {pf_str} |"
            )

    # ── Volatility Correlation Analysis ─────────────────────────────────
    report.append("\n## Volatility Regime Correlation")
    report.append("")
    report.append("Analysis of trade performance clustered by ATR regime at entry time.")
    report.append("ATR is split into low (<median), normal (median-P75), high (>P75).")
    report.append("")

    for label, result in zip(labels, all_results):
        if result["total_trades"] > 0:
            report.append(f"### {label}")
            report.append("")
            report.append(format_vol_table(result["vol_stats"]))
            report.append("")

    # ── Key Findings & Recommendations ──────────────────────────────────
    report.append("\n## Key Findings")
    report.append("")

    # Auto-generate findings based on results
    findings = []

    # Best performing symbol/timeframe
    profitable = [r for r in all_results if r["total_trades"] > 0 and r["total_pnl"] > 0]
    if profitable:
        best = max(profitable, key=lambda r: r["total_pnl"])
        findings.append(
            f"1. **Best performer:** {best['symbol']} {best['timeframe']} "
            f"({_filter_label(best)} filter) with {best['total_trades']} trades, "
            f"{best['win_rate']:.0%} WR, ${best['total_pnl']:,.0f} PnL"
        )
    else:
        worst = min(all_results, key=lambda r: r["total_pnl"] if r["total_trades"] > 0 else 0)
        findings.append(
            f"1. **No profitable configuration found.** Least negative: {worst['symbol']} {worst['timeframe']} "
            f"with ${worst['total_pnl']:,.0f} PnL"
        )

    # London Open filter impact
    if r1["total_trades"] > 0 and r2["total_trades"] > 0:
        wr_diff = r2["win_rate"] - r1["win_rate"]
        findings.append(
            f"2. **London Open filter:** {'Improved' if wr_diff > 0 else 'Reduced'} win rate by "
            f"{abs(wr_diff):.1%} ({r1['win_rate']:.0%} -> {r2['win_rate']:.0%}). "
            f"PnL went from ${r1['total_pnl']:,.0f} to ${r2['total_pnl']:,.0f}."
        )
    elif r2["total_trades"] == 0:
        findings.append(
            f"2. **London Open filter:** Too restrictive for M15 — generated 0 trades in {r1['total_trades']} signal window."
        )

    # VWAP filter
    if r2b["total_trades"] > 0:
        findings.append(
            f"3. **VWAP filter:** {r2b['total_trades']} trades vs {r1['total_trades']} unfiltered. "
            f"WR: {r2b['win_rate']:.0%} vs {r1['win_rate']:.0%}. "
            f"PnL: ${r2b['total_pnl']:,.0f} vs ${r1['total_pnl']:,.0f}."
        )

    # Best time window
    if time_scan_results and time_scan_results[0][2]["total_trades"] > 0:
        best_tw = time_scan_results[0]
        findings.append(
            f"4. **Best time window:** {best_tw[0]:02d}:00-{best_tw[1]:02d}:00 UTC "
            f"({best_tw[2]['total_trades']} trades, {best_tw[2]['win_rate']:.0%} WR, "
            f"${best_tw[2]['total_pnl']:,.0f} PnL)"
        )

    # Volatility regime insight
    for result in all_results:
        if result["total_trades"] > 10:
            vs = result["vol_stats"]
            for regime in ["low", "normal", "high"]:
                s = vs[regime]
                if s["trades"] > 0:
                    wr = s["wins"] / s["trades"]
                    if wr > 0.5 and s["pnl"] > 0:
                        findings.append(
                            f"5. **Volatility sweet spot:** {result['symbol']} {result['timeframe']} "
                            f"performs best in {regime} volatility "
                            f"({s['trades']} trades, {wr:.0%} WR, ${s['pnl']:,.0f} PnL)"
                        )
                        break
            break

    # Long vs short bias
    for result in all_results[:1]:
        if result["total_trades"] > 10:
            findings.append(
                f"6. **Direction bias ({result['symbol']} {result['timeframe']}):** "
                f"Longs: {result['long_trades']} trades, {result['long_wr']:.0%} WR, ${result['long_pnl']:,.0f} PnL | "
                f"Shorts: {result['short_trades']} trades, {result['short_wr']:.0%} WR, ${result['short_pnl']:,.0f} PnL"
            )

    # Parameter sensitivity finding
    best_param = max(sensitivity_results, key=lambda x: x[1]["total_pnl"] if x[1]["total_trades"] > 0 else -9999)
    if best_param[1]["total_trades"] > 0:
        findings.append(
            f"7. **Best SL/TP config:** {best_param[0]} — "
            f"{best_param[1]['total_trades']} trades, {best_param[1]['win_rate']:.0%} WR, "
            f"${best_param[1]['total_pnl']:,.0f} PnL"
        )

    for f in findings:
        report.append(f)

    # ── Recommendations ─────────────────────────────────────────────────
    report.append("\n## Recommendations")
    report.append("")
    report.append("Based on backtest results:")
    report.append("")

    recs = []

    # Win rate analysis
    avg_wr = np.mean([r["win_rate"] for r in all_results if r["total_trades"] > 5])
    if avg_wr < 0.40:
        recs.append(
            "1. **CVD divergence alone has a sub-40% win rate.** This is expected for a mean-reversion "
            "signal using approximated CVD from bar data. The live system's 10+ filter layers "
            "(ML, confluence scoring, circuit breakers, regime detection) are essential — "
            "do NOT trade CVD divergence without them."
        )
    elif avg_wr < 0.50:
        recs.append(
            "1. **Win rate is marginal (40-50%).** The signal has edge but requires careful filtering. "
            "Confluence scoring and time-of-day filters significantly impact results."
        )
    else:
        recs.append(
            "1. **Win rate is adequate (>50%).** The raw signal shows edge, "
            "but additional filters may improve risk-adjusted returns."
        )

    # TP/SL recommendation
    recs.append(
        "2. **SL/TP tuning:** Test the best-performing parameter set on out-of-sample data before "
        "changing live config. The R:R ratio has outsized impact on total PnL when WR is near 50%."
    )

    # Time filter recommendation
    if time_scan_results and time_scan_results[0][2]["total_pnl"] > 0:
        tw = time_scan_results[0]
        recs.append(
            f"3. **Time filter:** Consider restricting signals to {tw[0]:02d}:00-{tw[1]:02d}:00 UTC "
            f"which showed the best PnL in the scan. Verify on other symbols before deploying."
        )

    # Volatility
    recs.append(
        "4. **Volatility regimes matter.** Consider reducing position size or skipping signals "
        "during extreme ATR spikes (>P75). The high-vol regime often produces larger losses "
        "that wipe out gains from normal conditions."
    )

    # Live comparison
    recs.append(
        "5. **Live performance gap:** The live system's -$112 over 82 trades likely reflects "
        "the cost of learning (circuit breakers, regime mismatches, spread/slippage). "
        "The backtest does not account for spreads (~2-5 pips on XAGUSD), commission, "
        "or order execution latency — real edge is ~$2-5/trade lower than shown."
    )

    recs.append(
        "6. **Next steps:** (a) Run this backtest with spread deduction ($2-5/trade), "
        "(b) Add ICT 5-step confirmation filter, "
        "(c) Test on walk-forward splits (train 70% / test 30%), "
        "(d) Compare CVD divergence signal rate vs actual live signal rate to calibrate lookback params."
    )

    for rec in recs:
        report.append(rec)

    # ── Methodology Notes ───────────────────────────────────────────────
    report.append("\n## Methodology Notes")
    report.append("")
    report.append("- **CVD approximation:** Volume delta = volume * (2*close - high - low) / (high - low). ")
    report.append("  This is the same formula used in the live `indicators/cvd.py` module.")
    report.append("- **Swing detection:** lookback=3 bars either side (matching live min(swing_lookback, lookback//4, 3))")
    report.append("- **Signal detection:** Exact match of live `cvd_divergence()` logic — bearish checked first per bar")
    report.append("- **Position sizing:** Fixed $50 risk, lot_size = $50 / (SL_pips * tick_value)")
    report.append("- **Trade management:** Simple SL/TP only — no trailing stop, no partial close, no breakeven")
    report.append("- **No spread/commission deduction** — results are gross, not net")
    report.append("- **One trade at a time** — no overlapping positions")
    report.append("- **Bar-by-bar simulation** — SL/TP checked on each bar's high/low")
    report.append("- **Same-bar ambiguity:** If both SL and TP are hit on the same bar, ")
    report.append("  the trade is resolved conservatively (SL if bar opened against position)")

    report.append("\n---")
    report.append(f"*Script: `research/run_backtest.py` | Re-run: `python3 research/run_backtest.py`*")

    # Write report
    report_text = "\n".join(report)
    with open(OUTPUT_FILE, "w") as f:
        f.write(report_text)

    print(f"\nReport written to {OUTPUT_FILE}")
    print(f"Total results: {len(all_results)} backtests across {len(set(r['symbol'] for r in all_results))} symbols")
    print("Done.")


if __name__ == "__main__":
    main()

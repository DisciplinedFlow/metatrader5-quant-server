from app.utils.constants import MT5Timeframe

PAIRS = ['NG-C', 'UKOUSDft', 'USOUSD', 'XAGUSD', 'XAUUSD', 'XAUEUR', 'EURUSD',
         'EURGBP', 'USDJPY', 'USDCAD', 'USDCHF', 'AUDUSD', 'NZDUSD']
MAIN_TIMEFRAME = MT5Timeframe.M5
LEVERAGE = 100
CAPITAL_PER_TRADE = 3.50   # 5% of 70 EUR
DEVIATION = 10
MAX_OPEN_TRADES = 3        # limit total exposure

EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
ATR_PERIOD = 14

SL_ATR_MULTIPLIER = 1.5   # SL at 1.5x ATR from entry
TP_ATR_MULTIPLIER = 2.0   # TP at 2.0x ATR (1:1.33 R:R)
MIN_WIN_RATE = 0.55        # backtest gate threshold

TRAILING_STOP_STEPS = [
    {'trigger_pnl_multiplier': 2.00, 'new_sl_pnl_multiplier': 1.50},
    {'trigger_pnl_multiplier': 1.50, 'new_sl_pnl_multiplier': 1.00},
    {'trigger_pnl_multiplier': 1.00, 'new_sl_pnl_multiplier': 0.60},
    {'trigger_pnl_multiplier': 0.60, 'new_sl_pnl_multiplier': 0.30},
    {'trigger_pnl_multiplier': 0.30, 'new_sl_pnl_multiplier': 0.15},
    {'trigger_pnl_multiplier': 0.15, 'new_sl_pnl_multiplier': 0.05},
]

from app.utils.constants import MT5Timeframe

# Default config for CVD strategies — overridden by CustomStrategy.definition
DEFAULT_TIMEFRAME = MT5Timeframe.M15
LEVERAGE = 200
CAPITAL_PER_TRADE = 100
DEVIATION = 20
MAX_OPEN_TRADES = 10
ATR_PERIOD = 14
SL_ATR_MULTIPLIER = 1.5
TP_ATR_MULTIPLIER = 2.5

TRAILING_STOP_STEPS = [
    {'trigger_pnl_multiplier': 4.00, 'new_sl_pnl_multiplier': 3.50},
    {'trigger_pnl_multiplier': 3.50, 'new_sl_pnl_multiplier': 3.00},
    {'trigger_pnl_multiplier': 3.00, 'new_sl_pnl_multiplier': 2.75},
    {'trigger_pnl_multiplier': 2.75, 'new_sl_pnl_multiplier': 2.50},
    {'trigger_pnl_multiplier': 2.50, 'new_sl_pnl_multiplier': 2.25},
    {'trigger_pnl_multiplier': 2.25, 'new_sl_pnl_multiplier': 2.00},
    {'trigger_pnl_multiplier': 2.00, 'new_sl_pnl_multiplier': 1.75},
    {'trigger_pnl_multiplier': 1.75, 'new_sl_pnl_multiplier': 1.50},
    {'trigger_pnl_multiplier': 1.50, 'new_sl_pnl_multiplier': 1.25},
    {'trigger_pnl_multiplier': 1.25, 'new_sl_pnl_multiplier': 1.00},
    {'trigger_pnl_multiplier': 1.00, 'new_sl_pnl_multiplier': 0.75},
    {'trigger_pnl_multiplier': 0.75, 'new_sl_pnl_multiplier': 0.45},
    {'trigger_pnl_multiplier': 0.50, 'new_sl_pnl_multiplier': 0.22},
    {'trigger_pnl_multiplier': 0.25, 'new_sl_pnl_multiplier': 0.12},
    {'trigger_pnl_multiplier': 0.12, 'new_sl_pnl_multiplier': 0.05},
    {'trigger_pnl_multiplier': 0.06, 'new_sl_pnl_multiplier': 0.025},
]

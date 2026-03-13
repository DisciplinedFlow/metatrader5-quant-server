from app.utils.constants import MT5Timeframe

# Default config for CVD strategies — overridden by CustomStrategy.definition
DEFAULT_TIMEFRAME = MT5Timeframe.M15
LEVERAGE = 200
CAPITAL_PER_TRADE = 2000
MAX_LOT_SIZE = 1.0     # Hard safety cap — never exceed this regardless of sizing math
DEVIATION = 20
MAX_OPEN_TRADES = 5    # Reduced from 10 — less exposure with only 3 active strategies
ATR_PERIOD = 14
SL_ATR_MULTIPLIER = 1.2   # Tighter SL (was 1.5) — cut losers faster, reduce avg loss
TP_ATR_MULTIPLIER = 2.5   # Keep TP wide — let winners run to full target

# ---------------------------------------------------------------------------
# Energy-Specific Risk Configuration
# ---------------------------------------------------------------------------
# Oil and NG require different risk parameters than forex/metals:
# - Higher ATR → wider stops (2x ATR vs 1.2x for forex)
# - Lower capital per trade to compensate for larger dollar-per-pip
# - Separate position limits (WTI+Brent = 1 effective position due to 0.95 corr)
# - Session-aware: peak liquidity 13:00-17:00 UTC (London-NY overlap)
ENERGY_SYMBOLS = frozenset(['UKOUSDft', 'USOUSD', 'NG-C'])
NG_SYMBOLS = frozenset(['NG-C'])

ENERGY_RISK_CONFIG = {
    'CAPITAL_PER_TRADE': 300,         # Lower than default ($2000) — oil ATR is 3-5x forex
    'SL_ATR_MULTIPLIER': 2.0,         # Wider stops — oil needs room to breathe
    'TP_ATR_MULTIPLIER': 3.0,         # Maintain 1.5:1 minimum R:R
    'MAX_LOSS_PER_TRADE': 50,         # Hard dollar cap same as forex
    'MAX_OPEN_OIL': 2,                # Max 2 oil positions (WTI+Brent = ~1 effective)
    'MAX_OPEN_NG': 1,                 # Max 1 NG — independent but very volatile
    'DAILY_HALT_ENERGY': 150,         # Separate daily halt for energy
    # Session filter (UTC hours)
    'TRADING_START_HOUR': 8,          # London open
    'TRADING_END_HOUR': 17,           # NY close
    'BLOCKED_HOURS': [22, 23, 0],     # Dead zone — widest spreads, no sustained moves
    # Volatility regime sizing (ATR percentile thresholds)
    'CRISIS_ATR_RATIO': 2.5,          # ATR > 2.5x avg → crisis: halve size
    'HIGH_VOL_ATR_RATIO': 1.5,        # ATR > 1.5x avg → elevated: 75% size
    'CRISIS_SIZE_MULT': 0.50,
    'HIGH_VOL_SIZE_MULT': 0.75,
}

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

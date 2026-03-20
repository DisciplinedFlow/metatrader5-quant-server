import os

LIGHTER_API_URL = os.getenv('LIGHTER_API_URL', 'https://testnet.zklighter.elliot.ai')
LIGHTER_PRIVATE_KEY = os.getenv('LIGHTER_PRIVATE_KEY', '')
LIGHTER_PUBLIC_KEY = os.getenv('LIGHTER_PUBLIC_KEY', '')
LIGHTER_API_KEY_INDEX = int(os.getenv('LIGHTER_API_KEY_INDEX', '3'))
LIGHTER_ACCOUNT_INDEX = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
LIGHTER_TESTNET = os.getenv('LIGHTER_TESTNET', 'true').lower() == 'true'

# Signer proxy for Docker environments (Go native library crashes under QEMU)
LIGHTER_SIGNER_PROXY_URL = os.getenv('LIGHTER_SIGNER_PROXY_URL', 'http://host.docker.internal:5555')

# Trading parameters
LIGHTER_CAPITAL_USD = float(os.getenv('LIGHTER_CAPITAL_USD', '30'))  # Match actual equity (was $10)
# Hard global cap driven by exchange OCO limit: Lighter allows ~4 conditional orders
# per account (2 per position: SL + TP). More than 2 concurrent positions means the
# 3rd position cannot get exchange-level stops — software-only protection only.
LIGHTER_MAX_POSITIONS = int(os.getenv('LIGHTER_MAX_POSITIONS', '2'))
LIGHTER_LEVERAGE = int(os.getenv('LIGHTER_LEVERAGE', '15'))  # 3x scale-up (was 5)
LIGHTER_MAX_SLIPPAGE = float(os.getenv('LIGHTER_MAX_SLIPPAGE', '0.005'))  # 0.5%
LIGHTER_POSITION_SIZE_PCT = float(os.getenv('LIGHTER_POSITION_SIZE_PCT', '0.50'))  # 50% of capital per trade (up from 40%, justified by 65% WR / PF 2.01)

# Trading pairs (Lighter perp symbols)
# BTC removed: 50% WR, -$4.08 net PnL across 12 trades (outsized losses)
# ETH removed: 60% WR, -$8.32 net PnL across 15 trades (outsized losses)
LIGHTER_PAIRS = os.getenv('LIGHTER_PAIRS', 'SOL,AVAX,LINK,DOGE,XAU').split(',')

# Market metadata: {symbol: (market_id, min_base, size_decimals, price_decimals)}
# All markets enforce size_decimals + price_decimals = 6
# base_amount = human_amount * 10^size_decimals
# price = human_price * 10^price_decimals
LIGHTER_MARKETS = {
    # Crypto majors
    'ETH': {'id': 0, 'min_base': 0.0050, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'BTC': {'id': 1, 'min_base': 0.00020, 'size_dec': 5, 'price_dec': 1, 'min_quote': 10.0},
    'SOL': {'id': 2, 'min_base': 0.050, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    'DOGE': {'id': 3, 'min_base': 10, 'size_dec': 0, 'price_dec': 6, 'min_quote': 10.0},
    'XRP': {'id': 7, 'min_base': 20, 'size_dec': 0, 'price_dec': 6, 'min_quote': 10.0},
    'LINK': {'id': 8, 'min_base': 1.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'AVAX': {'id': 9, 'min_base': 0.50, 'size_dec': 2, 'price_dec': 4, 'min_quote': 10.0},
    'NEAR': {'id': 10, 'min_base': 2.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'DOT': {'id': 11, 'min_base': 2.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'TON': {'id': 12, 'min_base': 2.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'SUI': {'id': 16, 'min_base': 3.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'HYPE': {'id': 24, 'min_base': 0.50, 'size_dec': 2, 'price_dec': 4, 'min_quote': 10.0},
    'BNB': {'id': 25, 'min_base': 0.02, 'size_dec': 2, 'price_dec': 4, 'min_quote': 10.0},
    'AAVE': {'id': 27, 'min_base': 0.050, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    'ADA': {'id': 39, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'ARB': {'id': 50, 'min_base': 20.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'OP': {'id': 55, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    # Forex pairs
    'EURUSD': {'id': 96, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'GBPUSD': {'id': 97, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'USDJPY': {'id': 98, 'min_base': 0.050, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    'USDCHF': {'id': 99, 'min_base': 8.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'USDCAD': {'id': 100, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'AUDUSD': {'id': 106, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    'NZDUSD': {'id': 107, 'min_base': 10.0, 'size_dec': 1, 'price_dec': 5, 'min_quote': 10.0},
    # Metals & commodities
    'XAU': {'id': 92, 'min_base': 0.0030, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'XAG': {'id': 93, 'min_base': 0.15, 'size_dec': 2, 'price_dec': 4, 'min_quote': 10.0},
    'PAXG': {'id': 48, 'min_base': 0.0025, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'WTI': {'id': 145, 'min_base': 0.100, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    # US Stocks
    'TSLA': {'id': 112, 'min_base': 0.0200, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'NVDA': {'id': 110, 'min_base': 0.050, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    'AAPL': {'id': 113, 'min_base': 0.050, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    'AMZN': {'id': 114, 'min_base': 0.050, 'size_dec': 3, 'price_dec': 3, 'min_quote': 10.0},
    'MSFT': {'id': 115, 'min_base': 0.0200, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'GOOGL': {'id': 116, 'min_base': 0.0300, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'META': {'id': 117, 'min_base': 0.0200, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    # ETFs
    'SPY': {'id': 128, 'min_base': 0.0100, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
    'QQQ': {'id': 129, 'min_base': 0.0100, 'size_dec': 4, 'price_dec': 2, 'min_quote': 10.0},
}


def get_market_id(symbol: str) -> int:
    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        raise ValueError(f"Unknown Lighter symbol: {symbol}. Available: {list(LIGHTER_MARKETS.keys())}")
    return meta['id']


def human_to_sdk_amount(symbol: str, human_amount: float) -> int:
    """Convert human-readable base amount to SDK integer format."""
    meta = LIGHTER_MARKETS[symbol]
    return int(round(human_amount * (10 ** meta['size_dec'])))


def human_to_sdk_price(symbol: str, human_price: float) -> int:
    """Convert human-readable price to SDK integer format."""
    meta = LIGHTER_MARKETS[symbol]
    return int(round(human_price * (10 ** meta['price_dec'])))


def sdk_to_human_amount(symbol: str, sdk_amount: int) -> float:
    """Convert SDK integer amount back to human-readable."""
    meta = LIGHTER_MARKETS[symbol]
    return sdk_amount / (10 ** meta['size_dec'])


def sdk_to_human_price(symbol: str, sdk_price: int) -> float:
    """Convert SDK integer price back to human-readable."""
    meta = LIGHTER_MARKETS[symbol]
    return sdk_price / (10 ** meta['price_dec'])


def is_global_position_limit_reached() -> bool:
    """Return True if the global Lighter position cap is reached across ALL strategies.

    Checks CryptoPosition directly so every strategy (CVD, MOM, RSI2, grid) shares
    the same hard limit. Capped at LIGHTER_MAX_POSITIONS=2 to match the exchange's
    ~4 conditional order limit (2 positions × SL+TP each).
    """
    try:
        from app.crypto.models import CryptoPosition
        open_count = CryptoPosition.objects.filter(status='OPEN').count()
        return open_count >= LIGHTER_MAX_POSITIONS
    except Exception:
        return False  # fail-open so a DB hiccup doesn't freeze the bot

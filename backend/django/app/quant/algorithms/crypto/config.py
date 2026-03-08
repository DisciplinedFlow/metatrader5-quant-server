import os

# Hyperliquid credentials
HYPERLIQUID_PRIVATE_KEY = os.getenv('HYPERLIQUID_PRIVATE_KEY', '')
HYPERLIQUID_WALLET_ADDRESS = os.getenv('HYPERLIQUID_WALLET_ADDRESS', '')
HYPERLIQUID_TESTNET = os.getenv('HYPERLIQUID_TESTNET', 'true').lower() == 'true'
# Agent wallet: trade-only delegate key (cannot withdraw). Set to use instead of master key.
HYPERLIQUID_AGENT_KEY = os.getenv('HYPERLIQUID_AGENT_KEY', '')

# Trading parameters
CRYPTO_PAIRS = os.getenv('CRYPTO_PAIRS', 'BTC,ETH,SOL,ARB').split(',')
CRYPTO_CAPITAL_USD = float(os.getenv('CRYPTO_CAPITAL_USD', '1000'))
CRYPTO_MAX_POSITIONS = int(os.getenv('CRYPTO_MAX_POSITIONS', '3'))
CRYPTO_LEVERAGE = int(os.getenv('CRYPTO_LEVERAGE', '1'))

# Strategy parameters
CRYPTO_STRATEGY = os.getenv('CRYPTO_STRATEGY', 'momentum')
CRYPTO_FAST_MA = int(os.getenv('CRYPTO_FAST_MA', '50'))
CRYPTO_SLOW_MA = int(os.getenv('CRYPTO_SLOW_MA', '200'))
CRYPTO_LOOKBACK = int(os.getenv('CRYPTO_LOOKBACK', '252'))
CRYPTO_MAX_POSITION_PCT = float(os.getenv('CRYPTO_MAX_POSITION_PCT', '0.10'))

# Risk parameters
CRYPTO_STOP_LOSS_PCT = float(os.getenv('CRYPTO_STOP_LOSS_PCT', '0.05'))
CRYPTO_TAKE_PROFIT_PCT = float(os.getenv('CRYPTO_TAKE_PROFIT_PCT', '0.10'))

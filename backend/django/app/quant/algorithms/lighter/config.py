import os

LIGHTER_API_URL = os.getenv('LIGHTER_API_URL', 'https://testnet.zklighter.elliot.ai')
LIGHTER_PRIVATE_KEY = os.getenv('LIGHTER_PRIVATE_KEY', '')
LIGHTER_API_KEY_INDEX = int(os.getenv('LIGHTER_API_KEY_INDEX', '3'))
LIGHTER_ACCOUNT_INDEX = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
LIGHTER_TESTNET = os.getenv('LIGHTER_TESTNET', 'true').lower() == 'true'

# Market indices on Lighter
LIGHTER_MARKETS = {
    'ETH': 0,
    'BTC': 1,
    'SOL': 2,
    'ARB': 3,
}

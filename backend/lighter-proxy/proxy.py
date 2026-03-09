#!/usr/bin/env python3
"""
Lighter.xyz Signer Proxy — runs NATIVELY on macOS.

The Lighter SDK's SignerClient uses a Go native library that crashes under
QEMU emulation in Docker on arm64 Mac. This proxy exposes the SignerClient
as HTTP endpoints so Django/Celery in Docker can trade.

Usage:
    cd backend/lighter-proxy
    pip install lighter-sdk flask python-dotenv
    python proxy.py

Reads config from ../../.env (project root).
"""
import os
import sys
import asyncio
import logging
from pathlib import Path
from flask import Flask, request, jsonify

# Load .env from project root
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(env_path)

import lighter

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('lighter-proxy')

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────

API_URL = os.getenv('LIGHTER_API_URL', 'https://mainnet.zklighter.elliot.ai')
PRIVATE_KEY = os.getenv('LIGHTER_PRIVATE_KEY', '')
API_KEY_INDEX = int(os.getenv('LIGHTER_API_KEY_INDEX', '2'))
ACCOUNT_INDEX = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '718566'))
PORT = int(os.getenv('LIGHTER_PROXY_PORT', '5555'))

# Market metadata (size_dec + price_dec = 6 for all markets)
MARKETS = {
    'ETH': {'id': 0, 'size_dec': 4, 'price_dec': 2},
    'BTC': {'id': 1, 'size_dec': 5, 'price_dec': 1},
    'SOL': {'id': 2, 'size_dec': 3, 'price_dec': 3},
    'DOGE': {'id': 3, 'size_dec': 0, 'price_dec': 6},
    'XRP': {'id': 7, 'size_dec': 0, 'price_dec': 6},
    'LINK': {'id': 8, 'size_dec': 1, 'price_dec': 5},
    'AVAX': {'id': 9, 'size_dec': 2, 'price_dec': 4},
    'NEAR': {'id': 10, 'size_dec': 1, 'price_dec': 5},
    'DOT': {'id': 11, 'size_dec': 1, 'price_dec': 5},
    'TON': {'id': 12, 'size_dec': 1, 'price_dec': 5},
    'SUI': {'id': 16, 'size_dec': 1, 'price_dec': 5},
    'HYPE': {'id': 24, 'size_dec': 2, 'price_dec': 4},
    'BNB': {'id': 25, 'size_dec': 2, 'price_dec': 4},
    'AAVE': {'id': 27, 'size_dec': 3, 'price_dec': 3},
    'ADA': {'id': 39, 'size_dec': 1, 'price_dec': 5},
    'ARB': {'id': 50, 'size_dec': 1, 'price_dec': 5},
    'OP': {'id': 55, 'size_dec': 1, 'price_dec': 5},
    'EURUSD': {'id': 96, 'size_dec': 1, 'price_dec': 5},
    'GBPUSD': {'id': 97, 'size_dec': 1, 'price_dec': 5},
    'USDJPY': {'id': 98, 'size_dec': 3, 'price_dec': 3},
    'USDCHF': {'id': 99, 'size_dec': 1, 'price_dec': 5},
    'USDCAD': {'id': 100, 'size_dec': 1, 'price_dec': 5},
    'AUDUSD': {'id': 106, 'size_dec': 1, 'price_dec': 5},
    'NZDUSD': {'id': 107, 'size_dec': 1, 'price_dec': 5},
    'XAU': {'id': 92, 'size_dec': 4, 'price_dec': 2},
    'XAG': {'id': 93, 'size_dec': 2, 'price_dec': 4},
    'PAXG': {'id': 48, 'size_dec': 4, 'price_dec': 2},
    'WTI': {'id': 145, 'size_dec': 3, 'price_dec': 3},
    'TSLA': {'id': 112, 'size_dec': 4, 'price_dec': 2},
    'NVDA': {'id': 110, 'size_dec': 3, 'price_dec': 3},
    'AAPL': {'id': 113, 'size_dec': 3, 'price_dec': 3},
    'AMZN': {'id': 114, 'size_dec': 3, 'price_dec': 3},
    'MSFT': {'id': 115, 'size_dec': 4, 'price_dec': 2},
    'GOOGL': {'id': 116, 'size_dec': 4, 'price_dec': 2},
    'META': {'id': 117, 'size_dec': 4, 'price_dec': 2},
    'SPY': {'id': 128, 'size_dec': 4, 'price_dec': 2},
    'QQQ': {'id': 129, 'size_dec': 4, 'price_dec': 2},
}


def _run(coro):
    """Run async coroutine from sync Flask context."""
    return asyncio.run(coro)


# ── Signer Client (created inside event loop) ────────────

async def _create_signer():
    """Create and validate SignerClient (must be called inside event loop)."""
    if not PRIVATE_KEY:
        raise ValueError("LIGHTER_PRIVATE_KEY not set")
    signer = lighter.SignerClient(
        url=API_URL,
        api_private_keys={API_KEY_INDEX: PRIVATE_KEY},
        account_index=ACCOUNT_INDEX,
    )
    err = signer.check_client()
    if err is not None:
        raise ConnectionError(f"SignerClient check failed: {err}")
    return signer


async def _create_account_api():
    """Create account API client (must be called inside event loop)."""
    api = lighter.ApiClient(configuration=lighter.Configuration(host=API_URL))
    return lighter.AccountApi(api), api


# ── Endpoints ─────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    try:
        async def _check():
            signer = await _create_signer()
            await signer.close()
            return True
        _run(_check())
        return jsonify({'status': 'ok', 'account': ACCOUNT_INDEX})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/order/market', methods=['POST'])
def market_order():
    """Place a market order by USD amount."""
    data = request.json
    symbol = data['symbol']
    is_buy = data['is_buy']
    quote_amount_usd = float(data['quote_amount_usd'])
    max_slippage = float(data.get('max_slippage', 0.005))

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                tx, resp, err = await signer.create_market_order_quote_amount(
                    market_index=meta['id'],
                    client_order_index=0,
                    quote_amount=quote_amount_usd,
                    max_slippage=max_slippage,
                    is_ask=not is_buy,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {
                    'tx_hash': tx_hash,
                    'symbol': symbol,
                    'side': 'BUY' if is_buy else 'SELL',
                    'quote_amount': quote_amount_usd,
                }
            finally:
                await signer.close()

        result = _run(_execute())
        logger.info("Market order: %s %s $%.2f -> %s",
                     symbol, 'BUY' if is_buy else 'SELL', quote_amount_usd,
                     result.get('error') or result.get('tx_hash'))
        status_code = 500 if result.get('error') else 200
        return jsonify(result), status_code
    except Exception as e:
        logger.error("Market order error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/order/limit', methods=['POST'])
def limit_order():
    """Place a limit order."""
    data = request.json
    symbol = data['symbol']
    is_buy = data['is_buy']
    base_amount = float(data['base_amount'])
    price = float(data['price'])

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))
    sdk_price = int(round(price * (10 ** meta['price_dec'])))

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                tx, resp, err = await signer.create_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_price,
                    is_ask=not is_buy,
                    order_type=signer.ORDER_TYPE_LIMIT,
                    time_in_force=signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {'tx_hash': tx_hash, 'symbol': symbol}
            finally:
                await signer.close()

        result = _run(_execute())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/order/stop-loss', methods=['POST'])
def stop_loss_order():
    """Place a stop-loss order."""
    data = request.json
    symbol = data['symbol']
    is_buy = data['is_buy']
    base_amount = float(data['base_amount'])
    trigger_price = float(data['trigger_price'])

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))
    sdk_trigger = int(round(trigger_price * (10 ** meta['price_dec'])))
    slippage = 0.02
    if is_buy:
        sdk_price = int(round(trigger_price * (1 + slippage) * (10 ** meta['price_dec'])))
    else:
        sdk_price = int(round(trigger_price * (1 - slippage) * (10 ** meta['price_dec'])))

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                tx, resp, err = await signer.create_sl_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_price,
                    is_ask=not is_buy,
                    trigger_price=sdk_trigger,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {'tx_hash': tx_hash, 'symbol': symbol, 'type': 'stop_loss'}
            finally:
                await signer.close()

        result = _run(_execute())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/order/take-profit', methods=['POST'])
def take_profit_order():
    """Place a take-profit order."""
    data = request.json
    symbol = data['symbol']
    is_buy = data['is_buy']
    base_amount = float(data['base_amount'])
    trigger_price = float(data['trigger_price'])

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))
    sdk_trigger = int(round(trigger_price * (10 ** meta['price_dec'])))
    sdk_price = sdk_trigger

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                tx, resp, err = await signer.create_tp_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_price,
                    is_ask=not is_buy,
                    trigger_price=sdk_trigger,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {'tx_hash': tx_hash, 'symbol': symbol, 'type': 'take_profit'}
            finally:
                await signer.close()

        result = _run(_execute())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/position/close', methods=['POST'])
def close_position():
    """Close entire position for a symbol by placing a reduce-only market order."""
    data = request.json
    symbol = data['symbol']

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    try:
        async def _execute():
            signer = await _create_signer()
            account_api, api_client = await _create_account_api()
            try:
                account = await account_api.account(by="index", value=str(ACCOUNT_INDEX))

                # Account data is nested: account.accounts[0].positions
                position = None
                acct = account.accounts[0] if hasattr(account, 'accounts') and account.accounts else None
                if acct and hasattr(acct, 'positions') and acct.positions:
                    for pos in acct.positions:
                        if hasattr(pos, 'market_id') and int(pos.market_id) == meta['id']:
                            pos_size = float(pos.position) if hasattr(pos, 'position') else 0
                            if pos_size != 0:
                                position = pos
                                break

                if position is None:
                    return {'error': f'No open position for {symbol}'}

                pos_size = float(position.position)
                is_ask = pos_size > 0  # positive = long, sell to close
                abs_size = abs(pos_size)
                sdk_amount = int(round(abs_size * (10 ** meta['size_dec'])))

                ideal_price = await signer.get_best_price(meta['id'], is_ask)
                slippage_factor = 0.995 if is_ask else 1.005
                execution_price = round(ideal_price * slippage_factor)

                tx, resp, err = await signer.create_market_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    avg_execution_price=execution_price,
                    is_ask=is_ask,
                    reduce_only=True,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {'tx_hash': tx_hash, 'symbol': symbol, 'closed_size': abs_size}
            finally:
                await signer.close()
                await api_client.close()

        result = _run(_execute())
        logger.info("Close position: %s -> %s", symbol, result.get('error') or result.get('tx_hash'))
        return jsonify(result)
    except Exception as e:
        logger.error("Close position error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/leverage', methods=['POST'])
def set_leverage():
    """Update leverage for a market."""
    data = request.json
    symbol = data['symbol']
    leverage = int(data['leverage'])
    cross = data.get('cross', True)

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                margin_mode = signer.CROSS_MARGIN_MODE if cross else signer.ISOLATED_MARGIN_MODE
                tx, resp, err = await signer.update_leverage(
                    market_index=meta['id'],
                    leverage=leverage,
                    margin_mode=margin_mode,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {'tx_hash': tx_hash, 'symbol': symbol, 'leverage': leverage}
            finally:
                await signer.close()

        result = _run(_execute())
        logger.info("Leverage update: %s %dx -> %s", symbol, leverage, result.get('error') or 'OK')
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/orders/cancel-all', methods=['POST'])
def cancel_all():
    """Cancel all open orders."""
    data = request.json or {}
    symbol = data.get('symbol')

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                market_index = 0
                if symbol:
                    meta = MARKETS.get(symbol)
                    if not meta:
                        return {'error': f'Unknown symbol: {symbol}'}
                    market_index = meta['id']
                tx, resp, err = await signer.cancel_all_orders(
                    market_index=market_index,
                    tif=signer.CANCEL_ALL_TIF_IMMEDIATE,
                )
                if err:
                    return {'error': err}
                return {'status': 'ok'}
            finally:
                await signer.close()

        result = _run(_execute())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    logger.info("Starting Lighter Signer Proxy on port %d...", PORT)
    logger.info("API URL: %s", API_URL)
    logger.info("Account: %s, Key Index: %s", ACCOUNT_INDEX, API_KEY_INDEX)

    # Validate signer on startup
    try:
        async def _validate():
            signer = await _create_signer()
            await signer.close()
        asyncio.run(_validate())
        logger.info("SignerClient validated successfully!")
    except Exception as e:
        logger.error("Failed to initialize SignerClient: %s", e)
        sys.exit(1)

    app.run(host='0.0.0.0', port=PORT, debug=False)

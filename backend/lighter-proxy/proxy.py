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
import json
import os
import sys
import asyncio
import logging
import time as _time
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

# ── Trading active flag & uptime ─────────────────────────
_active = True          # When False, all trading endpoints return 503
_start_time = _time.time()

# ── CORS — allow dashboard (any localhost origin) ────────
_CONTROL_ROUTES = frozenset(['/health', '/status', '/toggle', '/trades'])

@app.after_request
def _cors(response):
    origin = request.headers.get('Origin', '')
    if 'localhost' in origin or '127.0.0.1' in origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.before_request
def _guard_trading():
    """Block trading endpoints when proxy is in standby mode."""
    if request.method == 'OPTIONS':
        return  # CORS preflight always OK
    if request.path in _CONTROL_ROUTES:
        return  # Control endpoints always available
    if not _active:
        return jsonify({
            'error': 'Lighter proxy is in STANDBY mode — trading disabled',
            'active': False,
        }), 503

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


@app.route('/status', methods=['GET'])
def status():
    """Lightweight status check — no signer validation, just process state."""
    return jsonify({
        'active': _active,
        'uptime_s': int(_time.time() - _start_time),
        'account': ACCOUNT_INDEX,
        'port': PORT,
        'markets': len(MARKETS),
        'oco_pairs': len(_oco_pairs),
    })


@app.route('/toggle', methods=['POST', 'OPTIONS'])
def toggle():
    """Set or flip the active flag. When inactive, all trading endpoints return 503.

    POST with {"active": true/false} to set explicitly, or POST with no body to flip.
    """
    if request.method == 'OPTIONS':
        return '', 204
    global _active
    data = request.get_json(silent=True) or {}
    if 'active' in data:
        _active = bool(data['active'])
    else:
        _active = not _active
    state = 'ACTIVE' if _active else 'STANDBY'
    logger.info("Trading toggled → %s", state)
    return jsonify({'active': _active, 'state': state})


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
    """Place a limit order. Supports post_only flag for maker-only orders."""
    data = request.json
    symbol = data['symbol']
    is_buy = data['is_buy']
    base_amount = float(data['base_amount'])
    price = float(data['price'])
    post_only = data.get('post_only', False)

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))
    sdk_price = int(round(price * (10 ** meta['price_dec'])))

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                tif = signer.ORDER_TIME_IN_FORCE_POST_ONLY if post_only else signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME
                tx, resp, err = await signer.create_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_price,
                    is_ask=not is_buy,
                    order_type=signer.ORDER_TYPE_LIMIT,
                    time_in_force=tif,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {'tx_hash': tx_hash, 'symbol': symbol, 'post_only': post_only}
            finally:
                await signer.close()

        result = _run(_execute())
        logger.info("Limit order: %s %s %.6f @ %.4f %s-> %s",
                     symbol, 'BUY' if is_buy else 'SELL', base_amount, price,
                     '(post-only) ' if post_only else '',
                     result.get('error') or result.get('tx_hash'))
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/order/twap', methods=['POST'])
def twap_order():
    """Place a TWAP order that executes over a duration.

    Uses ORDER_TYPE_TWAP with create_order. The SDK treats TWAP as an order type
    where the exchange slices execution over time. The base_amount is calculated
    from quote_amount_usd using the current mid price.
    """
    data = request.json
    symbol = data['symbol']
    is_buy = data['is_buy']
    quote_amount_usd = float(data['quote_amount_usd'])
    duration_seconds = int(data.get('duration_seconds', 300))  # default 5 min

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                # Get current best price to estimate base amount from USD
                best_price = await signer.get_best_price(meta['id'], not is_buy)
                if not best_price or best_price <= 0:
                    return {'error': f'Cannot get price for {symbol}'}

                # Convert quote amount (USD) to base amount
                price_float = best_price / (10 ** meta['price_dec'])
                base_amount = quote_amount_usd / price_float
                sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))
                sdk_price = best_price  # already in SDK units

                tx, resp, err = await signer.create_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_price,
                    is_ask=not is_buy,
                    order_type=signer.ORDER_TYPE_TWAP,
                    time_in_force=signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    order_expiry=duration_seconds,
                )
                if err:
                    return {'error': err}
                tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                return {
                    'tx_hash': tx_hash,
                    'symbol': symbol,
                    'type': 'twap',
                    'duration': duration_seconds,
                    'estimated_base': base_amount,
                }
            finally:
                await signer.close()

        result = _run(_execute())
        logger.info("TWAP order: %s %s $%.2f over %ds -> %s",
                     symbol, 'BUY' if is_buy else 'SELL', quote_amount_usd,
                     duration_seconds, result.get('error') or result.get('tx_hash'))
        status_code = 500 if result.get('error') else 200
        return jsonify(result), status_code
    except Exception as e:
        logger.error("TWAP order error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/order/batch', methods=['POST'])
def batch_orders():
    """Place multiple limit orders in a single request.

    Each order is submitted individually via create_order. For atomic grouped
    orders (OCO, OTO), use the /order/grouped endpoint instead.
    """
    data = request.json
    orders = data.get('orders', [])

    if not orders:
        return jsonify({'error': 'No orders provided'}), 400

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                results = []
                for order in orders:
                    symbol = order['symbol']
                    meta = MARKETS.get(symbol)
                    if not meta:
                        results.append({'error': f'Unknown symbol: {symbol}'})
                        continue

                    is_buy = order['is_buy']
                    base_amount = float(order['base_amount'])
                    price = float(order['price'])
                    post_only = order.get('post_only', False)

                    sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))
                    sdk_price = int(round(price * (10 ** meta['price_dec'])))

                    tif = signer.ORDER_TIME_IN_FORCE_POST_ONLY if post_only else signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME

                    tx, resp, err = await signer.create_order(
                        market_index=meta['id'],
                        client_order_index=0,
                        base_amount=sdk_amount,
                        price=sdk_price,
                        is_ask=not is_buy,
                        order_type=signer.ORDER_TYPE_LIMIT,
                        time_in_force=tif,
                    )
                    if err:
                        results.append({'error': err, 'symbol': symbol})
                    else:
                        tx_hash = resp.tx_hash if hasattr(resp, 'tx_hash') else str(resp)
                        results.append({'tx_hash': tx_hash, 'symbol': symbol})

                return {'results': results, 'total': len(results)}
            finally:
                await signer.close()

        result = _run(_execute())
        logger.info("Batch orders: %d submitted", len(orders))
        return jsonify(result)
    except Exception as e:
        logger.error("Batch order error: %s", e)
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


@app.route('/order/oco-sltp', methods=['POST'])
def oco_sltp_order():
    """Place SL + TP as a "poor man's OCO".

    The native create_grouped_orders OCO returns "ReduceOnly is invalid" on
    Lighter.xyz. Workaround: place individual SL and TP orders (which both
    work), store their tx hashes in a Redis-backed in-memory registry, and
    let the cleanup task cancel the orphaned counterpart when one fills.
    """
    data = request.json
    symbol = data['symbol']
    is_long = data['is_long']
    base_amount = float(data['base_amount'])
    stop_loss_price = float(data['stop_loss_price'])
    take_profit_price = float(data['take_profit_price'])

    meta = MARKETS.get(symbol)
    if not meta:
        return jsonify({'error': f'Unknown symbol: {symbol}'}), 400

    sdk_amount = int(round(base_amount * (10 ** meta['size_dec'])))

    # SL/TP exit direction: if long, exit is sell (is_ask=True); if short, exit is buy (is_ask=False)
    is_ask = is_long

    # Stop-loss price with slippage
    sdk_sl_trigger = int(round(stop_loss_price * (10 ** meta['price_dec'])))
    slippage = 0.02
    if is_ask:
        sdk_sl_price = int(round(stop_loss_price * (1 - slippage) * (10 ** meta['price_dec'])))
    else:
        sdk_sl_price = int(round(stop_loss_price * (1 + slippage) * (10 ** meta['price_dec'])))

    # Take-profit price
    sdk_tp_trigger = int(round(take_profit_price * (10 ** meta['price_dec'])))
    sdk_tp_price = sdk_tp_trigger

    try:
        async def _execute():
            signer = await _create_signer()
            try:
                # Place SL order individually (this works)
                _, sl_resp, sl_err = await signer.create_sl_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_sl_price,
                    is_ask=is_ask,
                    trigger_price=sdk_sl_trigger,
                )
                if sl_err:
                    return {'error': f'SL failed: {sl_err}'}
                sl_tx = sl_resp.tx_hash if hasattr(sl_resp, 'tx_hash') else str(sl_resp)

                # Place TP order individually (this works)
                _, tp_resp, tp_err = await signer.create_tp_order(
                    market_index=meta['id'],
                    client_order_index=0,
                    base_amount=sdk_amount,
                    price=sdk_tp_price,
                    is_ask=is_ask,
                    trigger_price=sdk_tp_trigger,
                )
                if tp_err:
                    return {'error': f'TP failed (SL placed as {sl_tx}): {tp_err}'}
                tp_tx = tp_resp.tx_hash if hasattr(tp_resp, 'tx_hash') else str(tp_resp)

                # Register the OCO pair for cleanup tracking
                _register_oco_pair(symbol, sl_tx, tp_tx)

                return {
                    'tx_hash': f'{sl_tx},{tp_tx}',
                    'sl_tx_hash': sl_tx,
                    'tp_tx_hash': tp_tx,
                    'symbol': symbol,
                    'type': 'oco_sltp',
                    'stop_loss': stop_loss_price,
                    'take_profit': take_profit_price,
                }
            finally:
                await signer.close()

        result = _run(_execute())
        logger.info("OCO SL/TP (poor-man): %s %s SL=%.4f TP=%.4f -> %s",
                     symbol, 'LONG' if is_long else 'SHORT',
                     stop_loss_price, take_profit_price,
                     result.get('error') or result.get('tx_hash'))
        status_code = 500 if result.get('error') else 200
        return jsonify(result), status_code
    except Exception as e:
        logger.error("OCO SL/TP error: %s", e)
        return jsonify({'error': str(e)}), 500


# ── Poor-man's OCO tracking ─────────────────────────────

# In-memory OCO registry: list of {symbol, sl_tx, tp_tx, created_at}
# Persisted to a JSON file so it survives proxy restarts.
_OCO_FILE = Path(__file__).resolve().parent / '.oco_pairs.json'
_oco_pairs = []


def _load_oco_pairs():
    global _oco_pairs
    try:
        if _OCO_FILE.exists():
            _oco_pairs = json.loads(_OCO_FILE.read_text())
    except Exception:
        _oco_pairs = []


def _save_oco_pairs():
    try:
        _OCO_FILE.write_text(json.dumps(_oco_pairs, indent=2))
    except Exception as e:
        logger.warning("Failed to save OCO pairs file: %s", e)


def _register_oco_pair(symbol, sl_tx, tp_tx):
    """Register a pair of SL/TP orders for cleanup tracking."""
    _oco_pairs.append({
        'symbol': symbol,
        'sl_tx': sl_tx,
        'tp_tx': tp_tx,
        'created_at': _time.time(),
    })
    _save_oco_pairs()
    logger.info("OCO pair registered: %s SL=%s TP=%s", symbol, sl_tx, tp_tx)


@app.route('/oco/pairs', methods=['GET'])
def get_oco_pairs():
    """Return active OCO pairs for monitoring."""
    return jsonify({'pairs': _oco_pairs})


@app.route('/oco/remove', methods=['POST'])
def remove_oco_pair():
    """Remove an OCO pair after cleanup (called by Django reconcile)."""
    data = request.json
    symbol = data.get('symbol')
    global _oco_pairs
    _oco_pairs = [p for p in _oco_pairs if p['symbol'] != symbol]
    _save_oco_pairs()
    return jsonify({'status': 'ok'})


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

                # position.position is ALWAYS positive (absolute size string).
                # Direction lives in position.sign: 1=LONG, -1=SHORT.
                abs_size = float(position.position)
                sign = int(position.sign) if hasattr(position, 'sign') and position.sign is not None else 1
                is_ask = sign > 0  # long (sign=1) -> sell to close; short (sign=-1) -> buy to close
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
    """Cancel all open orders.

    Sends two cancel-all transactions:
    1. CANCEL_ALL_TIF_ABORT  — cancels regular limit orders in the order book.
    2. CANCEL_ALL_TIF_IMMEDIATE — cancels pending conditional orders (SL/TP type)
       that don't appear in account_active_orders but consume the pending quota.
    """
    try:
        async def _execute():
            signer = await _create_signer()
            try:
                from lighter import SignerClient as _SC
                errors = []

                # Cancel regular limit orders
                _, _, err = await signer.cancel_all_orders(
                    time_in_force=_SC.CANCEL_ALL_TIF_ABORT,
                    timestamp_ms=0,
                )
                if err:
                    errors.append(f'ABORT: {err}')

                # Cancel conditional orders (SL/TP pending queue)
                _, _, err2 = await signer.cancel_all_orders(
                    time_in_force=_SC.CANCEL_ALL_TIF_IMMEDIATE,
                    timestamp_ms=0,
                )
                if err2:
                    errors.append(f'IMMEDIATE: {err2}')

                if errors:
                    return {'status': 'partial', 'errors': errors}
                return {'status': 'ok'}
            finally:
                await signer.close()

        result = _run(_execute())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/trades', methods=['GET'])
def account_trades():
    """Fetch authenticated trade history for this account."""
    limit = request.args.get('limit', 100, type=int)
    try:
        async def _fetch():
            signer = await _create_signer()
            try:
                auth_token = signer.create_auth_token_with_expiry(
                    signer.DEFAULT_10_MIN_AUTH_EXPIRY,
                )
                api = lighter.ApiClient(configuration=lighter.Configuration(host=API_URL))
                try:
                    order_api = lighter.OrderApi(api)
                    resp = await order_api.trades_without_preload_content(
                        sort_by='timestamp',
                        sort_dir='desc',
                        limit=limit,
                        account_index=ACCOUNT_INDEX,
                        authorization=auth_token,
                    )
                    body = await resp.read()
                    return json.loads(body.decode())
                finally:
                    await api.close()
            finally:
                await signer.close()

        data = _run(_fetch())
        return jsonify(data)
    except Exception as e:
        logger.error("Trade history error: %s", e)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    _load_oco_pairs()
    logger.info("Starting Lighter Signer Proxy on port %d...", PORT)
    logger.info("API URL: %s", API_URL)
    logger.info("Account: %s, Key Index: %s", ACCOUNT_INDEX, API_KEY_INDEX)
    logger.info("OCO pairs loaded: %d active", len(_oco_pairs))

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

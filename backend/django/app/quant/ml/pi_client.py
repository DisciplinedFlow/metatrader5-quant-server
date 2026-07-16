"""Raspberry Pi NPU Inference Client.

Connects to Pi 5 (16GB + Hailo-10H 40 TOPS) running Flask inference server.
Provides: FinBERT sentiment, XGBoost prediction, Ollama report generation.
Falls back to local processing if Pi is unreachable.
"""
import os
import json
import time
import logging
import requests
from django.core.cache import cache

logger = logging.getLogger('quant')

PI_URL = os.getenv('PI_NPU_URL', 'http://raspberrypi:8100')
PI_ENABLED = os.getenv('PI_NPU_ENABLED', 'true').lower() == 'true'
PI_TIMEOUT = float(os.getenv('PI_NPU_TIMEOUT', '3'))
PI_SENTIMENT_TIMEOUT = float(os.getenv('PI_NPU_SENTIMENT_TIMEOUT', '10'))
PI_REPORT_TIMEOUT = float(os.getenv('PI_NPU_REPORT_TIMEOUT', '120'))
SENTIMENT_CACHE_TTL = int(os.getenv('PI_NPU_SENTIMENT_TTL', '300'))

# Circuit breaker: 5 failures → 2 min cooldown
_failure_count = 0
_circuit_open_until = 0
_MAX_FAILURES = 5
_COOLDOWN_SECONDS = 120


def _is_available():
    global _failure_count, _circuit_open_until
    if not PI_ENABLED:
        return False
    if _circuit_open_until > time.time():
        return False
    return True


def _record_failure():
    global _failure_count, _circuit_open_until
    _failure_count += 1
    if _failure_count >= _MAX_FAILURES:
        _circuit_open_until = time.time() + _COOLDOWN_SECONDS
        logger.warning(f'Pi circuit breaker OPEN — {_MAX_FAILURES} failures, cooling down {_COOLDOWN_SECONDS}s')
        _failure_count = 0


def _record_success():
    global _failure_count, _circuit_open_until
    _failure_count = 0
    _circuit_open_until = 0


def health_check() -> dict:
    """Check Pi inference server health."""
    try:
        resp = requests.get(f'{PI_URL}/health', timeout=PI_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        data['pi_reachable'] = True
        _record_success()
        return data
    except Exception as e:
        _record_failure()
        return {'pi_reachable': False, 'error': str(e)}


def get_sentiment(headlines: list) -> dict:
    """Get FinBERT sentiment from Pi.

    Returns same format as news_sentiment.get_market_risk_level()
    so it's a drop-in replacement.
    """
    cache_key = f'pi:sentiment:{hash(str(headlines[:5]))}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    if not _is_available() or not headlines:
        return None  # Caller falls back to keyword matching

    try:
        resp = requests.post(
            f'{PI_URL}/sentiment',
            json={'texts': headlines[:20]},
            timeout=PI_SENTIMENT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        _record_success()

        # Map to the format news_sentiment expects
        result = {
            'risk_level': data.get('risk_level', 'NORMAL'),
            'size_multiplier': data.get('size_multiplier', 1.0),
            'reason': f"FinBERT NLP: {data.get('negative_ratio', 0):.0%} negative ({data.get('latency_ms', 0):.0f}ms)",
            'headlines_checked': len(headlines),
            'matched_keywords': [r['text'] for r in data.get('results', []) if r.get('label') == 'negative'],
            'source': 'PI_FINBERT',
        }
        cache.set(cache_key, result, timeout=SENTIMENT_CACHE_TTL)
        logger.info(f'Pi sentiment: {result["risk_level"]} ({data.get("latency_ms", 0):.0f}ms)')
        return result
    except Exception as e:
        _record_failure()
        logger.debug(f'Pi sentiment failed: {e}')
        return None


def predict_trade(features: list) -> dict:
    """Get XGBoost win probability from Pi.

    Returns: {'win_probability': 0.65} or None if unavailable.
    """
    if not _is_available():
        return None

    try:
        resp = requests.post(
            f'{PI_URL}/predict',
            json={'features': features},
            timeout=PI_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        _record_success()
        return data
    except Exception as e:
        _record_failure()
        logger.debug(f'Pi predict failed: {e}')
        return None


def generate_report(prompt: str, model: str = 'qwen2.5:1.5b') -> str:
    """Generate trading report via Ollama on Pi.

    Returns report text or None.
    """
    if not _is_available():
        return None

    try:
        resp = requests.post(
            f'{PI_URL}/report',
            json={'prompt': prompt, 'model': model},
            timeout=PI_REPORT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        _record_success()
        return data.get('report', '')
    except Exception as e:
        _record_failure()
        logger.debug(f'Pi report failed: {e}')
        return None

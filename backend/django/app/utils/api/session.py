"""
Shared HTTP session for MT5 API calls.

Uses requests.Session with connection pooling to reuse TCP connections
across all API calls. Saves ~5-10ms per call by avoiding repeated
TCP handshakes. Pool size of 10 supports concurrent ThreadPoolExecutor
usage for parallel data fetching.
"""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv('MT5_API_URL', 'http://mt5:5001')

# Shared session with connection pooling and automatic retries
_session = requests.Session()

# Connection pool: 10 connections, retry on transient failures
adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=10,
    max_retries=Retry(
        total=2,
        backoff_factor=0.1,
        status_forcelist=[502, 503, 504],
    ),
)
_session.mount('http://', adapter)
_session.mount('https://', adapter)


def get_session() -> requests.Session:
    """Return the shared HTTP session for MT5 API calls."""
    return _session

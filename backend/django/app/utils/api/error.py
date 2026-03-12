import traceback
from typing import List, Dict
from dotenv import load_dotenv
import logging

from app.utils.api.session import get_session, BASE_URL

load_dotenv()
logger = logging.getLogger(__name__)

def last_error() -> Dict:
    try:
        url = f"{BASE_URL}/last_error"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        return data
    except Exception as e:
        error_msg = f"Exception fetching last error: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

def last_error_str() -> Dict:
    try:
        url = f"{BASE_URL}/last_error_str"
        response = get_session().get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        return data
    except Exception as e:
        error_msg = f"Exception fetching last error str: {e}\n{traceback.format_exc()}"
        logger.error(error_msg)

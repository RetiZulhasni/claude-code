"""Session bootstrap shared by every endpoint this scraper calls.

IDX's JSON endpoints (financial reports, securities list) are only
reliably served to requests that carry cookies from a normal page load
first -- calling them cold can return empty/blocked responses even with
correct URL and params. This module does that warm-up once per run.
"""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from idx_scraper.config import (
    API_HEADERS,
    BROWSER_HEADERS,
    SESSION_VALIDATE_URL,
    SESSION_WARMUP_URL,
)

logger = logging.getLogger(__name__)


def create_session(timeout: float = 20.0) -> requests.Session:
    """Return a requests.Session pre-warmed with cookies idx.co.id expects,
    with retries configured for transient network/5xx errors."""
    session = requests.Session()
    session.headers.update(API_HEADERS)

    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    try:
        session.get(SESSION_WARMUP_URL, headers=BROWSER_HEADERS, timeout=timeout)
        time.sleep(1)
        session.get(SESSION_VALIDATE_URL, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Session warm-up failed (continuing anyway): %s", exc)

    return session

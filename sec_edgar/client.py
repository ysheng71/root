"""
SEC EDGAR HTTP client with rate limiting and retry logic.

SEC requires:
- User-Agent header: "Name email@example.com"
- Max 10 requests/second
"""

from __future__ import annotations

import time
import threading
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

BASE_URL = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
MIN_REQUEST_INTERVAL = 0.12  # ~8 req/sec, safely under 10


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError):
        return exc.response is not None and exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


class EdgarClient:
    def __init__(self, user_agent: str):
        """
        Args:
            user_agent: Required by SEC, e.g. "Jane Doe jane@example.com"
        """
        self._lock = threading.Lock()
        self._last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json",
        })

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _get(self, url: str) -> Any:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_time
            wait = MIN_REQUEST_INTERVAL - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_request_time = time.monotonic()

        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_ticker_cik_map(self) -> dict[str, str]:
        """Returns {TICKER: cik10} mapping for all known companies."""
        raw = self._get(TICKERS_URL)
        # Response: {0: {cik_str, ticker, title}, 1: ...}
        return {
            v["ticker"].upper(): str(v["cik_str"]).zfill(10)
            for v in raw.values()
        }

    def get_submissions(self, cik10: str) -> dict:
        """
        Fetch company submissions (metadata + recent filings list).
        Handles pagination: merges additional files when filing history > ~1000.
        """
        url = f"{BASE_URL}/submissions/CIK{cik10}.json"
        data = self._get(url)

        # Merge paginated filing history
        additional_files = data.get("filings", {}).get("files", [])
        if additional_files:
            recent = data["filings"]["recent"]
            for file_info in additional_files:
                extra_url = f"{BASE_URL}/submissions/{file_info['name']}"
                extra = self._get(extra_url)
                # Each field in recent is a parallel array — append each
                for key, values in extra.items():
                    if isinstance(values, list) and key in recent:
                        recent[key].extend(values)

        return data

    def get_company_facts(self, cik10: str) -> dict:
        """
        Fetch all XBRL facts for a company (single large JSON, full history).
        Response shape:
          { cik, entityName, facts: { taxonomy: { concept: { label, description,
              units: { unit: [ {end, val, accn, fy, fp, form, filed, start?, frame?} ] }
          } } } }
        """
        url = f"{BASE_URL}/api/xbrl/companyfacts/CIK{cik10}.json"
        return self._get(url)

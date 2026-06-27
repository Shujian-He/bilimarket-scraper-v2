"""HTTP client for the Bilibili market API."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import requests

from .config import MARKET_API_URL
from .errors import APIResponseError, RequestFailed
from .models import MarketQuery

SleepFn = Callable[[float], None]
LogFn = Callable[[str], None]
JitterFn = Callable[[float, float], float]


class MarketClient:
    """Small API client with bounded, polite retry behavior."""

    def __init__(
        self,
        headers: dict[str, str],
        *,
        session: requests.Session | None = None,
        url: str = MARKET_API_URL,
        timeout: tuple[float, float] = (5.0, 15.0),
        max_attempts: int = 4,
        sleep: SleepFn = time.sleep,
        jitter: JitterFn = random.uniform,
        logger: LogFn | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self._headers = headers
        self._owns_session = session is None
        self._session = session or requests.Session()
        self._url = url
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._jitter = jitter
        self._logger = logger

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def fetch_page(self, query: MarketQuery, next_id: str | None) -> dict[str, Any]:
        payload = query.payload(next_id)
        last_reason = "unknown error"
        last_error: BaseException | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.post(
                    self._url,
                    headers=self._headers,
                    json=payload,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                last_reason = f"{exc.__class__.__name__}: {exc}"
                delay = _exponential_delay(attempt, self._jitter)
            else:
                status = response.status_code
                if status == 200:
                    return _decode_json_object(response)
                if status == 429:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    delay = retry_after if retry_after is not None else _exponential_delay(
                        attempt, self._jitter
                    )
                    last_reason = "HTTP 429"
                    last_error = RequestFailed(f"HTTP 429: {_preview(response.text)}")
                elif 500 <= status < 600:
                    delay = _exponential_delay(attempt, self._jitter)
                    last_reason = f"HTTP {status}"
                    last_error = RequestFailed(f"HTTP {status}: {_preview(response.text)}")
                else:
                    raise RequestFailed(f"HTTP {status}: {_preview(response.text)}")

            if attempt >= self._max_attempts:
                raise RequestFailed(
                    f"Request failed after {self._max_attempts} attempts: {last_reason}"
                ) from last_error

            if self._logger is not None:
                self._logger(
                    f"Retrying market request after attempt {attempt} "
                    f"because {last_reason}; sleeping {delay:.2f}s."
                )
            self._sleep(delay)

        raise RequestFailed("Request failed unexpectedly.")


def _decode_json_object(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise APIResponseError(f"HTTP 200 response was not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise APIResponseError("HTTP 200 response JSON must be an object.")
    return payload


def _parse_retry_after(value: str | None) -> float | None:
    try:
        delay = float(value) if value is not None else None
    except ValueError:
        return None
    return delay if delay is not None and delay >= 0 else None


def _exponential_delay(attempt: int, jitter: JitterFn) -> float:
    return min(30.0, (2 ** (attempt - 1)) + jitter(0.0, 1.0))


def _preview(text: str, *, limit: int = 300) -> str:
    compact = " ".join(text.split())
    return compact[:limit]

"""HTTP client for the Bilibili market API.

This module is responsible for sending one page request at a time to the
market list endpoint and translating transport-level problems into scraper
exceptions. It intentionally does not parse listing payloads; response shape
validation lives in ``models.Page``.

Components:
    SleepFn, LogFn, JitterFn: Callable type aliases used to inject deterministic
        timing and logging behavior in tests.
    MarketClient: A small wrapper around ``requests.Session`` with retry logic.
    _decode_json_object: Validates that HTTP 200 responses contain JSON objects.
    _parse_retry_after, _exponential_delay, _preview: Private helpers for retry
        timing and compact error messages.

Example:
    ``MarketClient(headers).fetch_page(query, None)`` returns the raw JSON
    object for the first API page.
"""

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
    """Small API client with bounded, polite retry behavior.

    Args:
        headers: ``dict[str, str]`` request headers, usually from
            ``auth.build_headers``.
        session: Optional ``requests.Session``. When omitted, the client owns
            and later closes a new session.
        url: ``str`` endpoint URL used for every market list request.
        timeout: ``tuple[float, float]`` connect/read timeout passed to
            ``requests``.
        max_attempts: ``int`` maximum number of attempts for retryable failures.
        sleep: ``Callable[[float], None]`` delay function, injectable for tests.
        jitter: ``Callable[[float, float], float]`` random jitter provider.
        logger: Optional ``Callable[[str], None]`` for retry messages.

    Example:
        ``client = MarketClient({"Cookie": "SESSDATA=abc"}, max_attempts=2)``
        creates a client that retries retryable failures once.
    """

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
        """Store request settings and create or adopt a ``requests`` session.

        Args:
            headers: ``dict[str, str]`` headers sent on each POST request.
            session: Optional ``requests.Session`` or compatible test double.
            url: ``str`` market API URL.
            timeout: ``tuple[float, float]`` connect/read timeout in seconds.
            max_attempts: ``int`` number of total attempts before giving up.
            sleep: ``Callable[[float], None]`` used between retries.
            jitter: ``Callable[[float, float], float]`` used by exponential
                backoff.
            logger: Optional ``Callable[[str], None]`` retry logger.

        Returns:
            None.

        Raises:
            ValueError: Raised when ``max_attempts`` is less than ``1``.

        Example:
            ``MarketClient({}, session=fake_session, sleep=list.append)`` lets
            a test observe outgoing calls and retry delays.
        """
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
        """Close the owned HTTP session, if this client created one.

        Args:
            None.

        Returns:
            None.

        Example:
            ``client.close()`` releases sockets for clients created without a
            caller-provided ``session``.
        """
        if self._owns_session:
            self._session.close()

    def fetch_page(self, query: MarketQuery, next_id: str | None) -> dict[str, Any]:
        """Fetch one market API page with retries for transient failures.

        Args:
            query: ``MarketQuery`` containing filters and sort order.
            next_id: ``str | None`` cursor from the previous page. ``None``
                fetches the first page.

        Returns:
            dict[str, Any]: The decoded top-level JSON object returned by the
            API, for example ``{"code": 0, "data": {"data": []}}``.

        Raises:
            RequestFailed: Raised for non-retryable HTTP errors or when all
                retry attempts are exhausted.
            APIResponseError: Raised when a successful response is not a JSON
                object.

        Example:
            ``payload = client.fetch_page(query, "cursor-1")`` sends
            ``query.payload("cursor-1")`` as the JSON request body.
        """
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
    """Decode a successful response and require a JSON object.

    Args:
        response: ``requests.Response`` returned from a status-200 request.

    Returns:
        dict[str, Any]: Decoded response JSON.

    Raises:
        APIResponseError: Raised when JSON decoding fails or the payload is not
        a mapping.

    Example:
        A response whose ``json()`` returns ``{"code": 0}`` produces that
        dictionary; a response whose ``json()`` returns ``[]`` is rejected.
    """
    try:
        payload = response.json()
    except ValueError as exc:
        raise APIResponseError(f"HTTP 200 response was not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise APIResponseError("HTTP 200 response JSON must be an object.")
    return payload


def _parse_retry_after(value: str | None) -> float | None:
    """Parse an HTTP ``Retry-After`` delay expressed in seconds.

    Args:
        value: ``str | None`` header value such as ``"2.5"``.

    Returns:
        float | None: Non-negative delay in seconds, or ``None`` when the value
        is absent, negative, or not numeric.

    Example:
        ``_parse_retry_after("2.5")`` returns ``2.5`` and
        ``_parse_retry_after("soon")`` returns ``None``.
    """
    try:
        delay = float(value) if value is not None else None
    except ValueError:
        return None
    return delay if delay is not None and delay >= 0 else None


def _exponential_delay(attempt: int, jitter: JitterFn) -> float:
    """Compute capped exponential backoff with caller-provided jitter.

    Args:
        attempt: ``int`` one-based attempt number.
        jitter: ``Callable[[float, float], float]`` random jitter provider.

    Returns:
        float: Delay in seconds, capped at ``30.0``.

    Example:
        ``_exponential_delay(1, lambda low, high: 0)`` returns ``1``.
    """
    return min(30.0, (2 ** (attempt - 1)) + jitter(0.0, 1.0))


def _preview(text: str, *, limit: int = 300) -> str:
    """Return a compact one-line preview for error messages.

    Args:
        text: ``str`` raw response body or error text.
        limit: ``int`` maximum number of characters to keep.

    Returns:
        str: Whitespace-normalized text truncated to ``limit`` characters.

    Example:
        ``_preview("a\\n b", limit=3)`` returns ``"a b"``.
    """
    compact = " ".join(text.split())
    return compact[:limit]

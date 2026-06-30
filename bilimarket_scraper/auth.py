"""Authentication helpers for Bilibili market requests.

This module owns the small amount of authentication glue needed before the
scraper can call the market API. It contains the cookie lookup rule and the
browser-like request headers shared by the HTTP client.

Components:
    load_cookie: Returns the cookie as ``str`` from the default
        ``cookies.txt`` file.
    build_headers: Returns ``dict[str, str]`` headers for authenticated JSON
        POST requests.

Example:
    ``headers = build_headers(load_cookie())`` prepares the headers later
    passed to ``MarketClient(headers)``.
"""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_COOKIE_FILE, DEFAULT_USER_AGENT, MARKET_REFERER
from .errors import ConfigurationError


def load_cookie() -> str:
    """Read the authentication cookie without logging or echoing the secret.

    Args:
        None.

    Returns:
        str: The non-empty cookie value, for example
        ``"SESSDATA=...; bili_jct=..."``.

    Raises:
        ConfigurationError: Raised when the default cookie file is missing,
        unreadable, or empty.

    Example:
        ``cookie = load_cookie()`` reads the repository-local ``cookies.txt``.
    """

    path = Path(DEFAULT_COOKIE_FILE)
    try:
        cookie = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Create cookie file: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Unable to read cookie file {path}: {exc}") from exc

    if not cookie:
        raise ConfigurationError(f"Cookie file is empty: {path}")
    return cookie


def build_headers(cookie: str, *, user_agent: str = DEFAULT_USER_AGENT) -> dict[str, str]:
    """Build browser-like headers for the JSON POST endpoint.

    Args:
        cookie: ``str`` authentication cookie copied from a logged-in browser.
        user_agent: ``str`` User-Agent header. It defaults to the packaged
            browser string but can be overridden in tests or manual probes.

    Returns:
        dict[str, str]: Header names mapped to header values. The result always
        contains ``Cookie``, ``Referer``, ``Origin``, and JSON content headers.

    Example:
        ``build_headers("SESSDATA=abc", user_agent="pytest")["Cookie"]``
        returns ``"SESSDATA=abc"``.
    """

    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "Origin": "https://mall.bilibili.com",
        "Pragma": "no-cache",
        "Referer": MARKET_REFERER,
        "User-Agent": user_agent,
        "Cookie": cookie,
    }

"""Cookie loading and request header construction."""

from __future__ import annotations

import os
from pathlib import Path

from .config import DEFAULT_USER_AGENT, MARKET_REFERER
from .errors import ConfigurationError


def load_cookie(cookie_file: Path | str | None, *, env_var: str = "BILI_COOKIE") -> str:
    """Read the authentication cookie without logging or echoing the secret."""

    env_cookie = os.environ.get(env_var, "").strip()
    if env_cookie:
        return env_cookie

    if cookie_file is None:
        raise ConfigurationError(f"Set {env_var} or provide --cookie-file.")

    path = Path(cookie_file)
    try:
        cookie = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Cookie file does not exist: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Unable to read cookie file {path}: {exc}") from exc

    if not cookie:
        raise ConfigurationError(f"Cookie file is empty: {path}")
    return cookie


def build_headers(cookie: str, *, user_agent: str = DEFAULT_USER_AGENT) -> dict[str, str]:
    """Build browser-like headers for the JSON POST endpoint."""

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

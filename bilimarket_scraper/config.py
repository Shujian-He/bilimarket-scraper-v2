"""Configuration constants for the Bilibili market scraper.

This module centralizes values that are shared across CLI parsing, request
construction, and run storage. It contains only constants so importing it has
no side effects and does not touch the network or filesystem.

Components:
    MARKET_API_URL, MARKET_REFERER, DEFAULT_USER_AGENT: ``str`` values used by
        the HTTP layer.
    VALID_*_FILTERS: ``frozenset[str]`` allow-lists used by CLI validation.
    DEFAULT_*: Default filter, sorting, cookie-file, and output-directory
        values used when users omit optional flags.

Example:
    ``DEFAULT_OUTPUT_DIR / "20260630-120000"`` is the default shape of a run
    directory created by ``RunStorage.new``.
"""

from __future__ import annotations

from pathlib import Path

MARKET_API_URL = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
MARKET_REFERER = "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)

VALID_PRICE_FILTERS = frozenset(
    {
        "0-2000",
        "2000-3000",
        "3000-5000",
        "5000-10000",
        "10000-20000",
        "20000-0",
    }
)
VALID_DISCOUNT_FILTERS = frozenset({"0-30", "30-50", "50-70", "70-100"})
VALID_CATEGORY_FILTERS = frozenset({"", "2312", "2066", "2331", "2273", "fudai_cate_id"})

DEFAULT_PRICE_FILTERS = ("10000-20000", "20000-0")
DEFAULT_DISCOUNT_FILTERS = ("0-30", "30-50", "50-70", "70-100")
DEFAULT_CATEGORY_FILTER = ""
DEFAULT_SORT_TYPE = "TIME_DESC"

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COOKIE_FILE = PACKAGE_ROOT / "cookies.txt"
DEFAULT_OUTPUT_DIR = PACKAGE_ROOT / "runs"

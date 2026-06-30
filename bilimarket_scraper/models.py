"""Typed request and response objects for the market API.

This module converts between raw Bilibili API JSON and small Python objects
used by the runner and storage layers. It owns validation of response shape,
normalization of listing fields, and export rows for CSV and SQLite.

Components:
    MarketQuery: Immutable request filter object that builds API payloads and
        checkpoint dictionaries.
    Listing: Immutable normalized listing with CSV and database row helpers.
    Page: Immutable parsed API page containing valid listings, cursor, and
        skipped item errors.
    _required_text, _optional_text, _required_int, _optional_int,
    _sum_market_prices, _json_safe_copy: Private parsing helpers.

Example:
    ``Page.from_response(payload, captured_at="2026-06-30T00:00:00+00:00")``
    validates a raw API payload and returns normalized ``Listing`` objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import DEFAULT_SORT_TYPE
from .errors import APIResponseError


@dataclass(frozen=True)
class MarketQuery:
    """Filters sent to the market list endpoint.

    Args:
        category_filter: ``str`` category id, or ``""`` for all categories.
        price_filters: ``tuple[str, ...]`` price ranges accepted by the API.
        discount_filters: ``tuple[str, ...]`` discount ranges accepted by the
            API.
        sort_type: ``str`` API sort mode, defaulting to ``TIME_DESC``.

    Example:
        ``MarketQuery("", ("20000-0",), ("70-100",))`` requests expensive
        listings with 70%-100% discount filters.
    """

    category_filter: str
    price_filters: tuple[str, ...]
    discount_filters: tuple[str, ...]
    sort_type: str = DEFAULT_SORT_TYPE

    def payload(self, next_id: str | None) -> dict[str, Any]:
        """Build the JSON request body for one API request.

        Args:
            next_id: ``str | None`` pagination cursor. ``None`` means the first
                page.

        Returns:
            dict[str, Any]: API payload with list-valued filters and ``nextId``.

        Example:
            ``query.payload("abc")["nextId"]`` returns ``"abc"``.
        """
        return {
            "categoryFilter": self.category_filter,
            "priceFilters": list(self.price_filters),
            "discountFilters": list(self.discount_filters),
            "sortType": self.sort_type,
            "nextId": next_id,
        }

    def as_checkpoint(self) -> dict[str, Any]:
        """Serialize stable query settings into checkpoint JSON shape.

        Args:
            None.

        Returns:
            dict[str, Any]: JSON-safe dictionary containing filters and sort
            mode, excluding the page cursor and counters.

        Example:
            ``query.as_checkpoint()["sortType"]`` returns ``"TIME_DESC"`` for
            the default query.
        """
        return {
            "categoryFilter": self.category_filter,
            "priceFilters": list(self.price_filters),
            "discountFilters": list(self.discount_filters),
            "sortType": self.sort_type,
        }


@dataclass(frozen=True)
class Listing:
    """A single market listing normalized from API JSON.

    Args:
        captured_at: ``str`` ISO timestamp when the page was fetched.
        listing_id: ``str`` unique listing id from ``c2cItemsId``.
        name: ``str`` normalized listing name.
        current_price: ``int`` current listing price in API units.
        market_price: ``int | None`` summed market price from detail rows.
        discount: ``float | None`` current price divided by market price.
        seller_uid: ``str | None`` seller id when present.
        seller_name: ``str | None`` seller display name when present.
        item_count: ``int | None`` number of items in the listing.
        payment_time: ``str | None`` payment time string from the API.
        detail_count: ``int`` number of detail entries in ``detailDtoList``.
        raw: ``dict[str, Any]`` JSON-safe copy of the original item.

    Example:
        ``Listing.from_api(item, captured_at="time").csv_row()`` turns raw API
        JSON into a row suitable for ``csv.writer``.
    """

    captured_at: str
    listing_id: str
    name: str
    current_price: int
    market_price: int | None
    discount: float | None
    seller_uid: str | None
    seller_name: str | None
    item_count: int | None
    payment_time: str | None
    detail_count: int
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, item: Any, *, captured_at: str) -> Listing:
        """Normalize one raw API item into a ``Listing``.

        Args:
            item: ``Any`` raw element from ``data.data``. It must be a
                ``dict`` with required id, name, and price fields.
            captured_at: ``str`` ISO timestamp attached to the containing page.

        Returns:
            Listing: Normalized listing with string ids, integer prices, and a
            JSON-safe ``raw`` copy.

        Raises:
            ValueError: Raised when required fields are missing, invalid, or a
                price is negative.

        Example:
            ``Listing.from_api({"c2cItemsId": 1, "c2cItemsName": "A",
            "price": "100"}, captured_at="time").listing_id`` returns
            ``"1"``.
        """
        if not isinstance(item, dict):
            raise ValueError("listing item must be an object")

        listing_id = _required_text(item.get("c2cItemsId"), "c2cItemsId")
        name = " ".join(_required_text(item.get("c2cItemsName"), "c2cItemsName").split())
        current_price = _required_int(item.get("price"), "price")
        if current_price < 0:
            raise ValueError("price must not be negative")

        details = item.get("detailDtoList")
        detail_count = len(details) if isinstance(details, list) else 0
        market_price = _sum_market_prices(details)
        discount = current_price / market_price if market_price and market_price > 0 else None

        return cls(
            captured_at=captured_at,
            listing_id=listing_id,
            name=name,
            current_price=current_price,
            market_price=market_price,
            discount=discount,
            seller_uid=_optional_text(item.get("uid")),
            seller_name=_optional_text(item.get("uname")),
            item_count=_optional_int(item.get("totalItemsCount")),
            payment_time=_optional_text(item.get("paymentTime")),
            detail_count=detail_count,
            raw=_json_safe_copy(item),
        )

    def csv_row(self) -> list[Any]:
        """Return the listing fields in ``CSV_HEADER`` order.

        Args:
            None.

        Returns:
            list[Any]: Values ready for ``csv.writer.writerow``. Optional values
            are converted to empty strings for easier spreadsheet reading.

        Example:
            ``listing.csv_row()[1]`` is the listing id.
        """
        return [
            self.captured_at,
            self.listing_id,
            self.name,
            self.current_price,
            "" if self.market_price is None else self.market_price,
            "" if self.discount is None else self.discount,
            "" if self.item_count is None else self.item_count,
            "" if self.seller_uid is None else self.seller_uid,
            "" if self.seller_name is None else self.seller_name,
            "" if self.payment_time is None else self.payment_time,
            self.detail_count,
        ]

    def db_row(self) -> tuple[Any, ...]:
        """Return the listing fields in ``UPSERT_SQL`` parameter order.

        Args:
            None.

        Returns:
            tuple[Any, ...]: SQLite parameter tuple, including ``raw`` encoded
            as deterministic JSON text.

        Example:
            ``listing.db_row()[0]`` is the primary-key listing id.
        """
        return (
            self.listing_id,
            self.name,
            self.current_price,
            self.market_price,
            self.discount,
            self.seller_uid,
            self.seller_name,
            self.item_count,
            self.payment_time,
            self.detail_count,
            self.captured_at,
            json.dumps(self.raw, ensure_ascii=False, sort_keys=True),
        )


@dataclass(frozen=True)
class Page:
    """A parsed API page.

    Args:
        listings: ``tuple[Listing, ...]`` valid listings parsed from the page.
        next_id: ``str | None`` cursor for the next page, or ``None`` at the end.
        skipped_errors: ``tuple[str, ...]`` per-item parse errors for malformed
            listings that were skipped.

    Example:
        ``page.next_id is None`` means the runner should stop after writing the
        current page.
    """

    listings: tuple[Listing, ...]
    next_id: str | None
    skipped_errors: tuple[str, ...]

    @classmethod
    def from_response(cls, response: Any, *, captured_at: str) -> Page:
        """Parse a raw API response into a ``Page``.

        Args:
            response: ``Any`` decoded JSON object returned by ``MarketClient``.
            captured_at: ``str`` ISO timestamp to attach to each listing.

        Returns:
            Page: Parsed page with valid listings, normalized next cursor, and
            skipped item messages.

        Raises:
            APIResponseError: Raised when top-level API status or response shape
                is invalid.

        Example:
            ``Page.from_response({"code": 0, "data": {"data": [],
            "nextId": ""}}, captured_at="time").next_id`` returns ``None``.
        """
        if not isinstance(response, dict):
            raise APIResponseError("API response must be a JSON object.")
        if response.get("code") != 0:
            message = response.get("message") or response.get("msg") or "unknown error"
            raise APIResponseError(f"API returned code {response.get('code')}: {message}")

        data = response.get("data")
        if not isinstance(data, dict):
            raise APIResponseError("API response data must be an object.")

        raw_items = data.get("data")
        if not isinstance(raw_items, list):
            raise APIResponseError("API response data.data must be a list.")

        next_id = data.get("nextId")
        normalized_next_id = None if next_id in (None, "") else str(next_id)

        listings: list[Listing] = []
        skipped: list[str] = []
        for index, item in enumerate(raw_items):
            try:
                listings.append(Listing.from_api(item, captured_at=captured_at))
            except ValueError as exc:
                skipped.append(f"item[{index}]: {exc}")

        return cls(
            listings=tuple(listings),
            next_id=normalized_next_id,
            skipped_errors=tuple(skipped),
        )


def _required_text(value: Any, field_name: str) -> str:
    """Convert a required value into non-empty stripped text.

    Args:
        value: ``Any`` value from API JSON.
        field_name: ``str`` API field name used in error messages.

    Returns:
        str: Stripped text representation.

    Raises:
        ValueError: Raised when the value is missing or blank.

    Example:
        ``_required_text(123, "id")`` returns ``"123"``.
    """
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    """Convert an optional value into stripped text or ``None``.

    Args:
        value: ``Any`` value from API JSON.

    Returns:
        str | None: Stripped text when present; otherwise ``None``.

    Example:
        ``_optional_text(" seller ")`` returns ``"seller"``.
    """
    text = str(value).strip() if value is not None else ""
    return text or None


def _required_int(value: Any, field_name: str) -> int:
    """Convert a required API value into ``int``.

    Args:
        value: ``Any`` value from API JSON.
        field_name: ``str`` API field name used in error messages.

    Returns:
        int: Parsed integer.

    Raises:
        ValueError: Raised when ``int(value)`` fails.

    Example:
        ``_required_int("1000", "price")`` returns ``1000``.
    """
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _optional_int(value: Any) -> int | None:
    """Convert an optional API value into ``int`` or ``None``.

    Args:
        value: ``Any`` value from API JSON.

    Returns:
        int | None: Parsed integer, or ``None`` for missing/blank/invalid input.

    Example:
        ``_optional_int("")`` returns ``None`` and ``_optional_int("2")``
        returns ``2``.
    """
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_market_prices(details: Any) -> int | None:
    """Sum ``marketPrice`` values from listing detail objects.

    Args:
        details: ``Any`` raw ``detailDtoList`` value from a listing item.

    Returns:
        int | None: Sum of valid market prices, or ``None`` when no usable
        prices are present.

    Example:
        ``_sum_market_prices([{"marketPrice": "1200"}, {"marketPrice": 800}])``
        returns ``2000``.
    """
    if not isinstance(details, list):
        return None

    total = 0
    found = False
    for detail in details:
        if not isinstance(detail, dict):
            continue
        value = _optional_int(detail.get("marketPrice"))
        if value is None:
            continue
        total += value
        found = True

    return total if found else None


def _json_safe_copy(value: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy that can be serialized as JSON.

    Args:
        value: ``dict[str, Any]`` raw API item.

    Returns:
        dict[str, Any]: Copy produced through JSON encode/decode so nested
        structures are detached from the original object.

    Example:
        ``_json_safe_copy({"id": 1})`` returns a separate ``{"id": 1}``
        dictionary.
    """
    return json.loads(json.dumps(value, ensure_ascii=False))

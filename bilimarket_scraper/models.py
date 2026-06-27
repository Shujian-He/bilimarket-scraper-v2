"""Typed request and response objects for the market API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import DEFAULT_SORT_TYPE
from .errors import APIResponseError


@dataclass(frozen=True)
class MarketQuery:
    """Filters sent to the market list endpoint."""

    category_filter: str
    price_filters: tuple[str, ...]
    discount_filters: tuple[str, ...]
    sort_type: str = DEFAULT_SORT_TYPE

    def payload(self, next_id: str | None) -> dict[str, Any]:
        return {
            "categoryFilter": self.category_filter,
            "priceFilters": list(self.price_filters),
            "discountFilters": list(self.discount_filters),
            "sortType": self.sort_type,
            "nextId": next_id,
        }

    def as_checkpoint(self) -> dict[str, Any]:
        return {
            "categoryFilter": self.category_filter,
            "priceFilters": list(self.price_filters),
            "discountFilters": list(self.discount_filters),
            "sortType": self.sort_type,
        }


@dataclass(frozen=True)
class Listing:
    """A single market listing normalized from API JSON."""

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
    """A parsed API page."""

    listings: tuple[Listing, ...]
    next_id: str | None
    skipped_errors: tuple[str, ...]

    @classmethod
    def from_response(cls, response: Any, *, captured_at: str) -> Page:
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
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _required_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_market_prices(details: Any) -> int | None:
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
    return json.loads(json.dumps(value, ensure_ascii=False))

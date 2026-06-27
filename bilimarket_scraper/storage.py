"""CSV, SQLite, and checkpoint storage for one scraper run."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Listing, MarketQuery

CSV_HEADER = [
    "captured_at",
    "listing_id",
    "name",
    "current_price",
    "market_price",
    "discount",
    "item_count",
    "seller_uid",
    "seller_name",
    "payment_time",
    "detail_count",
]

UPSERT_SQL = """
INSERT INTO listings (
    listing_id,
    name,
    current_price,
    market_price,
    discount,
    seller_uid,
    seller_name,
    item_count,
    payment_time,
    detail_count,
    captured_at,
    raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(listing_id) DO UPDATE SET
    name = excluded.name,
    current_price = excluded.current_price,
    market_price = excluded.market_price,
    discount = excluded.discount,
    seller_uid = excluded.seller_uid,
    seller_name = excluded.seller_name,
    item_count = excluded.item_count,
    payment_time = excluded.payment_time,
    detail_count = excluded.detail_count,
    captured_at = excluded.captured_at,
    raw_json = excluded.raw_json
"""


@dataclass(frozen=True)
class Checkpoint:
    next_id: str | None
    pages_written: int
    listings_written: int
    query: dict[str, Any]
    updated_at: str


class RunStorage:
    """Owns all output files for one scrape run."""

    def __init__(self, run_dir: Path | str, *, wanted_keywords: tuple[str, ...] = ()) -> None:
        self.run_dir = Path(run_dir)
        self.wanted_keywords = tuple(keyword for keyword in wanted_keywords if keyword)
        self.listings_csv = self.run_dir / "listings.csv"
        self.matches_csv = self.run_dir / "matches.csv"
        self.sqlite_path = self.run_dir / "market.sqlite3"
        self.checkpoint_path = self.run_dir / "state.json"
        self._connection: sqlite3.Connection | None = None

    @classmethod
    def new(
        cls,
        output_dir: Path | str,
        *,
        run_id: str | None = None,
        wanted_keywords: tuple[str, ...] = (),
    ) -> RunStorage:
        run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        return cls(Path(output_dir) / run_id, wanted_keywords=wanted_keywords)

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.sqlite_path)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._create_schema()
            self._ensure_csv(self.listings_csv)
            self._ensure_csv(self.matches_csv)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def persist_listings(self, listings: tuple[Listing, ...]) -> int:
        """Persist listings and return how many matched the wanted keywords."""

        matched = tuple(listing for listing in listings if self._matches_wanted(listing))
        connection = self.connection

        with (
            self.listings_csv.open("a+", newline="", encoding="utf-8") as listings_file,
            self.matches_csv.open("a+", newline="", encoding="utf-8") as matches_file,
        ):
            listings_file.seek(0, 2)
            matches_file.seek(0, 2)
            listings_position = listings_file.tell()
            matches_position = matches_file.tell()

            try:
                with connection:
                    connection.executemany(UPSERT_SQL, [listing.db_row() for listing in listings])
                    csv.writer(listings_file).writerows(
                        listing.csv_row() for listing in listings
                    )
                    csv.writer(matches_file).writerows(listing.csv_row() for listing in matched)
                    listings_file.flush()
                    matches_file.flush()
            except BaseException:
                listings_file.seek(listings_position)
                listings_file.truncate()
                matches_file.seek(matches_position)
                matches_file.truncate()
                raise

        return len(matched)

    def write_checkpoint(
        self,
        *,
        next_id: str | None,
        pages_written: int,
        listings_written: int,
        query: MarketQuery,
    ) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = Checkpoint(
            next_id=next_id,
            pages_written=pages_written,
            listings_written=listings_written,
            query=query.as_checkpoint(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        temp_path = self.checkpoint_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(checkpoint.__dict__, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.checkpoint_path)

    def read_checkpoint(self) -> Checkpoint | None:
        try:
            raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

        return Checkpoint(
            next_id=raw.get("next_id"),
            pages_written=int(raw.get("pages_written", 0)),
            listings_written=int(raw.get("listings_written", 0)),
            query=dict(raw.get("query", {})),
            updated_at=str(raw.get("updated_at", "")),
        )

    def _create_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                listing_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                current_price INTEGER NOT NULL,
                market_price INTEGER,
                discount REAL,
                seller_uid TEXT,
                seller_name TEXT,
                item_count INTEGER,
                payment_time TEXT,
                detail_count INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def _ensure_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 0:
            return
        with path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(CSV_HEADER)

    def _matches_wanted(self, listing: Listing) -> bool:
        if not self.wanted_keywords:
            return False
        haystack = listing.name.casefold()
        return any(keyword.casefold() in haystack for keyword in self.wanted_keywords)

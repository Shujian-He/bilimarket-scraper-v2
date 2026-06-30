"""CSV, SQLite, and checkpoint storage for one scraper run.

This module owns every file written under a run directory: ``listings.csv`` for
all parsed listings, ``matches.csv`` for keyword hits, ``market.sqlite3`` for
upserted queryable records, and ``state.json`` for resuming after interruption.

Components:
    CSV_HEADER: ``list[str]`` shared column order for listings and matches CSVs.
    UPSERT_SQL: ``str`` SQLite statement that inserts or updates by listing id.
    Checkpoint: Immutable representation of ``state.json``.
    RunStorage: File and database manager for one run directory.
    _text_tuple: Private helper for checkpoint text tuple normalization.

Example:
    ``RunStorage.new("runs", wanted_keywords=("miku",)).persist_listings(...)``
    writes CSV rows, SQLite rows, keyword matches, and later checkpoints.
"""

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
    """Resume metadata stored in ``state.json``.

    Args:
        next_id: ``str | None`` cursor for the next request.
        pages_written: ``int`` total pages already written.
        listings_written: ``int`` total listings already written.
        wanted_keywords: ``tuple[str, ...]`` keyword filters used for matches.
        query: ``dict[str, Any]`` serialized ``MarketQuery`` settings.
        updated_at: ``str`` ISO timestamp when the checkpoint was written.

    Example:
        ``checkpoint.next_id`` is passed back into ``ScraperRunner.run`` when
        resuming a run.
    """

    next_id: str | None
    pages_written: int
    listings_written: int
    wanted_keywords: tuple[str, ...]
    query: dict[str, Any]
    updated_at: str


class RunStorage:
    """Owns all output files for one scrape run.

    Args:
        run_dir: ``Path | str`` directory containing this run's files.
        wanted_keywords: ``tuple[str, ...]`` case-insensitive keywords used to
            copy matching listings into ``matches.csv``.

    Example:
        ``RunStorage("/tmp/run", wanted_keywords=("miku",))`` stores all files
        under ``/tmp/run`` and marks names containing ``miku`` as matches.
    """

    def __init__(self, run_dir: Path | str, *, wanted_keywords: tuple[str, ...] = ()) -> None:
        """Create a storage object without opening files immediately.

        Args:
            run_dir: ``Path | str`` output directory for this run.
            wanted_keywords: ``tuple[str, ...]`` keyword filters; blank values
                are discarded.

        Returns:
            None.

        Example:
            ``RunStorage(tmp_path / "run").connection`` lazily creates the
            directory, database, and CSV headers.
        """
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
        """Create storage for a new timestamped run directory.

        Args:
            output_dir: ``Path | str`` parent directory for run folders.
            run_id: ``str | None`` explicit run folder name. When omitted, the
                current local timestamp is used.
            wanted_keywords: ``tuple[str, ...]`` keyword filters for matches.

        Returns:
            RunStorage: Storage rooted at ``output_dir / run_id``.

        Example:
            ``RunStorage.new("runs", run_id="manual-test").run_dir`` points to
            ``runs/manual-test``.
        """
        run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        return cls(Path(output_dir) / run_id, wanted_keywords=wanted_keywords)

    @property
    def connection(self) -> sqlite3.Connection:
        """Return a ready SQLite connection, creating files on first use.

        Args:
            None.

        Returns:
            sqlite3.Connection: Open connection with schema and CSV headers
            initialized.

        Example:
            ``storage.connection.execute("SELECT 1")`` also ensures the run
            directory exists.
        """
        if self._connection is None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.sqlite_path)
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._create_schema()
            self._ensure_csv(self.listings_csv)
            self._ensure_csv(self.matches_csv)
        return self._connection

    def close(self) -> None:
        """Close the SQLite connection if it has been opened.

        Args:
            None.

        Returns:
            None.

        Example:
            ``storage.close()`` is safe to call even when no writes happened.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def persist_listings(self, listings: tuple[Listing, ...]) -> int:
        """Persist listings and return how many matched the wanted keywords.

        Args:
            listings: ``tuple[Listing, ...]`` normalized listings from one API
                page.

        Returns:
            int: Number of listings whose names matched ``wanted_keywords``.

        Raises:
            BaseException: Re-raises any SQLite or file-write error after
                rolling CSV files back to their previous lengths.

        Example:
            ``storage.persist_listings((listing,))`` appends to CSV, upserts the
            SQLite row, and returns ``1`` if the listing matched a keyword.
        """

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
                    # Keep database and CSV writes as close to atomic as this
                    # mixed storage format allows. If an error occurs after a
                    # CSV append, truncate the files back to their saved offsets.
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
        """Write ``state.json`` atomically for the last completed page.

        Args:
            next_id: ``str | None`` cursor returned by the page just written.
            pages_written: ``int`` total pages written after the page.
            listings_written: ``int`` total listings written after the page.
            query: ``MarketQuery`` filters needed for resume.

        Returns:
            None.

        Example:
            ``storage.write_checkpoint(next_id="cursor", pages_written=1,
            listings_written=20, query=query)`` records a resumable state.
        """
        self.run_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = Checkpoint(
            next_id=next_id,
            pages_written=pages_written,
            listings_written=listings_written,
            wanted_keywords=self.wanted_keywords,
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
        """Read ``state.json`` when it exists.

        Args:
            None.

        Returns:
            Checkpoint | None: Parsed checkpoint, or ``None`` when the file does
            not exist.

        Example:
            ``checkpoint = storage.read_checkpoint()`` returns ``None`` for a
            brand-new run directory.
        """
        try:
            raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

        return Checkpoint(
            next_id=raw.get("next_id"),
            pages_written=int(raw.get("pages_written", 0)),
            listings_written=int(raw.get("listings_written", 0)),
            wanted_keywords=_text_tuple(raw.get("wanted_keywords")),
            query=dict(raw.get("query", {})),
            updated_at=str(raw.get("updated_at", "")),
        )

    def _create_schema(self) -> None:
        """Create the SQLite listings table when missing.

        Args:
            None.

        Returns:
            None.

        Example:
            ``self._create_schema()`` is called during lazy connection setup.
        """
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
        """Create a CSV file with ``CSV_HEADER`` when it is empty or missing.

        Args:
            path: ``Path`` file path for either ``listings.csv`` or
                ``matches.csv``.

        Returns:
            None.

        Example:
            ``self._ensure_csv(self.listings_csv)`` creates a readable CSV even
            before any listings are written.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 0:
            return
        with path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(CSV_HEADER)

    def _matches_wanted(self, listing: Listing) -> bool:
        """Check whether a listing name contains any wanted keyword.

        Args:
            listing: ``Listing`` normalized listing to test.

        Returns:
            bool: ``True`` when at least one wanted keyword appears in the
            listing name, case-insensitively.

        Example:
            With ``wanted_keywords=("miku",)``, a listing named ``"Good Miku"``
            matches.
        """
        if not self.wanted_keywords:
            return False
        haystack = listing.name.casefold()
        return any(keyword.casefold() in haystack for keyword in self.wanted_keywords)


def _text_tuple(value: Any) -> tuple[str, ...]:
    """Normalize checkpoint text values into a tuple of non-empty strings.

    Args:
        value: ``Any`` value from checkpoint JSON, usually a list of strings.

    Returns:
        tuple[str, ...]: Stripped non-empty strings, or an empty tuple for
        unsupported input.

    Example:
        ``_text_tuple([" a ", "", "b"])`` returns ``("a", "b")``.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, list | tuple):
        return ()
    return tuple(text for item in value if (text := str(item).strip()))

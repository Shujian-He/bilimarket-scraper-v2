"""Scrape orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event

from .client import MarketClient
from .errors import CursorStalled
from .models import MarketQuery, Page
from .rate_limit import DelayPolicy
from .storage import RunStorage

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class ScrapeResult:
    status: str
    pages_written: int
    listings_written: int
    matched_written: int
    next_id: str | None
    run_dir: str


class ScraperRunner:
    """Fetch pages, persist them, and update checkpoints at page boundaries."""

    def __init__(
        self,
        *,
        client: MarketClient,
        storage: RunStorage,
        query: MarketQuery,
        delay_policy: DelayPolicy,
        stop_event: Event | None = None,
        logger: LogFn = print,
    ) -> None:
        self._client = client
        self._storage = storage
        self._query = query
        self._delay_policy = delay_policy
        self._stop_event = stop_event
        self._logger = logger

    def run(
        self,
        *,
        start_next_id: str | None = None,
        start_pages_written: int = 0,
        start_listings_written: int = 0,
        max_pages: int | None = None,
    ) -> ScrapeResult:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1 when provided")

        current_id = start_next_id
        pages_written = start_pages_written
        listings_written = start_listings_written
        matched_written = 0
        pages_this_run = 0

        while True:
            if self._stop_requested():
                return self._result(
                    "stopped",
                    pages_written,
                    listings_written,
                    matched_written,
                    current_id,
                )

            if self._delay_policy.before_request(self._stop_event):
                return self._result(
                    "stopped",
                    pages_written,
                    listings_written,
                    matched_written,
                    current_id,
                )

            response = self._client.fetch_page(self._query, current_id)
            captured_at = datetime.now(timezone.utc).isoformat()
            page = Page.from_response(response, captured_at=captured_at)

            if page.next_id is not None and page.next_id == current_id:
                raise CursorStalled(f"API cursor did not advance: {page.next_id}")

            matched_count = self._storage.persist_listings(page.listings)
            pages_written += 1
            pages_this_run += 1
            listings_written += len(page.listings)
            matched_written += matched_count
            self._storage.write_checkpoint(
                next_id=page.next_id,
                pages_written=pages_written,
                listings_written=listings_written,
                query=self._query,
            )

            if page.skipped_errors:
                self._logger(f"Skipped {len(page.skipped_errors)} malformed listings.")
            self._logger(
                "Page saved: "
                f"page={pages_written}, listings={len(page.listings)}, "
                f"matches={matched_count}, "
                f"next_id={page.next_id if page.next_id is not None else '<end>'}"
            )

            if max_pages is not None and pages_this_run >= max_pages:
                return self._result(
                    "max_pages",
                    pages_written,
                    listings_written,
                    matched_written,
                    page.next_id,
                )

            if page.next_id is None:
                return self._result(
                    "finished",
                    pages_written,
                    listings_written,
                    matched_written,
                    None,
                )

            current_id = page.next_id
            if self._delay_policy.after_page(self._stop_event):
                return self._result(
                    "stopped",
                    pages_written,
                    listings_written,
                    matched_written,
                    current_id,
                )

    def _stop_requested(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    def _result(
        self,
        status: str,
        pages_written: int,
        listings_written: int,
        matched_written: int,
        next_id: str | None,
    ) -> ScrapeResult:
        return ScrapeResult(
            status=status,
            pages_written=pages_written,
            listings_written=listings_written,
            matched_written=matched_written,
            next_id=next_id,
            run_dir=str(self._storage.run_dir),
        )

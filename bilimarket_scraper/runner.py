"""Scrape orchestration for paginated market collection.

This module coordinates the scraper's main loop. It asks the HTTP client for a
page, asks the model layer to parse it, asks storage to persist it, and writes a
checkpoint after each completed page so interrupted runs can resume safely.

Components:
    LogFn: ``Callable[[str], None]`` type alias for status messages.
    ScrapeResult: Immutable summary returned by ``ScraperRunner.run``.
    ScraperRunner: Stateful coordinator for one scrape run.

Example:
    ``ScraperRunner(client=client, storage=storage, query=query,
    delay_policy=policy).run(max_pages=1)`` fetches and persists one page.
"""

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
    """Summary of a completed, stopped, or page-limited scrape run.

    Args:
        status: ``str`` terminal state such as ``"finished"`` or
            ``"max_pages"``.
        pages_written: ``int`` total pages written for the run directory.
        listings_written: ``int`` total listings written for the run directory.
        matched_written: ``int`` keyword-matching listings written during this
            invocation.
        next_id: ``str | None`` cursor to resume from, or ``None`` at the end.
        run_dir: ``str`` filesystem path to the run output directory.

    Example:
        ``result.status == "finished"`` means the API returned no next cursor.
    """

    status: str
    pages_written: int
    listings_written: int
    matched_written: int
    next_id: str | None
    run_dir: str


class ScraperRunner:
    """Fetch pages, persist them, and update checkpoints at page boundaries.

    Args:
        client: ``MarketClient`` or compatible object with ``fetch_page``.
        storage: ``RunStorage`` destination for CSV, SQLite, and checkpoints.
        query: ``MarketQuery`` filters sent for every page request.
        delay_policy: ``DelayPolicy`` controlling short and long sleeps.
        stop_event: Optional ``threading.Event`` used for graceful stop checks.
        logger: ``Callable[[str], None]`` status logger.

    Example:
        ``ScraperRunner(..., logger=lambda message: None)`` suppresses progress
        output in tests.
    """

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
        """Store collaborators used by the scrape loop.

        Args:
            client: ``MarketClient`` request layer.
            storage: ``RunStorage`` persistence layer.
            query: ``MarketQuery`` immutable request filters.
            delay_policy: ``DelayPolicy`` sleep strategy.
            stop_event: ``Event | None`` cooperative cancellation signal.
            logger: ``Callable[[str], None]`` progress sink.

        Returns:
            None.

        Example:
            ``ScraperRunner(client=fake, storage=storage, query=query,
            delay_policy=no_delay())`` builds a deterministic test runner.
        """
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
        """Run the scrape loop until stopped, exhausted, or page-limited.

        Args:
            start_next_id: ``str | None`` cursor from a checkpoint. ``None``
                starts at the first page.
            start_pages_written: ``int`` existing page count from a checkpoint.
            start_listings_written: ``int`` existing listing count from a
                checkpoint.
            max_pages: ``int | None`` optional number of pages to fetch in this
                invocation.

        Returns:
            ScrapeResult: Final status and counters.

        Raises:
            ValueError: Raised when ``max_pages`` is provided but less than
                ``1``.
            CursorStalled: Raised when the API repeats the current cursor, which
                would otherwise create an infinite loop.

        Example:
            ``runner.run(start_next_id="cursor-1", max_pages=5)`` resumes from
            ``cursor-1`` and stops after at most five new pages.
        """
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
        """Check whether cooperative cancellation has been requested.

        Args:
            None.

        Returns:
            bool: ``True`` when a stop event exists and is set.

        Example:
            ``self._stop_requested()`` lets the loop exit before starting a new
            request.
        """
        return self._stop_event is not None and self._stop_event.is_set()

    def _result(
        self,
        status: str,
        pages_written: int,
        listings_written: int,
        matched_written: int,
        next_id: str | None,
    ) -> ScrapeResult:
        """Build a ``ScrapeResult`` using the current storage directory.

        Args:
            status: ``str`` terminal status label.
            pages_written: ``int`` page counter to report.
            listings_written: ``int`` listing counter to report.
            matched_written: ``int`` matched listing counter to report.
            next_id: ``str | None`` cursor to store in the result.

        Returns:
            ScrapeResult: Immutable result object for callers and the CLI.

        Example:
            ``self._result("stopped", 3, 30, 2, "cursor")`` reports a
            resumable run.
        """
        return ScrapeResult(
            status=status,
            pages_written=pages_written,
            listings_written=listings_written,
            matched_written=matched_written,
            next_id=next_id,
            run_dir=str(self._storage.run_dir),
        )

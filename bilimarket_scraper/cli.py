"""Command line interface for the standalone scraper.

This module translates terminal arguments into scraper objects and handles the
top-level process exit codes. Parsing and validation stay here so the runner can
focus on scraping and the storage layer can focus on files.

Components:
    build_parser: Builds the ``argparse.ArgumentParser`` and all supported
        flags.
    main: Entry point used by ``python -m bilimarket_scraper``.
    _run_context_from_args: Creates or resumes ``RunStorage`` and query state.
    _query_from_args, _query_from_checkpoint: Build ``MarketQuery`` instances.
    _delay_policy_from_args, _split_values, _validate_values: CLI helper
        functions for timing and filter validation.

Example:
    ``main(["--max-pages", "1", "--no-sleep"])`` runs a one-page scrape and
    returns a process-style integer exit code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .auth import build_headers, load_cookie
from .client import MarketClient
from .config import (
    DEFAULT_CATEGORY_FILTER,
    DEFAULT_DISCOUNT_FILTERS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PRICE_FILTERS,
    DEFAULT_SORT_TYPE,
    VALID_CATEGORY_FILTERS,
    VALID_DISCOUNT_FILTERS,
    VALID_PRICE_FILTERS,
)
from .errors import ScraperError
from .models import MarketQuery
from .rate_limit import DelayPolicy
from .runner import ScraperRunner
from .storage import Checkpoint, RunStorage


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for scraper options.

    Args:
        None.

    Returns:
        argparse.ArgumentParser: Parser whose ``parse_args`` method returns the
        namespace consumed by ``main`` and helper functions.

    Example:
        ``build_parser().parse_args(["--max-pages", "1"]).max_pages`` returns
        ``1``.
    """
    parser = argparse.ArgumentParser(
        description="Standalone modular scraper for Bilibili C2C market listings."
    )
    parser.add_argument("--want", nargs="*", default=None, help="Wanted keywords.")
    parser.add_argument(
        "--price",
        nargs="+",
        default=None,
        help="Supported price filters, for example: 10000-20000 20000-0.",
    )
    parser.add_argument(
        "--discount",
        nargs="+",
        default=None,
        help="Supported discount filters, for example: 70-100.",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Category id, or blank for all categories.",
    )
    parser.add_argument("--run-id", help="Optional run directory name.")
    parser.add_argument("--resume-dir", type=Path, help="Existing run directory to resume.")
    parser.add_argument("--max-pages", type=int, help="Stop after this many fetched pages.")
    parser.add_argument("--min-delay", type=float, default=1.2)
    parser.add_argument("--max-delay", type=float, default=2.8)
    parser.add_argument("--long-pause-every", type=int, default=50)
    parser.add_argument("--long-pause-seconds", type=float, default=45.0)
    parser.add_argument(
        "--no-sleep",
        action="store_true",
        help="Disable scraper sleeps for local tests or a one-page manual probe.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the scraper from command-line arguments.

    Args:
        argv: ``list[str] | None`` command-line arguments excluding the program
            name. ``None`` makes ``argparse`` read ``sys.argv``.

    Returns:
        int: Process-style exit code: ``0`` for success, ``1`` for expected
        scraper/configuration failures, and ``130`` for keyboard interruption.

    Example:
        ``main(["--max-pages", "1", "--no-sleep"])`` performs a bounded run
        suitable for a manual smoke test.
    """
    args = build_parser().parse_args(argv)

    try:
        storage, query, checkpoint = _run_context_from_args(args)
        start_next_id = checkpoint.next_id if checkpoint is not None else None
        start_pages = 0
        start_listings = 0
        if checkpoint is not None:
            start_pages = checkpoint.pages_written
            start_listings = checkpoint.listings_written

        delay_policy = _delay_policy_from_args(args)
        cookie = load_cookie()
        client = MarketClient(build_headers(cookie), logger=print)

        try:
            runner = ScraperRunner(
                client=client,
                storage=storage,
                query=query,
                delay_policy=delay_policy,
            )
            result = runner.run(
                start_next_id=start_next_id,
                start_pages_written=start_pages,
                start_listings_written=start_listings,
                max_pages=args.max_pages,
            )
        finally:
            client.close()
            storage.close()

        print(
            "Scrape ended: "
            f"status={result.status}, pages={result.pages_written}, "
            f"listings={result.listings_written}, matches={result.matched_written}, "
            f"run_dir={result.run_dir}"
        )
        return 0
    except (ScraperError, OSError, ValueError) as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Last completed page remains checkpointed.", file=sys.stderr)
        return 130


def _run_context_from_args(
    args: argparse.Namespace,
) -> tuple[RunStorage, MarketQuery, Checkpoint | None]:
    """Build storage, query, and optional checkpoint from parsed CLI args.

    Args:
        args: ``argparse.Namespace`` returned by ``build_parser().parse_args``.

    Returns:
        tuple[RunStorage, MarketQuery, Checkpoint | None]: Storage target,
        request query, and checkpoint when resuming.

    Raises:
        ValueError: Raised for incompatible resume options or missing
        checkpoints.

    Example:
        Passing args parsed from ``["--resume-dir", "runs/demo"]`` loads query
        and keyword settings from ``runs/demo/state.json``.
    """
    if args.resume_dir is not None:
        if args.run_id:
            raise ValueError("--run-id cannot be used with --resume-dir")
        _reject_resume_managed_args(args)

        checkpoint_reader = RunStorage(args.resume_dir)
        checkpoint = checkpoint_reader.read_checkpoint()
        if checkpoint is None:
            raise ValueError(f"No checkpoint found in resume directory: {args.resume_dir}")

        query = _query_from_checkpoint(checkpoint)
        storage = RunStorage(args.resume_dir, wanted_keywords=checkpoint.wanted_keywords)
        return storage, query, checkpoint

    query = _query_from_args(args)
    keywords = _split_values(args.want)
    storage = RunStorage.new(DEFAULT_OUTPUT_DIR, run_id=args.run_id, wanted_keywords=keywords)
    return storage, query, None


def _reject_resume_managed_args(args: argparse.Namespace) -> None:
    """Reject options that must come from a resume checkpoint.

    Args:
        args: ``argparse.Namespace`` parsed CLI options.

    Returns:
        None.

    Raises:
        ValueError: Raised when users combine ``--resume-dir`` with filters or
        keyword options that would make the checkpoint ambiguous.

    Example:
        ``--resume-dir runs/demo --price 0-2000`` raises because price filters
        are loaded from ``state.json`` during resume.
    """
    conflicts = []
    if args.want is not None:
        conflicts.append("--want")
    if args.price is not None:
        conflicts.append("--price")
    if args.discount is not None:
        conflicts.append("--discount")
    if args.category is not None:
        conflicts.append("--category")

    if conflicts:
        raise ValueError(
            f"{', '.join(conflicts)} cannot be used with --resume-dir; "
            "values are loaded from state.json"
        )


def _query_from_args(args: argparse.Namespace) -> MarketQuery:
    """Create a ``MarketQuery`` from new-run CLI arguments.

    Args:
        args: ``argparse.Namespace`` parsed CLI options.

    Returns:
        MarketQuery: Validated query using defaults for omitted filters.

    Raises:
        ValueError: Raised when category, price, or discount values are not in
        the supported allow-lists.

    Example:
        With no filter flags, ``_query_from_args(args).price_filters`` returns
        ``DEFAULT_PRICE_FILTERS``.
    """
    price_values = DEFAULT_PRICE_FILTERS if args.price is None else args.price
    discount_values = DEFAULT_DISCOUNT_FILTERS if args.discount is None else args.discount
    prices = _validate_values("price", _split_values(price_values), VALID_PRICE_FILTERS)
    discounts = _validate_values(
        "discount", _split_values(discount_values), VALID_DISCOUNT_FILTERS
    )
    category = DEFAULT_CATEGORY_FILTER if args.category is None else args.category.strip()
    if category not in VALID_CATEGORY_FILTERS:
        raise ValueError(f"Unsupported category filter: {category!r}")
    return MarketQuery(
        category_filter=category,
        price_filters=prices,
        discount_filters=discounts,
    )


def _query_from_checkpoint(checkpoint: Checkpoint) -> MarketQuery:
    """Rebuild a ``MarketQuery`` from checkpoint JSON data.

    Args:
        checkpoint: ``Checkpoint`` read from an existing run directory.

    Returns:
        MarketQuery: Query matching the original run's filters and sort mode.

    Raises:
        ValueError: Raised when checkpoint filters are missing or unsupported.

    Example:
        A checkpoint query with ``{"categoryFilter": "2312"}`` resumes with
        ``MarketQuery.category_filter == "2312"``.
    """
    raw = checkpoint.query
    category = str(raw.get("categoryFilter", DEFAULT_CATEGORY_FILTER)).strip()
    if category not in VALID_CATEGORY_FILTERS:
        raise ValueError(f"Checkpoint has unsupported category filter: {category!r}")

    prices = _validate_values(
        "price",
        _split_values(raw.get("priceFilters")),
        VALID_PRICE_FILTERS,
    )
    discounts = _validate_values(
        "discount",
        _split_values(raw.get("discountFilters")),
        VALID_DISCOUNT_FILTERS,
    )
    sort_type = str(raw.get("sortType") or DEFAULT_SORT_TYPE).strip()
    return MarketQuery(
        category_filter=category,
        price_filters=prices,
        discount_filters=discounts,
        sort_type=sort_type,
    )


def _delay_policy_from_args(args: argparse.Namespace) -> DelayPolicy:
    """Create a ``DelayPolicy`` from parsed timing flags.

    Args:
        args: ``argparse.Namespace`` parsed CLI options.

    Returns:
        DelayPolicy: Delay configuration for ``ScraperRunner``.

    Raises:
        ValueError: Raised when delay values are negative or min/max are
        reversed.

    Example:
        ``--no-sleep`` returns a policy whose short and long delays are all
        ``0.0``.
    """
    min_delay = 0.0 if args.no_sleep else args.min_delay
    max_delay = 0.0 if args.no_sleep else args.max_delay
    long_pause_seconds = 0.0 if args.no_sleep else args.long_pause_seconds

    if min_delay < 0 or max_delay < 0 or max_delay < min_delay:
        raise ValueError("--min-delay and --max-delay must be non-negative and ordered")
    if args.long_pause_every < 0 or long_pause_seconds < 0:
        raise ValueError("Long pause settings must be non-negative")

    return DelayPolicy(
        min_seconds=min_delay,
        max_seconds=max_delay,
        long_pause_every=args.long_pause_every,
        long_pause_seconds=long_pause_seconds,
    )


def _split_values(values: Any) -> tuple[str, ...]:
    """Normalize CLI list/comma values into a tuple of strings.

    Args:
        values: ``Any`` value from argparse or checkpoint JSON. It may be
            ``None``, a string, or an iterable of values.

    Returns:
        tuple[str, ...]: Non-empty stripped tokens.

    Example:
        ``_split_values(["a,b", " c "])`` returns ``("a", "b", "c")``.
    """
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)

    split: list[str] = []
    for value in values:
        split.extend(part.strip() for part in str(value).split(","))
    return tuple(part for part in split if part)


def _validate_values(
    name: str,
    values: tuple[str, ...],
    allowed: frozenset[str],
) -> tuple[str, ...]:
    """Validate that every filter value belongs to an allow-list.

    Args:
        name: ``str`` display name used in error messages, such as ``"price"``.
        values: ``tuple[str, ...]`` candidate filter values.
        allowed: ``frozenset[str]`` supported filter values.

    Returns:
        tuple[str, ...]: The original ``values`` when all entries are valid.

    Raises:
        ValueError: Raised when values are empty or contain unsupported entries.

    Example:
        ``_validate_values("price", ("20000-0",), VALID_PRICE_FILTERS)``
        returns ``("20000-0",)``.
    """
    invalid = tuple(value for value in values if value not in allowed)
    if invalid:
        raise ValueError(f"Unsupported {name} filter(s): {', '.join(invalid)}")
    if not values:
        raise ValueError(f"At least one {name} filter is required")
    return values

"""Command line interface for the standalone scraper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auth import build_headers, load_cookie
from .client import MarketClient
from .config import (
    DEFAULT_CATEGORY_FILTER,
    DEFAULT_COOKIE_FILE,
    DEFAULT_DISCOUNT_FILTERS,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PRICE_FILTERS,
    VALID_CATEGORY_FILTERS,
    VALID_DISCOUNT_FILTERS,
    VALID_PRICE_FILTERS,
)
from .errors import ScraperError
from .models import MarketQuery
from .rate_limit import DelayPolicy
from .runner import ScraperRunner
from .storage import RunStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone modular scraper for Bilibili C2C market listings."
    )
    parser.add_argument("--want", nargs="*", default=(), help="Wanted keywords.")
    parser.add_argument(
        "--price",
        nargs="+",
        default=list(DEFAULT_PRICE_FILTERS),
        help="Supported price filters, for example: 10000-20000 20000-0.",
    )
    parser.add_argument(
        "--discount",
        nargs="+",
        default=list(DEFAULT_DISCOUNT_FILTERS),
        help="Supported discount filters, for example: 70-100.",
    )
    parser.add_argument(
        "--category",
        default=DEFAULT_CATEGORY_FILTER,
        help="Category id, or blank for all categories.",
    )
    parser.add_argument("--cookie-file", type=Path, default=DEFAULT_COOKIE_FILE)
    parser.add_argument("--cookie-env", default="BILI_COOKIE")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", help="Optional run directory name.")
    parser.add_argument("--resume-dir", type=Path, help="Existing run directory to resume.")
    parser.add_argument("--start-next-id", help="Manual cursor override.")
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
    args = build_parser().parse_args(argv)

    try:
        query = _query_from_args(args)
        keywords = _split_values(args.want)
        storage = _storage_from_args(args, keywords)
        checkpoint = storage.read_checkpoint() if args.resume_dir else None
        start_next_id = args.start_next_id
        start_pages = 0
        start_listings = 0
        if checkpoint is not None and start_next_id is None:
            start_next_id = checkpoint.next_id
            start_pages = checkpoint.pages_written
            start_listings = checkpoint.listings_written

        delay_policy = _delay_policy_from_args(args)
        cookie = load_cookie(args.cookie_file, env_var=args.cookie_env)
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


def _query_from_args(args: argparse.Namespace) -> MarketQuery:
    prices = _validate_values("price", _split_values(args.price), VALID_PRICE_FILTERS)
    discounts = _validate_values(
        "discount", _split_values(args.discount), VALID_DISCOUNT_FILTERS
    )
    category = args.category.strip()
    if category not in VALID_CATEGORY_FILTERS:
        raise ValueError(f"Unsupported category filter: {category!r}")
    return MarketQuery(
        category_filter=category,
        price_filters=prices,
        discount_filters=discounts,
    )


def _storage_from_args(args: argparse.Namespace, keywords: tuple[str, ...]) -> RunStorage:
    if args.resume_dir is not None:
        if args.run_id:
            raise ValueError("--run-id cannot be used with --resume-dir")
        return RunStorage(args.resume_dir, wanted_keywords=keywords)
    return RunStorage.new(args.output_dir, run_id=args.run_id, wanted_keywords=keywords)


def _delay_policy_from_args(args: argparse.Namespace) -> DelayPolicy:
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


def _split_values(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    split: list[str] = []
    for value in values:
        split.extend(part.strip() for part in str(value).split(","))
    return tuple(part for part in split if part)


def _validate_values(
    name: str,
    values: tuple[str, ...],
    allowed: frozenset[str],
) -> tuple[str, ...]:
    invalid = tuple(value for value in values if value not in allowed)
    if invalid:
        raise ValueError(f"Unsupported {name} filter(s): {', '.join(invalid)}")
    if not values:
        raise ValueError(f"At least one {name} filter is required")
    return values

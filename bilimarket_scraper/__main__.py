"""Module entry point for ``python -m bilimarket_scraper``.

This module delegates directly to ``cli.main`` and converts the returned integer
into a process exit status. Keeping the entry point tiny prevents import-time
side effects from running before argument parsing.

Components:
    main: Imported ``Callable[[list[str] | None], int]`` command-line entry
        point from ``bilimarket_scraper.cli``.

Example:
    ``python -m bilimarket_scraper --max-pages 1 --no-sleep`` executes this
    file and exits with the code returned by ``main``.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

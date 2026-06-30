"""Standalone Bilibili C2C market scraper package.

This package exposes the command-line scraper implementation as importable
modules. Public consumers normally enter through ``bilimarket_scraper.cli`` or
``python -m bilimarket_scraper`` rather than importing individual internals.

Components:
    __version__: ``str`` package version used by tools or diagnostics.

Example:
    ``from bilimarket_scraper import __version__`` returns the installed package
    version string.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"

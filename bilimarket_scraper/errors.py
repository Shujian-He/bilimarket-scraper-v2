"""Exception hierarchy for the standalone scraper.

This module defines scraper-specific runtime errors so the CLI can catch
expected failures separately from programming errors. The classes carry message
strings only; no extra fields are required by current callers.

Components:
    ScraperError: Base class for all expected scraper failures.
    ConfigurationError: Missing or invalid local setup such as cookies.
    RequestFailed: Transport or HTTP failure after retry handling.
    APIResponseError: Successful HTTP response with unusable API payload.
    CursorStalled: Repeated cursor that would make the runner loop forever.

Example:
    ``raise ConfigurationError("Create cookie file: cookies.txt")`` is caught
    by ``cli.main`` and printed as a user-facing scrape failure.
"""


class ScraperError(RuntimeError):
    """Base class for expected scraper failures.

    Args:
        *args: ``object`` message arguments accepted by ``RuntimeError``.

    Example:
        ``except ScraperError`` catches configuration, request, response, and
        cursor failures in one place.
    """


class ConfigurationError(ScraperError):
    """Raised when local configuration is missing or invalid.

    Args:
        *args: ``object`` message arguments accepted by ``RuntimeError``.

    Example:
        ``ConfigurationError("Cookie file is empty")`` reports an actionable
        setup problem to the CLI.
    """


class RequestFailed(ScraperError):
    """Raised when the API request fails after bounded retries.

    Args:
        *args: ``object`` message arguments accepted by ``RuntimeError``.

    Example:
        ``RequestFailed("HTTP 403: forbidden")`` represents a non-retryable
        HTTP response.
    """


class APIResponseError(ScraperError):
    """Raised when the API response cannot be parsed safely.

    Args:
        *args: ``object`` message arguments accepted by ``RuntimeError``.

    Example:
        ``APIResponseError("API response data must be an object.")`` tells the
        caller the HTTP request succeeded but the JSON shape was wrong.
    """


class CursorStalled(ScraperError):
    """Raised when the remote cursor repeats and would cause a loop.

    Args:
        *args: ``object`` message arguments accepted by ``RuntimeError``.

    Example:
        ``CursorStalled("API cursor did not advance: cursor-1")`` prevents the
        runner from writing the same page forever.
    """

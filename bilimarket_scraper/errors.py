"""Exception hierarchy for the standalone scraper."""


class ScraperError(RuntimeError):
    """Base class for scraper failures."""


class ConfigurationError(ScraperError):
    """Raised when local configuration is missing or invalid."""


class RequestFailed(ScraperError):
    """Raised when the API request fails after bounded retries."""


class APIResponseError(ScraperError):
    """Raised when the API response cannot be parsed safely."""


class CursorStalled(ScraperError):
    """Raised when the remote cursor repeats and would cause a loop."""

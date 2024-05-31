class DuckDuckGoSearchException(Exception):
    """Base exception class for duckduckgo_search."""


class RatelimitException(DuckDuckGoSearchException):
    """Raised for rate limit exceeded errors during API requests."""


class TimeoutException(DuckDuckGoSearchException):
    """Raised for timeout errors during API requests."""

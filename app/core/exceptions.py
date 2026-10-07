"""
Domain exceptions for the workflow executor.

These are raised by repository/service layers and caught by FastAPI
exception handlers registered in app/main.py.
"""


class NotFoundError(Exception):
    """Raised when a requested resource does not exist."""
    pass


class ConflictError(Exception):
    """Raised when an operation conflicts with the current state (e.g., active runs exist)."""
    pass


class StaleDataError(Exception):
    """Raised when an optimistic lock version mismatch is detected."""
    pass

"""Exceptions for the pygob library."""


class GobError(Exception):
    """Base class for all pygob errors."""


class GobDecodeError(GobError):
    """Raised when decoding fails."""


class GobEncodeError(GobError):
    """Raised when encoding fails."""

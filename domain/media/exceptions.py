"""Enhanced exception hierarchy for media domain."""


class MediaException(Exception):
    """Base exception for all media-related errors."""
    pass


class ValidationException(MediaException):
    """Raised when validation fails."""
    pass


class ProcessingException(MediaException):
    """Raised when media processing fails."""
    pass


class DuplicateException(MediaException):
    """Raised when a duplicate media file is detected."""
    pass


class StateTransitionException(MediaException):
    """Raised when an invalid state transition is attempted."""
    pass


class MetadataException(MediaException):
    """Raised when metadata extraction fails."""
    pass


class RepositoryException(MediaException):
    """Raised when repository operations fail."""
    pass


class HashCalculationException(MediaException):
    """Raised when hash calculation fails."""
    pass


class InvalidStateTransitionException(StateTransitionException):
    """Legacy exception name - maintained for compatibility."""
    pass

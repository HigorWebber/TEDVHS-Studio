"""Custom exceptions for TEDVHS Studio."""


class TEDVHSException(Exception):
    """Base exception for TEDVHS Studio."""
    pass


class RepositoryException(TEDVHSException):
    """Exception raised for repository operations."""
    pass


class ValidationException(TEDVHSException):
    """Exception raised for validation errors."""
    pass


class ConfigurationException(TEDVHSException):
    """Exception raised for configuration errors."""
    pass


class TaskException(TEDVHSException):
    """Exception raised for task management errors."""
    pass


class MediaProcessingException(TEDVHSException):
    """Exception raised for media processing errors."""
    pass
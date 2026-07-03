"""Exceções de domínio de mídia reexportadas da camada shared."""

from shared.exceptions import (
    MediaException,
    ValidationException,
    ProcessingException,
    DuplicateException,
    StateTransitionException,
    InvalidStateTransitionException,
    MetadataException,
    RepositoryException,
    HashCalculationException,
    MediaProcessingException,
)

__all__ = [
    "MediaException",
    "ValidationException",
    "ProcessingException",
    "DuplicateException",
    "StateTransitionException",
    "InvalidStateTransitionException",
    "MetadataException",
    "RepositoryException",
    "HashCalculationException",
    "MediaProcessingException",
]

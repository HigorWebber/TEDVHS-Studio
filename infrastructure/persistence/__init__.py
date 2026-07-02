"""Persistence infrastructure module."""

from infrastructure.persistence.repositories import Repository, IRepository

__all__ = [
    'Repository',
    'IRepository',
]
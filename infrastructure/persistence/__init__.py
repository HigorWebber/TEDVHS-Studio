"""Camada de persistência do TEDVHS Studio.

Implementações de repositórios e acesso a dados.
"""

from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository

__all__ = [
    'SQLiteMediaRepository',
]

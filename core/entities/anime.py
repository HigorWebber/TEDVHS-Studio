"""Entidade Anime."""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Anime:
    """Modelo de domínio para Anime.
    
    Attributes:
        id: ID único do anime
        name: Nome do anime
        description: Descrição
        thumbnail_path: Caminho para miniatura
        total_episodes: Total de episódios
        created_at: Data de criação
        updated_at: Data de última atualização
    """
    
    id: Optional[int] = None
    name: str = ""
    description: Optional[str] = None
    thumbnail_path: Optional[str] = None
    total_episodes: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

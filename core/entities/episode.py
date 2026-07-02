"""Entidade Episode."""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Episode:
    """Modelo de domínio para Episode.
    
    Attributes:
        id: ID único do episódio
        anime_id: ID do anime
        episode_number: Número do episódio
        title: Título do episódio
        file_path: Caminho do arquivo de vídeo
        duration: Duração em segundos
        file_size: Tamanho do arquivo em bytes
        processed: Indica se foi processado
        created_at: Data de criação
        updated_at: Data de última atualização
    """
    
    id: Optional[int] = None
    anime_id: Optional[int] = None
    episode_number: int = 0
    title: Optional[str] = None
    file_path: str = ""
    duration: Optional[float] = None
    file_size: Optional[int] = None
    processed: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

"""Entidade Clip."""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Clip:
    """Modelo de domínio para Clip.
    
    Attributes:
        id: ID único do clip
        episode_id: ID do episódio
        anime_id: ID do anime
        start_time: Tempo de início em segundos
        end_time: Tempo de término em segundos
        duration: Duração em segundos
        file_path: Caminho do arquivo de vídeo
        file_size: Tamanho do arquivo em bytes
        thumbnail_id: ID da miniatura
        created_at: Data de criação
        updated_at: Data de última atualização
    """
    
    id: Optional[int] = None
    episode_id: Optional[int] = None
    anime_id: Optional[int] = None
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    file_path: str = ""
    file_size: Optional[int] = None
    thumbnail_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

"""Entidade Project."""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Project:
    """Modelo de domínio para Project.
    
    Attributes:
        id: ID único do projeto
        name: Nome do projeto
        description: Descrição
        directory: Diretório do projeto
        thumbnail_path: Caminho para miniatura
        total_clips: Total de clips no projeto
        created_at: Data de criação
        updated_at: Data de última atualização
    """
    
    id: Optional[int] = None
    name: str = ""
    description: Optional[str] = None
    directory: str = ""
    thumbnail_path: Optional[str] = None
    total_clips: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

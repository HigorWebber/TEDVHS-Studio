"""Migrações de banco de dados."""

import logging
from typing import List

from core.database.connection import DatabaseConnection


logger = logging.getLogger(__name__)


# SQL das tabelas
CREATE_TABLES_SQL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS anime (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        thumbnail_path TEXT,
        total_episodes INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS episode (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anime_id INTEGER NOT NULL,
        episode_number INTEGER NOT NULL,
        title TEXT,
        file_path TEXT NOT NULL UNIQUE,
        duration REAL,
        file_size INTEGER,
        processed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE,
        UNIQUE(anime_id, episode_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clip (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        episode_id INTEGER NOT NULL,
        anime_id INTEGER NOT NULL,
        start_time REAL NOT NULL,
        end_time REAL NOT NULL,
        duration REAL NOT NULL,
        file_path TEXT NOT NULL UNIQUE,
        file_size INTEGER,
        thumbnail_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE,
        FOREIGN KEY (anime_id) REFERENCES anime(id) ON DELETE CASCADE,
        FOREIGN KEY (thumbnail_id) REFERENCES thumbnail(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS thumbnail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id INTEGER NOT NULL,
        file_path TEXT NOT NULL UNIQUE,
        file_size INTEGER,
        width INTEGER,
        height INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (clip_id) REFERENCES clip(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tag (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        color TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS clip_tag (
        clip_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (clip_id, tag_id),
        FOREIGN KEY (clip_id) REFERENCES clip(id) ON DELETE CASCADE,
        FOREIGN KEY (tag_id) REFERENCES tag(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        directory TEXT NOT NULL UNIQUE,
        thumbnail_path TEXT,
        total_clips INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS favorite (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clip_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (clip_id) REFERENCES clip(id) ON DELETE CASCADE,
        UNIQUE(clip_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL,
        results_count INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

# Índices para otimização
CREATE_INDEXES_SQL: List[str] = [
    "CREATE INDEX IF NOT EXISTS idx_anime_name ON anime(name)",
    "CREATE INDEX IF NOT EXISTS idx_episode_anime_id ON episode(anime_id)",
    "CREATE INDEX IF NOT EXISTS idx_episode_processed ON episode(processed)",
    "CREATE INDEX IF NOT EXISTS idx_clip_anime_id ON clip(anime_id)",
    "CREATE INDEX IF NOT EXISTS idx_clip_episode_id ON clip(episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_clip_created_at ON clip(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_thumbnail_clip_id ON thumbnail(clip_id)",
    "CREATE INDEX IF NOT EXISTS idx_tag_name ON tag(name)",
    "CREATE INDEX IF NOT EXISTS idx_project_name ON project(name)",
    "CREATE INDEX IF NOT EXISTS idx_search_history_created_at ON search_history(created_at)",
]


def run_migrations(connection: DatabaseConnection) -> None:
    """Executar todas as migrações de banco de dados.
    
    Args:
        connection: Conexão com o banco de dados
        
    Raises:
        RuntimeError: Se houver erro nas migrações
    """
    try:
        logger.info("Iniciando migrações do banco de dados")
        
        # Criar tabelas
        for idx, sql in enumerate(CREATE_TABLES_SQL, 1):
            try:
                connection.execute(sql)
                connection.commit()
                logger.debug(f"Tabela {idx}/{len(CREATE_TABLES_SQL)} criada/verificada")
            except Exception as e:
                logger.error(f"Erro ao criar tabela {idx}: {e}", exc_info=True)
                raise
        
        # Criar índices
        for idx, sql in enumerate(CREATE_INDEXES_SQL, 1):
            try:
                connection.execute(sql)
                connection.commit()
                logger.debug(f"Índice {idx}/{len(CREATE_INDEXES_SQL)} criado/verificado")
            except Exception as e:
                logger.error(f"Erro ao criar índice {idx}: {e}", exc_info=True)
                raise
        
        logger.info("Migrações concluídas com sucesso")
        
    except Exception as e:
        logger.error(f"Erro ao executar migrações: {e}", exc_info=True)
        raise RuntimeError(f"Falha ao executar migrações: {e}")

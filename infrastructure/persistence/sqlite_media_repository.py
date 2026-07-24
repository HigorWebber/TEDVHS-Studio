"""Implementação de repository SQLite para Media Library Engine."""

import logging
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.database.connection import DatabaseConnection
from domain.media.media_file import (
    AudioInfo,
    FileInfo,
    HashInfo,
    MediaFile,
    ProcessingInfo,
    VideoInfo,
)
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import Duration, FileHash, FileSize, MediaId, Resolution


logger = logging.getLogger(__name__)


class SQLiteMediaRepository:
    """Repository para persistência de MediaFile em SQLite."""

    def __init__(self, db_connection: DatabaseConnection):
        self.db = db_connection
        self._active_session_id: Optional[str] = None
        self._active_library_folder: str = "Sem pasta"
        self._active_library_season: str = "Sem temporada"
        self._ensure_schema()
        logger.info("SQLiteMediaRepository inicializado")

    def _ensure_schema(self) -> None:
        """Garantir que o schema existe e aplicar migrações leves."""
        try:
            cursor = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='media_files'"
            )
            if cursor.fetchone() is None:
                schema_path = Path(__file__).parent / "media_schema.sql"
                if schema_path.exists():
                    with open(schema_path, "r", encoding="utf-8") as file:
                        sql = file.read()
                    for statement in sql.split(";"):
                        if statement.strip():
                            self.db.execute(statement)
                    self.db.commit()
                    logger.info("Schema de mídia criado com sucesso")

            self._ensure_import_session_columns()
            self._ensure_library_folder_schema()
            self._ensure_scene_schema()
            self._ensure_clip_export_schema()
            self._migrate_media_files_uniqueness_if_needed()
        except Exception as exc:
            logger.error("Erro ao garantir schema: %s", exc, exc_info=True)
            raise

    def _ensure_import_session_columns(self) -> None:
        """Criar tabela de sessões e adicionar colunas novas em bancos antigos."""
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS import_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                folder_path TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                status TEXT DEFAULT 'IN_PROGRESS',
                total_files_found INTEGER DEFAULT 0,
                total_files_valid INTEGER DEFAULT 0,
                total_files_imported INTEGER DEFAULT 0,
                total_files_duplicate INTEGER DEFAULT 0,
                total_files_failed INTEGER DEFAULT 0,
                total_duration_seconds REAL DEFAULT 0,
                total_size_bytes INTEGER DEFAULT 0
            )"""
        )

        columns = {
            row[1]
            for row in self.db.execute(
                "PRAGMA table_info(import_sessions)"
            ).fetchall()
        }
        if "total_files_duplicate" not in columns:
            self.db.execute(
                "ALTER TABLE import_sessions "
                "ADD COLUMN total_files_duplicate INTEGER DEFAULT 0"
            )

        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_status "
            "ON import_sessions(status)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_started_at "
            "ON import_sessions(started_at)"
        )
        self.db.commit()

    def _ensure_library_folder_schema(self) -> None:
        """Criar estrutura simples de pastas e temporadas internas da biblioteca."""
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS media_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS media_seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_name TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(folder_name, name)
            )"""
        )

        media_columns = {row[1] for row in self.db.execute("PRAGMA table_info(media_files)").fetchall()}
        if media_columns and "library_folder" not in media_columns:
            self.db.execute(
                "ALTER TABLE media_files ADD COLUMN library_folder TEXT DEFAULT 'Sem pasta'"
            )
        if media_columns and "library_season" not in media_columns:
            self.db.execute(
                "ALTER TABLE media_files ADD COLUMN library_season TEXT DEFAULT 'Sem temporada'"
            )

        self.db.execute(
            "INSERT OR IGNORE INTO media_folders (name) VALUES (?)",
            ("Sem pasta",),
        )
        self.db.execute(
            "INSERT OR IGNORE INTO media_seasons (folder_name, name) VALUES (?, ?)",
            ("Sem pasta", "Sem temporada"),
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_library_folder ON media_files(library_folder)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_library_season ON media_files(library_season)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_library_folder_season ON media_files(library_folder, library_season)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_seasons_folder ON media_seasons(folder_name)")
        self.db.commit()

    def _migrate_media_files_uniqueness_if_needed(self) -> None:
        """Remover UNIQUE global de hash/caminho e adicionar temporada em bancos antigos.

        O mesmo vídeo pode aparecer em pastas/temporadas diferentes da biblioteca.
        A detecção de duplicado passa a considerar a localização interna
        (pasta + temporada), e não apenas o hash global ou o nome do arquivo.
        """
        row = self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='media_files'"
        ).fetchone()
        create_sql = row[0] if row else ""
        normalized_sql = create_sql.upper().replace("  ", " ")
        needs_migration = (
            "FILE_HASH TEXT UNIQUE" in normalized_sql
            or "FILE_PATH TEXT NOT NULL UNIQUE" in normalized_sql
            or "LIBRARY_SEASON" not in normalized_sql
        )
        if not needs_migration:
            return

        logger.info("Migrando media_files para suportar pastas/temporadas e duplicados por localização")
        backup_name = f"media_files_backup_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        self.db.execute(f"ALTER TABLE media_files RENAME TO {backup_name}")
        self._create_media_files_table()

        old_columns = {row[1] for row in self.db.execute(f"PRAGMA table_info({backup_name})").fetchall()}
        target_columns = [
            "id", "import_session_id", "file_path", "file_name", "file_extension",
            "file_size_bytes", "file_hash", "is_duplicate", "duplicate_of_hash",
            "duration_seconds", "fps", "width", "height", "resolution", "codec_video",
            "codec_audio", "audio_channels", "status", "import_date", "metadata_version",
            "processing_attempts", "last_error", "library_folder", "library_season",
        ]
        defaults = {
            "is_duplicate": "0",
            "metadata_version": "1",
            "processing_attempts": "0",
            "library_folder": "'Sem pasta'",
            "library_season": "'Sem temporada'",
        }
        select_exprs = [column if column in old_columns else defaults.get(column, "NULL") for column in target_columns]
        self.db.execute(
            f"""INSERT OR IGNORE INTO media_files ({', '.join(target_columns)})
                SELECT {', '.join(select_exprs)}
                FROM {backup_name}"""
        )
        self._create_media_indexes()
        self.db.commit()

    def _create_media_files_table(self) -> None:
        """Criar tabela media_files sem UNIQUE global de arquivo/hash."""
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS media_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_session_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_extension TEXT,
                file_size_bytes INTEGER,
                file_hash TEXT NOT NULL,
                is_duplicate BOOLEAN DEFAULT 0,
                duplicate_of_hash TEXT,
                duration_seconds REAL,
                fps REAL,
                width INTEGER,
                height INTEGER,
                resolution TEXT,
                codec_video TEXT,
                codec_audio TEXT,
                audio_channels INTEGER,
                status TEXT DEFAULT 'metadata_pending',
                import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata_version INTEGER DEFAULT 1,
                processing_attempts INTEGER DEFAULT 0,
                last_error TEXT,
                library_folder TEXT DEFAULT 'Sem pasta',
                library_season TEXT DEFAULT 'Sem temporada',
                FOREIGN KEY (import_session_id) REFERENCES import_sessions(session_id)
            )"""
        )

    def _create_media_indexes(self) -> None:
        """Criar índices usados pela biblioteca."""
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_import_session ON media_files(import_session_id)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_file_hash ON media_files(file_hash)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_file_path ON media_files(file_path)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_status ON media_files(status)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_import_date ON media_files(import_date)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_is_duplicate ON media_files(is_duplicate)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_library_folder ON media_files(library_folder)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_library_season ON media_files(library_season)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_library_folder_season ON media_files(library_folder, library_season)")

    def _ensure_scene_schema(self) -> None:
        """Criar estrutura de cenas detectadas e catálogo visual."""
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS media_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id INTEGER NOT NULL,
                scene_number INTEGER NOT NULL,
                sort_order INTEGER,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                duration_seconds REAL NOT NULL,
                custom_start_seconds REAL,
                custom_end_seconds REAL,
                custom_duration_seconds REAL,
                is_merged INTEGER DEFAULT 0,
                source_scene_ids TEXT,
                segments_json TEXT,
                display_name TEXT,
                detection_threshold REAL DEFAULT 0.35,
                status TEXT DEFAULT 'detected',
                description TEXT,
                tags TEXT,
                scene_type TEXT DEFAULT 'Geral',
                thumbnail_path TEXT,
                analysis_frames_json TEXT,
                ai_status TEXT DEFAULT 'pending',
                is_favorite INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY (media_id) REFERENCES media_files(id) ON DELETE CASCADE,
                UNIQUE(media_id, scene_number)
            )"""
        )

        columns = {row[1] for row in self.db.execute("PRAGMA table_info(media_scenes)").fetchall()}
        migrations = {
            "custom_start_seconds": "ALTER TABLE media_scenes ADD COLUMN custom_start_seconds REAL",
            "custom_end_seconds": "ALTER TABLE media_scenes ADD COLUMN custom_end_seconds REAL",
            "custom_duration_seconds": "ALTER TABLE media_scenes ADD COLUMN custom_duration_seconds REAL",
            "is_merged": "ALTER TABLE media_scenes ADD COLUMN is_merged INTEGER DEFAULT 0",
            "source_scene_ids": "ALTER TABLE media_scenes ADD COLUMN source_scene_ids TEXT",
            "segments_json": "ALTER TABLE media_scenes ADD COLUMN segments_json TEXT",
            "display_name": "ALTER TABLE media_scenes ADD COLUMN display_name TEXT",
            "sort_order": "ALTER TABLE media_scenes ADD COLUMN sort_order INTEGER",
            "description": "ALTER TABLE media_scenes ADD COLUMN description TEXT",
            "tags": "ALTER TABLE media_scenes ADD COLUMN tags TEXT",
            "scene_type": "ALTER TABLE media_scenes ADD COLUMN scene_type TEXT DEFAULT 'Geral'",
            "thumbnail_path": "ALTER TABLE media_scenes ADD COLUMN thumbnail_path TEXT",
            "analysis_frames_json": "ALTER TABLE media_scenes ADD COLUMN analysis_frames_json TEXT",
            "ai_status": "ALTER TABLE media_scenes ADD COLUMN ai_status TEXT DEFAULT 'pending'",
            "is_favorite": "ALTER TABLE media_scenes ADD COLUMN is_favorite INTEGER DEFAULT 0",
            "updated_at": "ALTER TABLE media_scenes ADD COLUMN updated_at TIMESTAMP",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self.db.execute(sql)

        # Bancos antigos passam a usar a ordem cronológica atual como ordem inicial.
        self.db.execute(
            "UPDATE media_scenes SET sort_order = scene_number "
            "WHERE sort_order IS NULL OR sort_order <= 0"
        )

        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_scenes_media_id ON media_scenes(media_id)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_scenes_number ON media_scenes(media_id, scene_number)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_scenes_sort_order ON media_scenes(media_id, sort_order)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_scenes_type ON media_scenes(scene_type)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_media_scenes_favorite ON media_scenes(is_favorite)")
        self.db.commit()

    def _ensure_clip_export_schema(self) -> None:
        """Criar tabela de clipes exportados em MP4."""
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS exported_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id INTEGER NOT NULL,
                scene_id INTEGER,
                clip_name TEXT NOT NULL,
                output_path TEXT NOT NULL,
                metadata_path TEXT,
                library_folder TEXT DEFAULT 'Sem pasta',
                library_season TEXT DEFAULT 'Sem temporada',
                episode_name TEXT,
                duration_seconds REAL DEFAULT 0,
                segments_json TEXT,
                description TEXT,
                tags TEXT,
                scene_type TEXT,
                export_mode TEXT DEFAULT 'precise_ffmpeg_reencode',
                status TEXT DEFAULT 'exported',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )"""
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(exported_clips)").fetchall()}
        migrations = {
            "metadata_path": "ALTER TABLE exported_clips ADD COLUMN metadata_path TEXT",
            "library_folder": "ALTER TABLE exported_clips ADD COLUMN library_folder TEXT DEFAULT 'Sem pasta'",
            "library_season": "ALTER TABLE exported_clips ADD COLUMN library_season TEXT DEFAULT 'Sem temporada'",
            "episode_name": "ALTER TABLE exported_clips ADD COLUMN episode_name TEXT",
            "segments_json": "ALTER TABLE exported_clips ADD COLUMN segments_json TEXT",
            "description": "ALTER TABLE exported_clips ADD COLUMN description TEXT",
            "tags": "ALTER TABLE exported_clips ADD COLUMN tags TEXT",
            "scene_type": "ALTER TABLE exported_clips ADD COLUMN scene_type TEXT",
            "export_mode": "ALTER TABLE exported_clips ADD COLUMN export_mode TEXT DEFAULT 'precise_ffmpeg_reencode'",
            "status": "ALTER TABLE exported_clips ADD COLUMN status TEXT DEFAULT 'exported'",
            "updated_at": "ALTER TABLE exported_clips ADD COLUMN updated_at TIMESTAMP",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self.db.execute(sql)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_exported_clips_media_id ON exported_clips(media_id)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_exported_clips_scene_id ON exported_clips(scene_id)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_exported_clips_folder ON exported_clips(library_folder)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_exported_clips_created ON exported_clips(created_at)")
        self.db.commit()

    def create_import_session(self, session_id: str, folder_path: str) -> int:
        """Criar nova sessão de importação.

        É idempotente: se a sessão já existir, retorna o ID existente.
        """
        try:
            existing = self.db.execute(
                "SELECT id FROM import_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if existing:
                return int(existing[0])

            cursor = self.db.execute(
                """INSERT INTO import_sessions (session_id, folder_path, status)
                   VALUES (?, ?, 'IN_PROGRESS')""",
                (session_id, folder_path),
            )
            self.db.commit()
            return int(cursor.lastrowid)
        except Exception as exc:
            logger.error("Erro ao criar sessão: %s", exc, exc_info=True)
            raise

    def add(self, media: MediaFile) -> MediaFile:
        """Adicionar arquivo de mídia usando a sessão ativa."""
        session_id = self._active_session_id
        if not session_id:
            raise RuntimeError("Sessão ativa de importação não definida no repositório")

        media_id = self.add_media_file(media, session_id)
        if media_id is None:
            raise sqlite3.IntegrityError("Arquivo duplicado ou já existente")

        media.id = media_id
        return media

    def update(self, media: MediaFile) -> MediaFile:
        """Atualizar dados principais do arquivo de mídia."""
        if media.id is None:
            raise ValueError("Não é possível atualizar mídia sem ID")

        try:
            self.db.execute(
                """UPDATE media_files SET
                   status = ?,
                   metadata_version = ?,
                   processing_attempts = ?,
                   last_error = ?
                   WHERE id = ?""",
                (
                    media.processing_info.status.value,
                    media.processing_info.metadata_version,
                    media.processing_info.processing_attempts,
                    media.processing_info.last_error,
                    media.id.value,
                ),
            )
            self.db.commit()
            return media
        except Exception as exc:
            logger.error("Erro ao atualizar arquivo: %s", exc, exc_info=True)
            raise

    def add_media_file(self, media: MediaFile, session_id: str) -> Optional[MediaId]:
        """Adicionar arquivo de mídia ao repositório."""
        try:
            library_folder = self._normalize_folder_name(getattr(self, "_active_library_folder", None))
            library_season = self._normalize_season_name(getattr(self, "_active_library_season", None))

            existing_same_location = self.find_by_hash_in_location(
                media.hash_info.file_hash,
                library_folder,
                library_season,
                originals_only=True,
            )
            if existing_same_location and not media.hash_info.is_duplicate:
                logger.info(
                    "Arquivo duplicado na mesma pasta/temporada: %s | %s / %s",
                    media.file_info.file_path,
                    library_folder,
                    library_season,
                )
                return None

            display_file_name = media.file_info.file_name
            name_conflict = self.find_name_conflict_in_location(
                display_file_name,
                library_folder,
                library_season,
            )
            if name_conflict and str(name_conflict.hash_info.file_hash) != str(media.hash_info.file_hash):
                display_file_name = self.generate_unique_file_name(
                    display_file_name,
                    library_folder,
                    library_season,
                )
                logger.info(
                    "Nome repetido na mesma pasta/temporada. Nome visual ajustado para: %s",
                    display_file_name,
                )

            cursor = self.db.execute(
                """INSERT INTO media_files (
                    import_session_id, file_path, file_name, file_extension,
                    file_size_bytes, file_hash, is_duplicate, duplicate_of_hash,
                    duration_seconds, fps, width, height, resolution,
                    codec_video, codec_audio, audio_channels, status,
                    metadata_version, processing_attempts, library_folder, library_season
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    media.file_info.file_path,
                    display_file_name,
                    media.file_info.file_extension,
                    media.file_info.file_size.bytes,
                    str(media.hash_info.file_hash),
                    1 if media.hash_info.is_duplicate else 0,
                    str(media.hash_info.duplicate_of_hash) if media.hash_info.duplicate_of_hash else None,
                    media.video_info.duration.seconds if media.video_info.duration else None,
                    media.video_info.fps,
                    media.video_info.resolution.width if media.video_info.resolution else None,
                    media.video_info.resolution.height if media.video_info.resolution else None,
                    str(media.video_info.resolution) if media.video_info.resolution else None,
                    media.video_info.codec_video,
                    media.audio_info.codec_audio,
                    media.audio_info.audio_channels,
                    media.processing_info.status.value,
                    media.processing_info.metadata_version,
                    media.processing_info.processing_attempts,
                    library_folder,
                    library_season,
                ),
            )
            self.db.commit()
            media_id = MediaId(cursor.lastrowid)
            logger.info("Arquivo de mídia adicionado: %s (id=%s)", media.file_info.file_name, media_id.value)
            return media_id
        except sqlite3.IntegrityError as exc:
            logger.info("Arquivo já existe ou viola constraint: %s", exc)
            return None
        except Exception as exc:
            logger.error("Erro ao adicionar arquivo: %s", exc, exc_info=True)
            raise

    def find_by_hash(self, file_hash: FileHash) -> Optional[MediaFile]:
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE file_hash = ?",
                (str(file_hash),),
            )
            row = cursor.fetchone()
            return self._row_to_media_file(row) if row else None
        except Exception as exc:
            logger.error("Erro ao buscar por hash: %s", exc, exc_info=True)
            raise

    def find_by_hash_in_location(
        self,
        file_hash: FileHash,
        library_folder: Optional[str] = None,
        library_season: Optional[str] = None,
        originals_only: bool = True,
    ) -> Optional[MediaFile]:
        """Encontrar arquivo por hash dentro da mesma pasta/temporada interna."""
        folder = self._normalize_folder_name(library_folder or getattr(self, "_active_library_folder", None))
        season = self._normalize_season_name(library_season or getattr(self, "_active_library_season", None))
        try:
            sql = (
                "SELECT * FROM media_files WHERE file_hash = ? "
                "AND library_folder = ? AND COALESCE(library_season, 'Sem temporada') = ?"
            )
            params: list[Any] = [str(file_hash), folder, season]
            if originals_only:
                sql += " AND COALESCE(is_duplicate, 0) = 0"
            sql += " ORDER BY import_date ASC LIMIT 1"
            cursor = self.db.execute(sql, tuple(params))
            row = cursor.fetchone()
            return self._row_to_media_file(row) if row else None
        except Exception as exc:
            logger.error("Erro ao buscar por hash na pasta/temporada: %s", exc, exc_info=True)
            raise

    def find_by_status(self, status: ProcessingStatus, limit: int = 100) -> List[MediaFile]:
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE status = ? ORDER BY import_date DESC LIMIT ?",
                (status.value, limit),
            )
            return [self._row_to_media_file(row) for row in cursor.fetchall()]
        except Exception as exc:
            logger.error("Erro ao buscar por status: %s", exc, exc_info=True)
            raise

    def find_by_session(self, session_id: str) -> List[MediaFile]:
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE import_session_id = ? ORDER BY import_date DESC",
                (session_id,),
            )
            return [self._row_to_media_file(row) for row in cursor.fetchall()]
        except Exception as exc:
            logger.error("Erro ao buscar por sessão: %s", exc, exc_info=True)
            raise

    def find_all(
        self,
        limit: int = 500,
        offset: int = 0,
        library_folder: Optional[str] = None,
        library_season: Optional[str] = None,
        order_by: str = "date",
        descending: bool = True,
    ) -> List[MediaFile]:
        """Encontrar arquivos com filtro de pasta, temporada e ordenação."""
        try:
            use_natural_sort = order_by in {"name", "name_natural"}
            order_clause = "ORDER BY import_date DESC" if use_natural_sort else self._order_clause(order_by, descending)

            where_clauses = []
            params: list[Any] = []

            if library_folder and library_folder != "Todas":
                where_clauses.append("library_folder = ?")
                params.append(library_folder)

            if library_season and library_season != "Todas":
                where_clauses.append("COALESCE(library_season, 'Sem temporada') = ?")
                params.append(library_season)

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            cursor = self.db.execute(
                f"SELECT * FROM media_files {where_sql} {order_clause} LIMIT ? OFFSET ?",
                tuple(params + [limit, offset]),
            )
            items = [self._row_to_media_file(row) for row in cursor.fetchall()]

            if use_natural_sort:
                items.sort(
                    key=lambda media: self._natural_sort_key(media.file_info.file_name),
                    reverse=descending,
                )

            return items
        except Exception as exc:
            logger.error("Erro ao listar todos os arquivos: %s", exc, exc_info=True)
            raise

    def _normalize_folder_name(self, folder_name: Optional[str]) -> str:
        """Normalizar nome da pasta interna."""
        name = (folder_name or "Sem pasta").strip()
        return name or "Sem pasta"

    def _normalize_season_name(self, season_name: Optional[str]) -> str:
        """Normalizar nome da temporada interna."""
        name = (season_name or "Sem temporada").strip()
        return name or "Sem temporada"

    def _natural_sort_key(self, text: str) -> list[Any]:
        """Chave de ordenação natural: Ep 2 vem antes de Ep 10."""
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text or "")]

    def get_library_folders(self) -> List[str]:
        """Listar pastas internas da biblioteca."""
        try:
            self.create_library_folder("Sem pasta")
            cursor = self.db.execute(
                "SELECT name FROM media_folders ORDER BY CASE WHEN name = 'Sem pasta' THEN 0 ELSE 1 END, name COLLATE NOCASE"
            )
            return [row[0] for row in cursor.fetchall()]
        except Exception as exc:
            logger.error("Erro ao listar pastas da biblioteca: %s", exc, exc_info=True)
            raise

    def create_library_folder(self, folder_name: str) -> str:
        """Criar pasta interna da biblioteca."""
        name = self._normalize_folder_name(folder_name)
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO media_folders (name) VALUES (?)",
                (name,),
            )
            self.db.commit()
            return name
        except Exception as exc:
            logger.error("Erro ao criar pasta da biblioteca: %s", exc, exc_info=True)
            raise

    def get_library_seasons(self, folder_name: Optional[str] = None) -> List[str]:
        """Listar temporadas internas, opcionalmente por pasta."""
        folder = self._normalize_folder_name(folder_name) if folder_name and folder_name != "Todas" else None
        try:
            if folder:
                self.create_library_season(folder, "Sem temporada")
                cursor = self.db.execute(
                    """SELECT name FROM media_seasons
                       WHERE folder_name = ?
                       ORDER BY CASE WHEN name = 'Sem temporada' THEN 0 ELSE 1 END, name COLLATE NOCASE""",
                    (folder,),
                )
            else:
                cursor = self.db.execute(
                    """SELECT DISTINCT name FROM media_seasons
                       ORDER BY CASE WHEN name = 'Sem temporada' THEN 0 ELSE 1 END, name COLLATE NOCASE"""
                )
            seasons = [row[0] for row in cursor.fetchall()]
            return seasons or ["Sem temporada"]
        except Exception as exc:
            logger.error("Erro ao listar temporadas da biblioteca: %s", exc, exc_info=True)
            raise

    def create_library_season(self, folder_name: str, season_name: str) -> str:
        """Criar temporada dentro de uma pasta interna."""
        folder = self.create_library_folder(folder_name)
        season = self._normalize_season_name(season_name)
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO media_seasons (folder_name, name) VALUES (?, ?)",
                (folder, season),
            )
            self.db.commit()
            return season
        except Exception as exc:
            logger.error("Erro ao criar temporada da biblioteca: %s", exc, exc_info=True)
            raise

    def count_media_in_folder(self, folder_name: str) -> int:
        """Contar quantas mídias existem em uma pasta interna."""
        folder = self._normalize_folder_name(folder_name)
        cursor = self.db.execute(
            "SELECT COUNT(*) FROM media_files WHERE library_folder = ?",
            (folder,),
        )
        return int(cursor.fetchone()[0] or 0)

    def count_media_in_season(self, folder_name: str, season_name: str) -> int:
        """Contar quantas mídias existem em uma temporada de uma pasta."""
        folder = self._normalize_folder_name(folder_name)
        season = self._normalize_season_name(season_name)
        cursor = self.db.execute(
            """SELECT COUNT(*) FROM media_files
               WHERE library_folder = ?
                 AND COALESCE(library_season, 'Sem temporada') = ?""",
            (folder, season),
        )
        return int(cursor.fetchone()[0] or 0)

    def delete_library_folder(self, folder_name: str, delete_media: bool = True) -> int:
        """Excluir uma pasta interna e, opcionalmente, todas as mídias nela.

        Não apaga os arquivos originais do computador. Remove apenas os registros
        da biblioteca TEDVHS Studio.
        """
        folder = self._normalize_folder_name(folder_name)
        if folder == "Sem pasta":
            raise ValueError("A pasta padrão 'Sem pasta' não pode ser excluída.")

        media_count = self.count_media_in_folder(folder)
        if media_count and not delete_media:
            raise ValueError("A pasta contém arquivos e não pode ser excluída sem remover as mídias.")

        try:
            if delete_media:
                self.db.execute(
                    "DELETE FROM media_files WHERE library_folder = ?",
                    (folder,),
                )
            self.db.execute(
                "DELETE FROM media_seasons WHERE folder_name = ?",
                (folder,),
            )
            cursor = self.db.execute(
                "DELETE FROM media_folders WHERE name = ?",
                (folder,),
            )
            self.db.commit()
            return int(media_count if delete_media else cursor.rowcount)
        except Exception as exc:
            logger.error("Erro ao excluir pasta da biblioteca: %s", exc, exc_info=True)
            raise

    def delete_library_season(
        self,
        folder_name: str,
        season_name: str,
        delete_media: bool = True,
    ) -> int:
        """Excluir uma temporada interna e, opcionalmente, todas as mídias nela.

        Não apaga os arquivos originais do computador. Remove apenas os registros
        da biblioteca TEDVHS Studio.
        """
        folder = self._normalize_folder_name(folder_name)
        season = self._normalize_season_name(season_name)
        if season == "Sem temporada":
            raise ValueError("A temporada padrão 'Sem temporada' não pode ser excluída.")

        media_count = self.count_media_in_season(folder, season)
        if media_count and not delete_media:
            raise ValueError("A temporada contém arquivos e não pode ser excluída sem remover as mídias.")

        try:
            if delete_media:
                self.db.execute(
                    """DELETE FROM media_files
                       WHERE library_folder = ?
                         AND COALESCE(library_season, 'Sem temporada') = ?""",
                    (folder, season),
                )
            cursor = self.db.execute(
                "DELETE FROM media_seasons WHERE folder_name = ? AND name = ?",
                (folder, season),
            )
            self.db.commit()
            return int(media_count if delete_media else cursor.rowcount)
        except Exception as exc:
            logger.error("Erro ao excluir temporada da biblioteca: %s", exc, exc_info=True)
            raise

    def _media_id_value(self, media_id: Any) -> int:
        """Extrair valor inteiro de MediaId ou ID bruto."""
        return int(media_id.value if hasattr(media_id, "value") else media_id)

    def find_hash_conflict_in_location(
        self,
        file_hash: FileHash,
        library_folder: str,
        library_season: str,
        exclude_media_id: Optional[Any] = None,
    ) -> Optional[MediaFile]:
        """Encontrar mídia com mesmo hash no destino, ignorando o próprio arquivo."""
        folder = self._normalize_folder_name(library_folder)
        season = self._normalize_season_name(library_season)
        params: list[Any] = [str(file_hash), folder, season]
        exclude_sql = ""
        if exclude_media_id is not None:
            exclude_sql = " AND id <> ?"
            params.append(self._media_id_value(exclude_media_id))

        cursor = self.db.execute(
            """SELECT * FROM media_files
               WHERE file_hash = ?
                 AND library_folder = ?
                 AND COALESCE(library_season, 'Sem temporada') = ?
                 AND COALESCE(is_duplicate, 0) = 0"""
            + exclude_sql
            + " ORDER BY import_date ASC LIMIT 1",
            tuple(params),
        )
        row = cursor.fetchone()
        return self._row_to_media_file(row) if row else None

    def find_name_conflict_in_location(
        self,
        file_name: str,
        library_folder: str,
        library_season: str,
        exclude_media_id: Optional[Any] = None,
    ) -> Optional[MediaFile]:
        """Encontrar mídia com mesmo nome no destino, ignorando o próprio arquivo."""
        folder = self._normalize_folder_name(library_folder)
        season = self._normalize_season_name(library_season)
        params: list[Any] = [file_name, folder, season]
        exclude_sql = ""
        if exclude_media_id is not None:
            exclude_sql = " AND id <> ?"
            params.append(self._media_id_value(exclude_media_id))

        cursor = self.db.execute(
            """SELECT * FROM media_files
               WHERE file_name = ?
                 AND library_folder = ?
                 AND COALESCE(library_season, 'Sem temporada') = ?"""
            + exclude_sql
            + " ORDER BY import_date ASC LIMIT 1",
            tuple(params),
        )
        row = cursor.fetchone()
        return self._row_to_media_file(row) if row else None

    def generate_unique_file_name(
        self,
        file_name: str,
        library_folder: str,
        library_season: str,
        exclude_media_id: Optional[Any] = None,
    ) -> str:
        """Gerar nome visual único no destino, no estilo Windows: Nome (1).ext."""
        folder = self._normalize_folder_name(library_folder)
        season = self._normalize_season_name(library_season)
        path = Path(file_name)
        stem = path.stem or file_name
        suffix = path.suffix

        candidate = file_name
        counter = 1
        while self.find_name_conflict_in_location(candidate, folder, season, exclude_media_id):
            candidate = f"{stem} ({counter}){suffix}"
            counter += 1
        return candidate

    def update_media_file_name(self, media_id: Any, new_file_name: str) -> bool:
        """Alterar apenas o nome exibido na biblioteca, sem renomear o arquivo original no disco."""
        media_id_value = self._media_id_value(media_id)
        clean_name = (new_file_name or "").strip()
        if not clean_name:
            raise ValueError("Nome do arquivo não pode ficar vazio")

        try:
            cursor = self.db.execute(
                "UPDATE media_files SET file_name = ? WHERE id = ?",
                (clean_name, media_id_value),
            )
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Erro ao renomear mídia na biblioteca: %s", exc, exc_info=True)
            raise

    def set_media_folder(self, media_id: Any, folder_name: str) -> bool:
        """Mover uma mídia para uma pasta interna, mantendo a temporada atual."""
        media = self.find_by_id(media_id)
        current_season = "Sem temporada"
        if media is not None:
            current_season = str(media.custom_metadata.get("library_season") or "Sem temporada")
        return self.set_media_folder_season(media_id, folder_name, current_season)

    def set_media_folder_season(
        self,
        media_id: Any,
        folder_name: str,
        season_name: str,
        new_file_name: Optional[str] = None,
        allow_same_hash: bool = False,
    ) -> bool:
        """Mover uma mídia para pasta + temporada internas.

        Por padrão, bloqueia movimentação quando o mesmo hash já existe no destino.
        Isso evita duas entradas idênticas na mesma Pasta/Temporada.
        """
        media_id_value = self._media_id_value(media_id)
        folder = self.create_library_folder(folder_name)
        season = self.create_library_season(folder, season_name)
        media = self.find_by_id(media_id_value)
        if media is None:
            return False

        hash_conflict = self.find_hash_conflict_in_location(
            media.hash_info.file_hash,
            folder,
            season,
            exclude_media_id=media_id_value,
        )
        if hash_conflict and not allow_same_hash:
            raise ValueError(
                "Este mesmo vídeo já existe na pasta/temporada de destino. "
                "A movimentação foi negada para evitar duplicidade."
            )

        final_name = (new_file_name or media.file_info.file_name).strip() or media.file_info.file_name
        try:
            cursor = self.db.execute(
                """UPDATE media_files
                   SET library_folder = ?, library_season = ?, file_name = ?
                   WHERE id = ?""",
                (folder, season, final_name, media_id_value),
            )
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Erro ao mover mídia para pasta/temporada: %s", exc, exc_info=True)
            raise

    def set_many_media_folder(self, media_ids: List[Any], folder_name: str) -> int:
        """Mover várias mídias para uma pasta interna."""
        moved = 0
        for media_id in media_ids:
            if self.set_media_folder(media_id, folder_name):
                moved += 1
        return moved

    def set_many_media_folder_season(self, media_ids: List[Any], folder_name: str, season_name: str) -> int:
        """Mover várias mídias para pasta + temporada internas."""
        moved = 0
        for media_id in media_ids:
            if self.set_media_folder_season(media_id, folder_name, season_name):
                moved += 1
        return moved

    def _order_clause(self, order_by: str = "import_date", descending: bool = True) -> str:
        """Gerar ORDER BY seguro para a biblioteca."""
        allowed = {
            "name": "file_name COLLATE NOCASE",
            "size": "file_size_bytes",
            "date": "import_date",
            "duration": "duration_seconds",
            "resolution": "width * height",
            "status": "status COLLATE NOCASE",
            "folder": "library_folder COLLATE NOCASE",
            "season": "library_season COLLATE NOCASE",
            "import_date": "import_date",
        }
        column = allowed.get(order_by, "import_date")
        direction = "DESC" if descending else "ASC"
        return f"ORDER BY {column} {direction}, file_name COLLATE NOCASE ASC"

    def find_by_id(self, media_id: Any) -> Optional[MediaFile]:
        try:
            media_id_value = self._media_id_value(media_id)
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE id = ?",
                (media_id_value,),
            )
            row = cursor.fetchone()
            return self._row_to_media_file(row) if row else None
        except Exception as exc:
            logger.error("Erro ao buscar por ID: %s", exc, exc_info=True)
            raise

    def delete_media_file(self, media_id: Any) -> bool:
        """Excluir uma mídia da biblioteca pelo ID."""
        try:
            media_id_value = media_id.value if hasattr(media_id, "value") else int(media_id)
            cursor = self.db.execute("DELETE FROM media_files WHERE id = ?", (media_id_value,))
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Erro ao deletar arquivo: %s", exc, exc_info=True)
            raise

    def clear_scenes_for_media(self, media_id: Any) -> int:
        """Remover cenas detectadas de uma mídia."""
        media_id_value = self._media_id_value(media_id)
        cursor = self.db.execute("DELETE FROM media_scenes WHERE media_id = ?", (media_id_value,))
        self.db.commit()
        return int(cursor.rowcount)

    def save_detected_scenes(self, media_id: Any, scenes: List[Dict[str, Any]], threshold: float = 0.35) -> int:
        """Salvar cenas detectadas, substituindo detecções anteriores da mídia."""
        media_id_value = self._media_id_value(media_id)
        self.clear_scenes_for_media(media_id_value)

        for index, scene in enumerate(scenes, start=1):
            self.db.execute(
                """INSERT INTO media_scenes (
                    media_id, scene_number, sort_order, start_seconds, end_seconds,
                    duration_seconds, custom_start_seconds, custom_end_seconds,
                    custom_duration_seconds, detection_threshold, status,
                    description, tags, scene_type, thumbnail_path,
                    analysis_frames_json, ai_status, is_favorite, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    media_id_value,
                    int(scene.get("scene_number") or index),
                    int(scene.get("sort_order") or index),
                    float(scene.get("start_seconds") or 0.0),
                    float(scene.get("end_seconds") or 0.0),
                    float(scene.get("duration_seconds") or 0.0),
                    scene.get("custom_start_seconds"),
                    scene.get("custom_end_seconds"),
                    scene.get("custom_duration_seconds"),
                    float(threshold),
                    str(scene.get("status") or "detected"),
                    scene.get("description"),
                    scene.get("tags"),
                    scene.get("scene_type") or "Geral",
                    scene.get("thumbnail_path"),
                    scene.get("analysis_frames_json"),
                    scene.get("ai_status") or "pending",
                    1 if scene.get("is_favorite") else 0,
                    scene.get("notes"),
                    datetime.utcnow().isoformat(),
                ),
            )

        self.db.execute(
            "UPDATE media_files SET status = ? WHERE id = ?",
            (ProcessingStatus.SCENES_COMPLETED.value, media_id_value),
        )
        self.db.commit()
        return len(scenes)

    def get_scenes_by_media(self, media_id: Any) -> List[Dict[str, Any]]:
        """Listar cenas detectadas de uma mídia."""
        media_id_value = self._media_id_value(media_id)
        cursor = self.db.execute(
            """SELECT id, media_id, scene_number, sort_order, start_seconds, end_seconds,
                      duration_seconds, custom_start_seconds, custom_end_seconds,
                      custom_duration_seconds, is_merged, source_scene_ids,
                      segments_json, display_name, detection_threshold, status,
                      description, tags, scene_type, thumbnail_path,
                      analysis_frames_json, ai_status, is_favorite,
                      notes, created_at, updated_at
               FROM media_scenes
               WHERE media_id = ?
               ORDER BY COALESCE(sort_order, scene_number) ASC, scene_number ASC, id ASC""",
            (media_id_value,),
        )
        columns = [
            "id", "media_id", "scene_number", "sort_order", "start_seconds", "end_seconds",
            "duration_seconds", "custom_start_seconds", "custom_end_seconds",
            "custom_duration_seconds", "is_merged", "source_scene_ids",
            "segments_json", "display_name", "detection_threshold", "status", "description",
            "tags", "scene_type", "thumbnail_path", "analysis_frames_json",
            "ai_status", "is_favorite", "notes", "created_at", "updated_at",
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


    def reorder_scenes(self, media_id: Any, ordered_scene_ids: List[Any]) -> int:
        """Persistir a ordem manual completa das cenas/clipes de uma mídia.

        A lista recebida precisa conter exatamente os IDs atualmente salvos para
        o episódio. Isso evita sobrescrever uma lista desatualizada ou perder itens.
        """
        media_id_value = self._media_id_value(media_id)
        clean_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in ordered_scene_ids:
            try:
                scene_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if scene_id not in seen:
                seen.add(scene_id)
                clean_ids.append(scene_id)

        current_rows = self.db.execute(
            "SELECT id FROM media_scenes WHERE media_id = ?",
            (media_id_value,),
        ).fetchall()
        current_ids = {int(row[0]) for row in current_rows}
        if not current_ids:
            return 0
        if set(clean_ids) != current_ids or len(clean_ids) != len(current_ids):
            raise ValueError(
                "A lista de cenas mudou enquanto a ordem era editada. Recarregue o episódio e tente novamente."
            )

        case_parts: list[str] = []
        params: list[Any] = []
        for position, scene_id in enumerate(clean_ids, start=1):
            case_parts.append("WHEN ? THEN ?")
            params.extend((scene_id, position))

        placeholders = ", ".join("?" for _ in clean_ids)
        params.extend((datetime.utcnow().isoformat(), media_id_value, *clean_ids))
        cursor = self.db.execute(
            f"""UPDATE media_scenes
                SET sort_order = CASE id {' '.join(case_parts)} END,
                    updated_at = ?
                WHERE media_id = ? AND id IN ({placeholders})""",
            tuple(params),
        )
        self.db.commit()
        return int(cursor.rowcount)


    def create_merged_scene(self, media_id: Any, source_scenes: List[Dict[str, Any]], display_name: Optional[str] = None) -> Dict[str, Any]:
        """Criar um clipe rascunho juntando cenas/trechos selecionados.

        O vídeo original não é alterado e nenhum MP4 é exportado aqui. O registro
        salvo em `media_scenes` representa um item composto, com `segments_json`
        guardando os trechos que deverão ser tocados/exportados em sequência.
        """
        media_id_value = self._media_id_value(media_id)
        clean_scenes = [scene for scene in source_scenes if scene]
        if len(clean_scenes) < 2:
            raise ValueError("Selecione duas ou mais cenas para juntar.")

        def effective_bounds(scene: Dict[str, Any]) -> tuple[float, float]:
            start = scene.get("custom_start_seconds")
            end = scene.get("custom_end_seconds")
            if start is None:
                start = scene.get("start_seconds") or 0.0
            if end is None:
                end = scene.get("end_seconds") or start
            start = float(start or 0.0)
            end = float(end or start)
            if end <= start:
                end = start + 0.25
            return start, end

        def segments_for_scene(
            scene: Dict[str, Any],
        ) -> list[Dict[str, Any]]:
            """Expandir cenas e clipes juntados nos seus cortes reais."""
            raw_segments = scene.get("segments_json")

            if raw_segments:
                try:
                    parsed_segments = (
                        json.loads(raw_segments)
                        if isinstance(raw_segments, str)
                        else raw_segments
                    )
                except (TypeError, ValueError):
                    parsed_segments = None

                if isinstance(parsed_segments, list):
                    expanded: list[Dict[str, Any]] = []

                    for raw_segment in parsed_segments:
                        if not isinstance(raw_segment, dict):
                            continue

                        try:
                            segment_start = float(
                                raw_segment.get("start_seconds") or 0.0
                            )
                            segment_end = float(
                                raw_segment.get("end_seconds")
                                or segment_start
                            )
                        except (TypeError, ValueError):
                            continue

                        if segment_end <= segment_start:
                            continue

                        expanded.append({
                            "scene_id": (
                                raw_segment.get("scene_id")
                                or scene.get("id")
                            ),
                            "scene_number": (
                                raw_segment.get("scene_number")
                                or scene.get("scene_number")
                            ),
                            "start_seconds": segment_start,
                            "end_seconds": segment_end,
                            "duration_seconds": max(
                                segment_end - segment_start,
                                0.0,
                            ),
                        })

                    if expanded:
                        return expanded

            scene_start, scene_end = effective_bounds(scene)

            return [{
                "scene_id": scene.get("id"),
                "scene_number": scene.get("scene_number"),
                "start_seconds": scene_start,
                "end_seconds": scene_end,
                "duration_seconds": max(
                    scene_end - scene_start,
                    0.0,
                ),
            }]

        # Preservar a ordem manual e expandir clipes ja juntados.
        segments: list[Dict[str, Any]] = []

        for scene in clean_scenes:
            segments.extend(segments_for_scene(scene))

        total_duration = sum(
            float(segment["duration_seconds"])
            for segment in segments
        )

        start_seconds = min(float(segment["start_seconds"]) for segment in segments)
        end_seconds = max(float(segment["end_seconds"]) for segment in segments)
        source_ids = [scene.get("id") for scene in clean_scenes]

        row = self.db.execute(
            """SELECT COALESCE(MAX(scene_number), 0) + 1,
                      COALESCE(MAX(COALESCE(sort_order, scene_number)), 0) + 1
               FROM media_scenes WHERE media_id = ?""",
            (media_id_value,),
        ).fetchone()
        scene_number = int(row[0] if row else 1)
        sort_order = int(row[1] if row else scene_number)
        display_name = (display_name or f"Clipe {scene_number:03d} (juntado)").strip() or f"Clipe {scene_number:03d} (juntado)"

        tag_values: list[str] = []
        for scene in clean_scenes:
            for raw_tag in str(scene.get("tags") or "").replace(";", ",").split(","):
                tag = raw_tag.strip()
                if tag and tag.lower() not in {existing.lower() for existing in tag_values}:
                    tag_values.append(tag)

        descriptions = []
        for scene in clean_scenes:
            text = str(scene.get("description") or "").strip()
            if text:
                descriptions.append(f"Cena {int(scene.get('scene_number') or 0):03d}: {text}")
        description = "\n".join(descriptions) or f"Clipe juntado com {len(clean_scenes)} cenas selecionadas."
        thumbnail_path = clean_scenes[0].get("thumbnail_path")

        self.db.execute(
            """INSERT INTO media_scenes (
                media_id, scene_number, sort_order, start_seconds, end_seconds,
                duration_seconds, custom_start_seconds, custom_end_seconds,
                custom_duration_seconds, is_merged, source_scene_ids,
                segments_json, display_name, detection_threshold, status,
                description, tags, scene_type, thumbnail_path,
                analysis_frames_json, ai_status, is_favorite, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id_value,
                scene_number,
                sort_order,
                start_seconds,
                end_seconds,
                total_duration,
                None,
                None,
                total_duration,
                1,
                json.dumps(source_ids, ensure_ascii=False),
                json.dumps(segments, ensure_ascii=False),
                display_name,
                0.0,
                "merged_draft",
                description,
                ", ".join(tag_values),
                "Clipe juntado",
                thumbnail_path,
                None,
                "manual_edit",
                0,
                f"Clipe rascunho criado a partir de {len(clean_scenes)} cena(s).",
                datetime.utcnow().isoformat(),
            ),
        )
        self.db.commit()

        scenes = self.get_scenes_by_media(media_id_value)
        for scene in scenes:
            if int(scene.get("scene_number") or 0) == scene_number:
                return scene
        raise RuntimeError("Clipe juntado foi salvo, mas não pôde ser recarregado.")

    def create_cut_scene(
        self,
        media_id: Any,
        source_scene: Dict[str, Any],
        start_seconds: float,
        end_seconds: float,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Criar uma nova marcação de corte sem alterar a cena original.

        O arquivo final ainda não é gerado aqui. Este método apenas salva um
        novo item em `media_scenes`, com início/fim próprios, para que a
        exportação em MP4 seja feita depois na Sprint 3.2.
        """
        media_id_value = self._media_id_value(media_id)
        start = float(start_seconds or 0.0)
        end = float(end_seconds or start)
        if end <= start:
            raise ValueError("O fim do corte precisa ser maior que o início.")

        source_id = source_scene.get("id")
        source_name = source_scene.get("display_name") or f"Cena {int(source_scene.get('scene_number') or 0):03d}"

        row = self.db.execute(
            """SELECT COALESCE(MAX(scene_number), 0) + 1,
                      COALESCE(MAX(COALESCE(sort_order, scene_number)), 0) + 1
               FROM media_scenes WHERE media_id = ?""",
            (media_id_value,),
        ).fetchone()
        scene_number = int(row[0] if row else 1)
        sort_order = int(row[1] if row else scene_number)
        display_name = (display_name or f"{source_name} - corte").strip() or f"{source_name} - corte"
        duration = max(end - start, 0.0)

        description = str(source_scene.get("description") or "").strip()
        if description:
            description = f"Recorte de {source_name}: {description}"
        else:
            description = f"Recorte criado a partir de {source_name}."

        segment = {
            "scene_id": source_id,
            "scene_number": source_scene.get("scene_number"),
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": duration,
        }

        self.db.execute(
            """INSERT INTO media_scenes (
                media_id, scene_number, sort_order, start_seconds, end_seconds,
                duration_seconds, custom_start_seconds, custom_end_seconds,
                custom_duration_seconds, is_merged, source_scene_ids,
                segments_json, display_name, detection_threshold, status,
                description, tags, scene_type, thumbnail_path,
                analysis_frames_json, ai_status, is_favorite, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id_value,
                scene_number,
                sort_order,
                start,
                end,
                duration,
                None,
                None,
                duration,
                0,
                json.dumps([source_id], ensure_ascii=False),
                json.dumps([segment], ensure_ascii=False),
                display_name,
                float(source_scene.get("detection_threshold") or 0.0),
                "cut_draft",
                description,
                source_scene.get("tags"),
                source_scene.get("scene_type") or "Geral",
                source_scene.get("thumbnail_path"),
                source_scene.get("analysis_frames_json"),
                "manual_edit",
                0,
                f"Marcação de corte criada a partir de {source_name}.",
                datetime.utcnow().isoformat(),
            ),
        )
        self.db.commit()

        scenes = self.get_scenes_by_media(media_id_value)
        for scene in scenes:
            if int(scene.get("scene_number") or 0) == scene_number:
                return scene
        raise RuntimeError("Marcação de corte foi salva, mas não pôde ser recarregada.")


    def get_scene_count(self, media_id: Any) -> int:
        """Contar cenas detectadas de uma mídia."""
        media_id_value = self._media_id_value(media_id)
        row = self.db.execute(
            "SELECT COUNT(*) FROM media_scenes WHERE media_id = ?",
            (media_id_value,),
        ).fetchone()
        return int(row[0] if row else 0)

    def delete_scenes(self, scene_ids: List[Any]) -> int:
        """Excluir uma ou mais cenas em uma única transação."""
        normalized_ids: List[int] = []
        seen: set[int] = set()
        for scene_id in scene_ids or []:
            scene_id_value = scene_id.value if hasattr(scene_id, "value") else int(scene_id)
            if scene_id_value not in seen:
                seen.add(scene_id_value)
                normalized_ids.append(scene_id_value)

        if not normalized_ids:
            return 0

        placeholders = ", ".join("?" for _ in normalized_ids)
        cursor = self.db.execute(
            f"DELETE FROM media_scenes WHERE id IN ({placeholders})",
            tuple(normalized_ids),
        )
        self.db.commit()
        return max(int(cursor.rowcount), 0)

    def delete_scene(self, scene_id: Any) -> bool:
        """Excluir uma cena detectada."""
        return self.delete_scenes([scene_id]) > 0


    def update_scene_visual_catalog(
        self,
        scene_id: Any,
        description: Optional[str] = None,
        tags: Optional[str] = None,
        scene_type: Optional[str] = None,
        thumbnail_path: Optional[str] = None,
        analysis_frames_json: Optional[str] = None,
        ai_status: str = "auto_local",
    ) -> bool:
        """Atualizar miniatura e catálogo automático de uma cena.

        Usado pela catalogação em segundo plano para evitar que a detecção
        de cenas fique pesada demais. Não altera cortes manuais nem clipes
        rascunho.
        """
        scene_id_value = scene_id.value if hasattr(scene_id, "value") else int(scene_id)
        cursor = self.db.execute(
            """UPDATE media_scenes
               SET description = COALESCE(?, description),
                   tags = COALESCE(?, tags),
                   scene_type = COALESCE(?, scene_type),
                   thumbnail_path = COALESCE(?, thumbnail_path),
                   analysis_frames_json = COALESCE(?, analysis_frames_json),
                   ai_status = ?,
                   updated_at = ?
               WHERE id = ?""",
            (
                description,
                tags,
                scene_type,
                thumbnail_path,
                analysis_frames_json,
                ai_status or "auto_local",
                datetime.utcnow().isoformat(),
                scene_id_value,
            ),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def update_scene_catalog(
        self,
        scene_id: Any,
        description: str,
        tags: str,
        scene_type: str,
        is_favorite: bool = False,
        notes: Optional[str] = None,
    ) -> bool:
        """Atualizar descrição, tags, tipo e destaque de uma cena."""
        scene_id_value = scene_id.value if hasattr(scene_id, "value") else int(scene_id)
        cursor = self.db.execute(
            """UPDATE media_scenes
               SET description = ?, tags = ?, scene_type = ?, is_favorite = ?,
                   notes = COALESCE(?, notes), ai_status = ?, updated_at = ?
               WHERE id = ?""",
            (
                (description or "").strip(),
                (tags or "").strip(),
                (scene_type or "Geral").strip() or "Geral",
                1 if is_favorite else 0,
                notes,
                "manual_edit",
                datetime.utcnow().isoformat(),
                scene_id_value,
            ),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def update_scene_trim(self, scene_id: Any, start_seconds: Optional[float], end_seconds: Optional[float]) -> bool:
        """Salvar ajuste manual de início/fim de uma cena.

        Quando start/end forem None, o corte customizado é resetado.
        O vídeo original não é alterado; esses valores são usados apenas para
        preview e futura criação/exportação do clipe.
        """
        scene_id_value = scene_id.value if hasattr(scene_id, "value") else int(scene_id)
        if start_seconds is None or end_seconds is None:
            cursor = self.db.execute(
                """UPDATE media_scenes
                   SET custom_start_seconds = NULL,
                       custom_end_seconds = NULL,
                       custom_duration_seconds = NULL,
                       updated_at = ?
                   WHERE id = ?""",
                (datetime.utcnow().isoformat(), scene_id_value),
            )
            self.db.commit()
            return cursor.rowcount > 0

        start = float(start_seconds)
        end = float(end_seconds)
        if end <= start:
            raise ValueError("O fim do corte precisa ser maior que o início.")

        cursor = self.db.execute(
            """UPDATE media_scenes
               SET custom_start_seconds = ?,
                   custom_end_seconds = ?,
                   custom_duration_seconds = ?,
                   updated_at = ?
               WHERE id = ?""",
            (start, end, end - start, datetime.utcnow().isoformat(), scene_id_value),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def update_scene_favorite(self, scene_id: Any, is_favorite: bool) -> bool:
        """Marcar/desmarcar cena como destaque."""
        scene_id_value = scene_id.value if hasattr(scene_id, "value") else int(scene_id)
        cursor = self.db.execute(
            "UPDATE media_scenes SET is_favorite = ?, updated_at = ? WHERE id = ?",
            (1 if is_favorite else 0, datetime.utcnow().isoformat(), scene_id_value),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def save_exported_clip(
        self,
        media_id: Any,
        scene_id: Any,
        clip_name: str,
        output_path: str,
        metadata_path: Optional[str],
        library_folder: str,
        library_season: str,
        episode_name: str,
        duration_seconds: float,
        segments_json: str,
        description: str = "",
        tags: str = "",
        scene_type: str = "",
        export_mode: str = "precise_ffmpeg_reencode",
    ) -> int:
        """Registrar um clipe exportado em MP4."""
        media_id_value = self._media_id_value(media_id)
        scene_id_value = None
        if scene_id is not None:
            scene_id_value = int(scene_id.value if hasattr(scene_id, "value") else scene_id)

        cursor = self.db.execute(
            """INSERT INTO exported_clips (
                media_id, scene_id, clip_name, output_path, metadata_path,
                library_folder, library_season, episode_name, duration_seconds,
                segments_json, description, tags, scene_type, export_mode,
                status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                media_id_value,
                scene_id_value,
                (clip_name or "clipe").strip(),
                output_path,
                metadata_path,
                self._normalize_folder_name(library_folder),
                self._normalize_season_name(library_season),
                (episode_name or "").strip(),
                float(duration_seconds or 0.0),
                segments_json or "[]",
                description or "",
                tags or "",
                scene_type or "",
                export_mode or "precise_ffmpeg_reencode",
                "exported",
                datetime.utcnow().isoformat(),
            ),
        )
        self.db.commit()
        return int(cursor.lastrowid)

    def get_exported_clips_by_media(self, media_id: Any) -> List[Dict[str, Any]]:
        """Listar clipes exportados de uma mídia."""
        media_id_value = self._media_id_value(media_id)
        cursor = self.db.execute(
            """SELECT id, media_id, scene_id, clip_name, output_path, metadata_path,
                      library_folder, library_season, episode_name, duration_seconds,
                      segments_json, description, tags, scene_type, export_mode, status, created_at
               FROM exported_clips
               WHERE media_id = ?
               ORDER BY created_at DESC""",
            (media_id_value,),
        )
        columns = [
            "id", "media_id", "scene_id", "clip_name", "output_path", "metadata_path",
            "library_folder", "library_season", "episode_name", "duration_seconds",
            "segments_json", "description", "tags", "scene_type", "export_mode", "status", "created_at",
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


    def get_exported_clips_all(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Listar todos os clipes exportados em MP4."""
        cursor = self.db.execute(
            """SELECT id, media_id, scene_id, clip_name, output_path, metadata_path,
                      library_folder, library_season, episode_name, duration_seconds,
                      segments_json, description, tags, scene_type, export_mode, status, created_at, updated_at
               FROM exported_clips
               ORDER BY created_at DESC
               LIMIT ?""",
            (int(limit or 1000),),
        )
        columns = [
            "id", "media_id", "scene_id", "clip_name", "output_path", "metadata_path",
            "library_folder", "library_season", "episode_name", "duration_seconds",
            "segments_json", "description", "tags", "scene_type", "export_mode", "status", "created_at", "updated_at",
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def update_exported_clip(
        self,
        clip_id: int,
        clip_name: Optional[str] = None,
        output_path: Optional[str] = None,
        metadata_path: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[str] = None,
        scene_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> bool:
        """Atualizar dados editáveis de um clipe exportado."""
        fields = []
        values: List[Any] = []
        mapping = {
            "clip_name": clip_name,
            "output_path": output_path,
            "metadata_path": metadata_path,
            "description": description,
            "tags": tags,
            "scene_type": scene_type,
            "status": status,
        }
        for column, value in mapping.items():
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        fields.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(int(clip_id))
        cursor = self.db.execute(
            f"UPDATE exported_clips SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        self.db.commit()
        return cursor.rowcount > 0

    def delete_exported_clip(self, clip_id: int) -> bool:
        """Remover o registro de um clipe exportado do banco."""
        cursor = self.db.execute("DELETE FROM exported_clips WHERE id = ?", (int(clip_id),))
        self.db.commit()
        return cursor.rowcount > 0

    def update_status(self, media_id: MediaId, status: ProcessingStatus) -> bool:
        try:
            cursor = self.db.execute(
                "UPDATE media_files SET status = ? WHERE id = ?",
                (status.value, media_id.value),
            )
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Erro ao atualizar status: %s", exc, exc_info=True)
            raise

    def update_session_stats(self, session_id: str, stats: Dict[str, Any]) -> bool:
        """Atualizar estatísticas da sessão.

        Aceita tanto nomes internos do pipeline (`files_found`) quanto nomes do banco
        (`total_files_found`).
        """
        try:
            status = stats.get("status", "IN_PROGRESS")
            completed_at = datetime.utcnow().isoformat() if status in {"COMPLETED", "FAILED", "CANCELLED"} else None

            cursor = self.db.execute(
                """UPDATE import_sessions SET
                   total_files_found = ?,
                   total_files_valid = ?,
                   total_files_imported = ?,
                   total_files_duplicate = ?,
                   total_files_failed = ?,
                   total_duration_seconds = ?,
                   total_size_bytes = ?,
                   completed_at = COALESCE(?, completed_at),
                   status = ?
                   WHERE session_id = ?""",
                (
                    stats.get("total_files_found", stats.get("files_found", 0)),
                    stats.get("total_files_valid", stats.get("files_valid", 0)),
                    stats.get("total_files_imported", stats.get("files_imported", 0)),
                    stats.get("total_files_duplicate", stats.get("files_duplicate", 0)),
                    stats.get("total_files_failed", stats.get("files_failed", 0)),
                    stats.get("total_duration_seconds", stats.get("duration_seconds", 0)),
                    stats.get("total_size_bytes", 0),
                    completed_at,
                    status,
                    session_id,
                ),
            )
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Erro ao atualizar sessão: %s", exc, exc_info=True)
            raise

    def get_incomplete_sessions(self) -> List[Dict[str, Any]]:
        try:
            cursor = self.db.execute(
                """SELECT id, session_id, folder_path, started_at,
                          total_files_found, total_files_imported
                   FROM import_sessions
                   WHERE status IN ('IN_PROGRESS', 'PAUSED')
                   ORDER BY started_at DESC"""
            )
            return [
                {
                    "id": row[0],
                    "session_id": row[1],
                    "folder_path": row[2],
                    "started_at": row[3],
                    "total_files_found": row[4],
                    "total_files_imported": row[5],
                }
                for row in cursor.fetchall()
            ]
        except Exception as exc:
            logger.error("Erro ao buscar sessões incompletas: %s", exc, exc_info=True)
            raise

    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        try:
            cursor = self.db.execute(
                """SELECT total_files_found, total_files_valid, total_files_imported,
                          total_files_duplicate, total_files_failed, total_duration_seconds,
                          total_size_bytes, status
                   FROM import_sessions WHERE session_id = ?""",
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "total_files_found": row[0],
                "total_files_valid": row[1],
                "total_files_imported": row[2],
                "total_files_duplicate": row[3],
                "total_files_failed": row[4],
                "total_duration_seconds": row[5],
                "total_size_bytes": row[6],
                "status": row[7],
            }
        except Exception as exc:
            logger.error("Erro ao obter estatísticas: %s", exc, exc_info=True)
            raise

    def get_duplicates(self, session_id: str) -> List[Dict[str, Any]]:
        try:
            cursor = self.db.execute(
                """SELECT file_name, duplicate_of_hash, import_date
                   FROM media_files
                   WHERE import_session_id = ? AND is_duplicate = 1
                   ORDER BY import_date DESC""",
                (session_id,),
            )
            return [
                {
                    "file_name": row[0],
                    "duplicate_of_hash": row[1],
                    "import_date": row[2],
                }
                for row in cursor.fetchall()
            ]
        except Exception as exc:
            logger.error("Erro ao obter duplicatas: %s", exc, exc_info=True)
            raise

    def _parse_status(self, value: Any) -> ProcessingStatus:
        """Converter status salvo no banco para ProcessingStatus com fallback."""
        raw = str(value or "").strip()
        normalized = raw.lower()

        aliases = {
            "pending": ProcessingStatus.METADATA_PENDING,
            "processando": ProcessingStatus.METADATA_PENDING,
            "processing": ProcessingStatus.METADATA_PENDING,
            "completed": ProcessingStatus.READY,
            "complete": ProcessingStatus.READY,
            "concluido": ProcessingStatus.READY,
            "concluído": ProcessingStatus.READY,
            "error": ProcessingStatus.FAILED,
            "erro": ProcessingStatus.FAILED,
            "duplicate": ProcessingStatus.SKIPPED,
            "duplicado": ProcessingStatus.SKIPPED,
            "skipped": ProcessingStatus.SKIPPED,
        }
        if normalized in aliases:
            return aliases[normalized]

        try:
            return ProcessingStatus(normalized)
        except ValueError:
            logger.warning("Status desconhecido no banco: %s. Usando METADATA_EXTRACTED.", raw)
            return ProcessingStatus.METADATA_EXTRACTED

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if not value:
            return datetime.utcnow()
        text = str(value)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.utcnow()

    def _row_to_media_file(self, row: tuple) -> MediaFile:
        values = list(row)
        # Bancos antigos podem não ter as colunas library_folder/library_season.
        library_folder = values[22] if len(values) > 22 else "Sem pasta"
        library_season = values[23] if len(values) > 23 else "Sem temporada"
        (media_id, _session_id, file_path, file_name, file_ext, file_size,
         file_hash, is_dup, dup_hash, duration, fps, width, height, _res_str,
         codec_video, codec_audio, audio_ch, status, import_date, metadata_ver,
         attempts, last_error) = values[:22]

        media = MediaFile(
            id=MediaId(media_id),
            file_info=FileInfo(
                file_path=file_path,
                file_name=file_name,
                file_name_clean=Path(file_name).stem,
                file_extension=file_ext or "",
                file_size=FileSize(file_size or 0),
            ),
            video_info=VideoInfo(
                duration=Duration(duration or 0.0),
                fps=fps or 0.0,
                resolution=Resolution(width, height) if width and height else None,
                codec_video=codec_video or "",
            ),
            audio_info=AudioInfo(
                codec_audio=codec_audio,
                audio_channels=audio_ch or 0,
            ),
            processing_info=ProcessingInfo(
                status=self._parse_status(status),
                import_date=self._parse_datetime(import_date),
                metadata_version=metadata_ver or 0,
                processing_attempts=attempts or 0,
                last_error=last_error,
            ),
            hash_info=HashInfo(
                file_hash=FileHash(file_hash),
                is_duplicate=bool(is_dup),
                duplicate_of_hash=FileHash(dup_hash) if dup_hash else None,
            ),
        )
        media.custom_metadata["library_folder"] = library_folder or "Sem pasta"
        media.custom_metadata["library_season"] = library_season or "Sem temporada"
        return media

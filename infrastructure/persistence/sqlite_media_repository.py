"""Implementação de repository SQLite para Media Library Engine."""

import logging
import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

from core.database.connection import DatabaseConnection
from domain.media.media_file import MediaFile, FileInfo, VideoInfo, AudioInfo, ProcessingInfo, HashInfo
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileHash, MediaId, FileSize, Duration, Resolution


logger = logging.getLogger(__name__)


class SQLiteMediaRepository:
    """Repository para persistência de MediaFile em SQLite.
    
    Implementa operações CRUD e queries otimizadas para Media Library Engine.
    """
    
    def __init__(self, db_connection: DatabaseConnection):
        """Inicializar repository.
        
        Args:
            db_connection: Conexão com banco de dados
        """
        self.db = db_connection
        self._ensure_schema()
        logger.info("SQLiteMediaRepository inicializado")
    
    def _ensure_schema(self) -> None:
        """Garantir que o schema existe no banco de dados."""
        try:
            # Verificar se tabelas existem
            cursor = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='media_files'"
            )
            if cursor.fetchone() is None:
                logger.info("Criando schema de media_files")
                schema_path = Path(__file__).parent / "media_schema.sql"
                if schema_path.exists():
                    with open(schema_path, 'r') as f:
                        sql = f.read()
                    for statement in sql.split(';'):
                        if statement.strip():
                            self.db.execute(statement)
                    self.db.commit()
                    logger.info("Schema criado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao garantir schema: {e}", exc_info=True)
            raise
    
    def create_import_session(self, session_id: str, folder_path: str) -> int:
        """Criar nova sessão de importação.
        
        Args:
            session_id: ID único da sessão
            folder_path: Caminho da pasta a importar
            
        Returns:
            ID da sessão no banco de dados
        """
        try:
            cursor = self.db.execute(
                """INSERT INTO import_sessions (session_id, folder_path, status)
                   VALUES (?, ?, 'IN_PROGRESS')""",
                (session_id, folder_path)
            )
            self.db.commit()
            session_pk = cursor.lastrowid
            logger.info(f"Sessão de importação criada: {session_id} (pk={session_pk})")
            return session_pk
        except Exception as e:
            logger.error(f"Erro ao criar sessão: {e}", exc_info=True)
            raise
    
    def add_media_file(self, media: MediaFile, session_id: str) -> Optional[MediaId]:
        """Adicionar arquivo de mídia ao repositório.
        
        Args:
            media: MediaFile a adicionar
            session_id: ID da sessão de importação
            
        Returns:
            MediaId do arquivo adicionado ou None se já existe
        """
        try:
            # Verificar duplicata
            existing = self.find_by_hash(media.hash_info.file_hash)
            if existing:
                logger.debug(f"Arquivo duplicado detectado: {media.file_info.file_hash}")
                return None
            
            # Inserir novo arquivo
            cursor = self.db.execute(
                """INSERT INTO media_files (
                    import_session_id, file_path, file_name, file_extension,
                    file_size_bytes, file_hash, is_duplicate, duplicate_of_hash,
                    duration_seconds, fps, width, height, resolution,
                    codec_video, codec_audio, audio_channels, status,
                    metadata_version, processing_attempts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    media.file_info.file_path,
                    media.file_info.file_name,
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
                    media.processing_info.processing_attempts
                )
            )
            self.db.commit()
            
            media_id = MediaId(cursor.lastrowid)
            logger.info(f"Arquivo de mídia adicionado: {media.file_info.file_name} (id={media_id})")
            return media_id
            
        except sqlite3.IntegrityError as e:
            logger.warning(f"Arquivo já existe ou viola constraint: {e}")
            return None
        except Exception as e:
            logger.error(f"Erro ao adicionar arquivo: {e}", exc_info=True)
            raise
    
    def find_by_hash(self, file_hash: FileHash) -> Optional[MediaFile]:
        """Encontrar arquivo por hash.
        
        Args:
            file_hash: Hash SHA-256 do arquivo
            
        Returns:
            MediaFile se encontrado, None caso contrário
        """
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE file_hash = ?",
                (str(file_hash),)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_media_file(row)
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar por hash: {e}", exc_info=True)
            raise
    
    def find_by_status(self, status: ProcessingStatus, limit: int = 100) -> List[MediaFile]:
        """Encontrar arquivos por status.
        
        Args:
            status: Status de processamento
            limit: Limite de resultados
            
        Returns:
            Lista de MediaFiles
        """
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE status = ? LIMIT ?",
                (status.value, limit)
            )
            rows = cursor.fetchall()
            return [self._row_to_media_file(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao buscar por status: {e}", exc_info=True)
            raise
    
    def find_by_session(self, session_id: str) -> List[MediaFile]:
        """Encontrar todos os arquivos de uma sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Lista de MediaFiles
        """
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE import_session_id = ? ORDER BY import_date DESC",
                (session_id,)
            )
            rows = cursor.fetchall()
            return [self._row_to_media_file(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao buscar por sessão: {e}", exc_info=True)
            raise
    
    def find_by_id(self, media_id: MediaId) -> Optional[MediaFile]:
        """Encontrar arquivo por ID.
        
        Args:
            media_id: ID do arquivo
            
        Returns:
            MediaFile se encontrado
        """
        try:
            cursor = self.db.execute(
                "SELECT * FROM media_files WHERE id = ?",
                (media_id.value,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_media_file(row)
            return None
        except Exception as e:
            logger.error(f"Erro ao buscar por ID: {e}", exc_info=True)
            raise
    
    def update_status(self, media_id: MediaId, status: ProcessingStatus) -> bool:
        """Atualizar status do arquivo.
        
        Args:
            media_id: ID do arquivo
            status: Novo status
            
        Returns:
            True se atualizado com sucesso
        """
        try:
            cursor = self.db.execute(
                "UPDATE media_files SET status = ? WHERE id = ?",
                (status.value, media_id.value)
            )
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erro ao atualizar status: {e}", exc_info=True)
            raise
    
    def update_session_stats(self, session_id: str, stats: Dict[str, Any]) -> bool:
        """Atualizar estatísticas da sessão.
        
        Args:
            session_id: ID da sessão
            stats: Dicionário com estatísticas
            
        Returns:
            True se atualizado com sucesso
        """
        try:
            cursor = self.db.execute(
                """UPDATE import_sessions SET 
                   total_files_found = ?,
                   total_files_valid = ?,
                   total_files_imported = ?,
                   total_files_failed = ?,
                   total_duration_seconds = ?,
                   total_size_bytes = ?,
                   completed_at = ?,
                   status = ?
                   WHERE session_id = ?""",
                (
                    stats.get('total_files_found', 0),
                    stats.get('total_files_valid', 0),
                    stats.get('total_files_imported', 0),
                    stats.get('total_files_failed', 0),
                    stats.get('total_duration_seconds', 0),
                    stats.get('total_size_bytes', 0),
                    datetime.utcnow().isoformat(),
                    stats.get('status', 'COMPLETED'),
                    session_id
                )
            )
            self.db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erro ao atualizar sessão: {e}", exc_info=True)
            raise
    
    def get_incomplete_sessions(self) -> List[Dict[str, Any]]:
        """Obter sessões incompletas (para resume).
        
        Returns:
            Lista de sessões com status IN_PROGRESS
        """
        try:
            cursor = self.db.execute(
                """SELECT id, session_id, folder_path, started_at, 
                          total_files_found, total_files_imported
                   FROM import_sessions WHERE status = 'IN_PROGRESS' 
                   ORDER BY started_at DESC"""
            )
            rows = cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    'id': row[0],
                    'session_id': row[1],
                    'folder_path': row[2],
                    'started_at': row[3],
                    'total_files_found': row[4],
                    'total_files_imported': row[5]
                })
            return result
        except Exception as e:
            logger.error(f"Erro ao buscar sessões incompletas: {e}", exc_info=True)
            raise
    
    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Obter estatísticas da sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Dicionário com estatísticas
        """
        try:
            cursor = self.db.execute(
                """SELECT total_files_found, total_files_valid, total_files_imported,
                          total_files_failed, total_duration_seconds, total_size_bytes, status
                   FROM import_sessions WHERE session_id = ?""",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'total_files_found': row[0],
                    'total_files_valid': row[1],
                    'total_files_imported': row[2],
                    'total_files_failed': row[3],
                    'total_duration_seconds': row[4],
                    'total_size_bytes': row[5],
                    'status': row[6]
                }
            return None
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {e}", exc_info=True)
            raise
    
    def get_duplicates(self, session_id: str) -> List[Dict[str, Any]]:
        """Obter arquivos duplicados de uma sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Lista de arquivos duplicados
        """
        try:
            cursor = self.db.execute(
                """SELECT file_name, duplicate_of_hash, import_date 
                   FROM media_files 
                   WHERE import_session_id = ? AND is_duplicate = 1
                   ORDER BY import_date DESC""",
                (session_id,)
            )
            rows = cursor.fetchall()
            return [{
                'file_name': row[0],
                'duplicate_of_hash': row[1],
                'import_date': row[2]
            } for row in rows]
        except Exception as e:
            logger.error(f"Erro ao obter duplicatas: {e}", exc_info=True)
            raise
    
    def _row_to_media_file(self, row: tuple) -> MediaFile:
        """Converter linha do banco para MediaFile.
        
        Args:
            row: Tupla de dados do banco
            
        Returns:
            MediaFile reconstruído
        """
        # Índices da tupla (do SELECT * FROM media_files)
        (media_id, session_id, file_path, file_name, file_ext, file_size,
         file_hash, is_dup, dup_hash, duration, fps, width, height, res_str,
         codec_video, codec_audio, audio_ch, status, import_date, metadata_ver,
         attempts, last_error) = row
        
        return MediaFile(
            id=MediaId(media_id),
            file_info=FileInfo(
                file_path=file_path,
                file_name=file_name,
                file_name_clean=Path(file_name).stem,
                file_extension=file_ext or "",
                file_size=FileSize(file_size or 0)
            ),
            video_info=VideoInfo(
                duration=Duration(duration or 0.0),
                fps=fps or 0.0,
                resolution=Resolution(width, height) if width and height else None,
                codec_video=codec_video or ""
            ),
            audio_info=AudioInfo(
                codec_audio=codec_audio,
                audio_channels=audio_ch or 0
            ),
            processing_info=ProcessingInfo(
                status=ProcessingStatus(status),
                metadata_version=metadata_ver or 0,
                processing_attempts=attempts or 0,
                last_error=last_error
            ),
            hash_info=HashInfo(
                file_hash=FileHash(file_hash),
                is_duplicate=bool(is_dup),
                duplicate_of_hash=FileHash(dup_hash) if dup_hash else None
            )
        )

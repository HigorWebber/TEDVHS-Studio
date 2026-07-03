"""Testes para SQLiteMediaRepository."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from core.database.connection import DatabaseConnection
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from domain.media.media_file import (
    MediaFile, FileInfo, VideoInfo, AudioInfo, ProcessingInfo, HashInfo
)
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileHash, MediaId, FileSize, Duration, Resolution


@pytest.fixture
def temp_db():
    """Criar banco de dados temporário para testes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        import config
        original_path = config.DATABASE_PATH
        config.DATABASE_PATH = db_path
        
        conn = DatabaseConnection()
        conn.connect()
        
        yield conn
        
        conn.close()
        config.DATABASE_PATH = original_path
        DatabaseConnection._instance = None
        DatabaseConnection._connection = None


@pytest.fixture
def repository(temp_db):
    """Criar repository com banco temporário."""
    return SQLiteMediaRepository(temp_db)


class TestImportSessions:
    """Testes de gerenciamento de sessões de importação."""
    
    def test_create_import_session(self, repository):
        """Teste de criação de sessão."""
        session_id = "test-session-001"
        folder_path = "/media/videos"
        
        result = repository.create_import_session(session_id, folder_path)
        
        assert result is not None
        assert isinstance(result, int)
        assert result > 0
    
    def test_get_session_stats(self, repository):
        """Teste de obtenção de estatísticas de sessão."""
        session_id = "test-session-002"
        folder_path = "/media/videos"
        
        repository.create_import_session(session_id, folder_path)
        
        stats = repository.get_session_stats(session_id)
        
        assert stats is not None
        assert stats['status'] == 'IN_PROGRESS'
        assert stats['total_files_found'] == 0
    
    def test_update_session_stats(self, repository):
        """Teste de atualização de estatísticas."""
        session_id = "test-session-003"
        folder_path = "/media/videos"
        
        repository.create_import_session(session_id, folder_path)
        
        stats = {
            'total_files_found': 10,
            'total_files_valid': 8,
            'total_files_imported': 8,
            'total_files_failed': 0,
            'total_duration_seconds': 3600.0,
            'total_size_bytes': 5368709120,  # 5GB
            'status': 'COMPLETED'
        }
        
        result = repository.update_session_stats(session_id, stats)
        
        assert result is True
        
        updated_stats = repository.get_session_stats(session_id)
        assert updated_stats['total_files_found'] == 10
        assert updated_stats['total_files_imported'] == 8
        assert updated_stats['status'] == 'COMPLETED'


class TestMediaFileCRUD:
    """Testes de operações CRUD de arquivos de mídia."""
    
    def test_add_media_file(self, repository):
        """Teste de adição de arquivo de mídia."""
        session_id = "test-session-crud-01"
        repository.create_import_session(session_id, "/media")
        
        media = MediaFile(
            file_info=FileInfo(
                file_path="/media/video.mp4",
                file_name="video.mp4",
                file_name_clean="video",
                file_extension=".mp4",
                file_size=FileSize(1073741824)  # 1GB
            ),
            video_info=VideoInfo(
                duration=Duration(3600.0),
                fps=30.0,
                resolution=Resolution(1920, 1080),
                codec_video="h264"
            ),
            audio_info=AudioInfo(
                codec_audio="aac",
                audio_channels=2
            ),
            hash_info=HashInfo(
                file_hash=FileHash("a" * 64)
            )
        )
        
        result = repository.add_media_file(media, session_id)
        
        assert result is not None
        assert isinstance(result, MediaId)
    
    def test_find_by_hash(self, repository):
        """Teste de busca por hash."""
        session_id = "test-session-crud-02"
        repository.create_import_session(session_id, "/media")
        
        file_hash = FileHash("b" * 64)
        media = MediaFile(
            file_info=FileInfo(
                file_path="/media/video2.mp4",
                file_name="video2.mp4",
                file_name_clean="video2",
                file_extension=".mp4",
                file_size=FileSize(2147483648)  # 2GB
            ),
            video_info=VideoInfo(
                duration=Duration(7200.0),
                fps=24.0,
                resolution=Resolution(3840, 2160),
                codec_video="h265"
            ),
            hash_info=HashInfo(
                file_hash=file_hash
            )
        )
        
        repository.add_media_file(media, session_id)
        
        found = repository.find_by_hash(file_hash)
        
        assert found is not None
        assert found.file_info.file_name == "video2.mp4"
        assert str(found.hash_info.file_hash) == str(file_hash)
    
    def test_find_by_id(self, repository):
        """Teste de busca por ID."""
        session_id = "test-session-crud-03"
        repository.create_import_session(session_id, "/media")
        
        media = MediaFile(
            file_info=FileInfo(
                file_path="/media/video3.mp4",
                file_name="video3.mp4",
                file_name_clean="video3",
                file_extension=".mp4",
                file_size=FileSize(536870912)  # 512MB
            ),
            video_info=VideoInfo(
                duration=Duration(1800.0),
                fps=60.0
            ),
            hash_info=HashInfo(
                file_hash=FileHash("c" * 64)
            )
        )
        
        media_id = repository.add_media_file(media, session_id)
        
        found = repository.find_by_id(media_id)
        
        assert found is not None
        assert found.file_info.file_name == "video3.mp4"
    
    def test_find_by_session(self, repository):
        """Teste de busca por sessão."""
        session_id = "test-session-crud-04"
        repository.create_import_session(session_id, "/media")
        
        # Adicionar múltiplos arquivos
        for i in range(3):
            media = MediaFile(
                file_info=FileInfo(
                    file_path=f"/media/video{i}.mp4",
                    file_name=f"video{i}.mp4",
                    file_name_clean=f"video{i}",
                    file_extension=".mp4",
                    file_size=FileSize(1073741824)
                ),
                video_info=VideoInfo(
                    duration=Duration(3600.0),
                    fps=30.0
                ),
                hash_info=HashInfo(
                    file_hash=FileHash(chr(ord('d') + i) * 64)
                )
            )
            repository.add_media_file(media, session_id)
        
        found_files = repository.find_by_session(session_id)
        
        assert len(found_files) == 3


class TestDuplicateDetection:
    """Testes de detecção de duplicatas."""
    
    def test_duplicate_detection(self, repository):
        """Teste de detecção de arquivo duplicado."""
        session_id = "test-session-dup-01"
        repository.create_import_session(session_id, "/media")
        
        # Adicionar primeiro arquivo
        file_hash = FileHash("e" * 64)
        media1 = MediaFile(
            file_info=FileInfo(
                file_path="/media/original.mp4",
                file_name="original.mp4",
                file_name_clean="original",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            hash_info=HashInfo(
                file_hash=file_hash
            )
        )
        
        result1 = repository.add_media_file(media1, session_id)
        assert result1 is not None
        
        # Tentar adicionar arquivo com mesmo hash
        media2 = MediaFile(
            file_info=FileInfo(
                file_path="/media/duplicate.mp4",
                file_name="duplicate.mp4",
                file_name_clean="duplicate",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            hash_info=HashInfo(
                file_hash=file_hash  # Mesmo hash
            )
        )
        
        result2 = repository.add_media_file(media2, session_id)
        # Deve retornar None pois é duplicata
        assert result2 is None
    
    def test_get_duplicates(self, repository):
        """Teste de obtenção de duplicatas."""
        session_id = "test-session-dup-02"
        repository.create_import_session(session_id, "/media")
        
        # Adicionar arquivo e marcar como duplicado
        file_hash = FileHash("f" * 64)
        original_hash = FileHash("0" * 64)
        
        media = MediaFile(
            file_info=FileInfo(
                file_path="/media/dup.mp4",
                file_name="dup.mp4",
                file_name_clean="dup",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            hash_info=HashInfo(
                file_hash=file_hash,
                is_duplicate=True,
                duplicate_of_hash=original_hash
            )
        )
        
        repository.add_media_file(media, session_id)
        
        duplicates = repository.get_duplicates(session_id)
        
        assert len(duplicates) > 0
        assert duplicates[0]['duplicate_of_hash'] == str(original_hash)


class TestStatusOperations:
    """Testes de operações de status."""
    
    def test_update_status(self, repository):
        """Teste de atualização de status."""
        session_id = "test-session-status-01"
        repository.create_import_session(session_id, "/media")
        
        media = MediaFile(
            file_info=FileInfo(
                file_path="/media/video.mp4",
                file_name="video.mp4",
                file_name_clean="video",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            hash_info=HashInfo(
                file_hash=FileHash("a" * 64)
            )
        )
        
        media_id = repository.add_media_file(media, session_id)
        
        # Atualizar status
        result = repository.update_status(media_id, ProcessingStatus.PROCESSING)
        assert result is True
        
        # Verificar
        found = repository.find_by_id(media_id)
        assert found.processing_info.status == ProcessingStatus.PROCESSING
    
    def test_find_by_status(self, repository):
        """Teste de busca por status."""
        session_id = "test-session-status-02"
        repository.create_import_session(session_id, "/media")
        
        # Adicionar arquivos com diferentes status
        for i in range(3):
            media = MediaFile(
                file_info=FileInfo(
                    file_path=f"/media/video{i}.mp4",
                    file_name=f"video{i}.mp4",
                    file_name_clean=f"video{i}",
                    file_extension=".mp4",
                    file_size=FileSize(1073741824)
                ),
                processing_info=ProcessingInfo(
                    status=ProcessingStatus.READY if i < 2 else ProcessingStatus.FAILED
                ),
                hash_info=HashInfo(
                    file_hash=FileHash(chr(ord('g') + i) * 64)
                )
            )
            repository.add_media_file(media, session_id)
        
        # Buscar por status READY
        ready_files = repository.find_by_status(ProcessingStatus.READY)
        assert len(ready_files) >= 2


class TestIncompleteSessionsResume:
    """Testes de detecção e resumo de sessões incompletas."""
    
    def test_get_incomplete_sessions(self, repository):
        """Teste de obtenção de sessões incompletas."""
        # Criar sessão incompleta
        session_id = "incomplete-session"
        folder_path = "/media/incomplete"
        
        repository.create_import_session(session_id, folder_path)
        
        incomplete = repository.get_incomplete_sessions()
        
        assert len(incomplete) > 0
        assert any(s['session_id'] == session_id for s in incomplete)
    
    def test_incomplete_sessions_not_in_completed(self, repository):
        """Teste para garantir que sessões completas não aparecem na lista incompleta."""
        session_id = "completed-session"
        folder_path = "/media/completed"
        
        repository.create_import_session(session_id, folder_path)
        
        # Marcar como completa
        stats = {
            'total_files_found': 5,
            'total_files_imported': 5,
            'total_files_failed': 0,
            'status': 'COMPLETED'
        }
        repository.update_session_stats(session_id, stats)
        
        incomplete = repository.get_incomplete_sessions()
        
        assert not any(s['session_id'] == session_id for s in incomplete)

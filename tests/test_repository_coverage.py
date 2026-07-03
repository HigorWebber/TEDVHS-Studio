"""Testes de cobertura de integração.

Mede cobertura end-to-end do processo de importação.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from core.database.connection import DatabaseConnection
from domain.media.media_file import (
    MediaFile, FileInfo, VideoInfo, AudioInfo, ProcessingInfo, HashInfo
)
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileHash, MediaId, FileSize, Duration, Resolution


@pytest.fixture
def temp_db():
    """Criar banco de dados temporário."""
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
    """Criar repository."""
    return SQLiteMediaRepository(temp_db)


class TestRepositoryCoverage:
    """Testes de cobertura completa do repository."""
    
    def test_create_and_query_media_files(self, repository):
        """Teste completo: criar e consultar arquivos."""
        session_id = "coverage-test-001"
        repository.create_import_session(session_id, "/test/media")
        
        # Criar 5 arquivos com diferentes características
        created_ids = []
        for i in range(5):
            media = MediaFile(
                file_info=FileInfo(
                    file_path=f"/test/media/video{i}.mp4",
                    file_name=f"video{i}.mp4",
                    file_name_clean=f"video{i}",
                    file_extension=".mp4",
                    file_size=FileSize((i + 1) * 1073741824)  # 1GB, 2GB, ...
                ),
                video_info=VideoInfo(
                    duration=Duration((i + 1) * 3600.0),
                    fps=30.0 + i,
                    resolution=Resolution(1920 + i * 640, 1080 + i * 360),
                    codec_video="h264" if i % 2 == 0 else "h265"
                ),
                audio_info=AudioInfo(
                    codec_audio="aac",
                    audio_channels=2 + i % 2
                ),
                processing_info=ProcessingInfo(
                    status=ProcessingStatus.READY if i < 3 else ProcessingStatus.PROCESSING
                ),
                hash_info=HashInfo(
                    file_hash=FileHash(chr(ord('a') + i) * 64)
                )
            )
            
            media_id = repository.add_media_file(media, session_id)
            assert media_id is not None
            created_ids.append(media_id)
        
        # Verificar que todos foram criados
        assert len(created_ids) == 5
        
        # Consultar por sessão
        session_files = repository.find_by_session(session_id)
        assert len(session_files) == 5
        
        # Consultar por status
        ready_files = repository.find_by_status(ProcessingStatus.READY)
        assert len(ready_files) >= 3
        
        processing_files = repository.find_by_status(ProcessingStatus.PROCESSING)
        assert len(processing_files) >= 2
        
        # Consultar por ID
        first_media = repository.find_by_id(created_ids[0])
        assert first_media is not None
        assert first_media.file_info.file_name == "video0.mp4"
    
    def test_duplicate_handling_workflow(self, repository):
        """Teste completo de tratamento de duplicatas."""
        session_id = "dup-test-001"
        repository.create_import_session(session_id, "/test/media")
        
        # Criar arquivo original
        original_hash = FileHash("f" * 64)
        original_media = MediaFile(
            file_info=FileInfo(
                file_path="/test/original.mp4",
                file_name="original.mp4",
                file_name_clean="original",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            hash_info=HashInfo(
                file_hash=original_hash
            )
        )
        
        original_id = repository.add_media_file(original_media, session_id)
        assert original_id is not None
        
        # Tentar adicionar duplicata
        duplicate_media = MediaFile(
            file_info=FileInfo(
                file_path="/test/duplicate.mp4",
                file_name="duplicate.mp4",
                file_name_clean="duplicate",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            hash_info=HashInfo(
                file_hash=original_hash  # Mesmo hash
            )
        )
        
        dup_id = repository.add_media_file(duplicate_media, session_id)
        assert dup_id is None  # Deve rejeitar duplicata
        
        # Verificar que apenas um arquivo existe
        session_files = repository.find_by_session(session_id)
        assert len(session_files) == 1
    
    def test_status_lifecycle(self, repository):
        """Teste do ciclo de vida de status."""
        session_id = "status-test-001"
        repository.create_import_session(session_id, "/test/media")
        
        # Criar arquivo com status PENDING
        media = MediaFile(
            file_info=FileInfo(
                file_path="/test/lifecycle.mp4",
                file_name="lifecycle.mp4",
                file_name_clean="lifecycle",
                file_extension=".mp4",
                file_size=FileSize(1073741824)
            ),
            processing_info=ProcessingInfo(
                status=ProcessingStatus.PENDING
            ),
            hash_info=HashInfo(
                file_hash=FileHash("g" * 64)
            )
        )
        
        media_id = repository.add_media_file(media, session_id)
        
        # Simular ciclo de processamento
        statuses = [
            ProcessingStatus.PROCESSING,
            ProcessingStatus.READY,
        ]
        
        for status in statuses:
            result = repository.update_status(media_id, status)
            assert result is True
            
            found = repository.find_by_id(media_id)
            assert found.processing_info.status == status
    
    def test_session_statistics_accumulation(self, repository):
        """Teste de acumulação de estatísticas de sessão."""
        session_id = "stats-test-001"
        repository.create_import_session(session_id, "/test/media")
        
        # Adicionar alguns arquivos
        for i in range(3):
            media = MediaFile(
                file_info=FileInfo(
                    file_path=f"/test/stat_video{i}.mp4",
                    file_name=f"stat_video{i}.mp4",
                    file_name_clean=f"stat_video{i}",
                    file_extension=".mp4",
                    file_size=FileSize(1073741824)
                ),
                hash_info=HashInfo(
                    file_hash=FileHash(chr(ord('h') + i) * 64)
                )
            )
            repository.add_media_file(media, session_id)
        
        # Atualizar estatísticas
        stats = {
            'total_files_found': 10,
            'total_files_valid': 8,
            'total_files_imported': 8,
            'total_files_failed': 2,
            'total_duration_seconds': 36000.0,
            'total_size_bytes': 10737418240,  # 10GB
            'status': 'COMPLETED'
        }
        
        result = repository.update_session_stats(session_id, stats)
        assert result is True
        
        # Verificar que foram atualizadas
        updated_stats = repository.get_session_stats(session_id)
        assert updated_stats['total_files_found'] == 10
        assert updated_stats['total_files_imported'] == 8
        assert updated_stats['total_files_failed'] == 2
        assert updated_stats['status'] == 'COMPLETED'
    
    def test_incomplete_sessions_workflow(self, repository):
        """Teste de fluxo de sessões incompletas."""
        # Criar 3 sessões
        for idx in range(3):
            session_id = f"incomplete-session-{idx}"
            repository.create_import_session(session_id, f"/test/media{idx}")
        
        # Marcar primeira como completa
        repository.update_session_stats(
            "incomplete-session-0",
            {'status': 'COMPLETED'}
        )
        
        # Obter incompletas
        incomplete = repository.get_incomplete_sessions()
        
        # Deve ter 2 incompletas
        assert len(incomplete) == 2
        assert not any(s['session_id'] == 'incomplete-session-0' for s in incomplete)


@pytest.fixture(scope="session")
def coverage_report():
    """Gerar relatório de cobertura."""
    import coverage
    cov = coverage.Coverage()
    cov.start()
    yield
    cov.stop()
    cov.save()

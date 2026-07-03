"""Testes de integração end-to-end de importação."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from application.media.import_orchestrator import ImportOrchestrator
from application.media.media_pipeline import MediaPipeline
from application.task_management import TaskScheduler, TaskQueue
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from core.database.connection import DatabaseConnection
from application.event_bus import EventBus


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


@pytest.fixture
def orchestrator(repository):
    """Criar orchestrator com mocks."""
    mock_pipeline = Mock(spec=MediaPipeline)
    task_queue = TaskQueue(max_concurrent_tasks=4)
    task_scheduler = TaskScheduler(task_queue, max_workers=4)
    event_bus = EventBus()
    
    task_scheduler.start()
    
    return ImportOrchestrator(
        media_pipeline=mock_pipeline,
        task_scheduler=task_scheduler,
        repository=repository,
        event_bus=event_bus
    ), mock_pipeline, task_scheduler


class TestImportOrchestrator:
    """Testes do orquestrador de importação."""
    
    def test_start_import_creates_session(self, orchestrator, temp_db):
        """Teste de criação de sessão ao iniciar importação."""
        orch, _, _ = orchestrator
        
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = orch.start_import(tmpdir)
            
            assert session_id is not None
            assert orch.current_session_id == session_id
    
    def test_start_import_with_invalid_folder_raises(self, orchestrator):
        """Teste que caminho inválido lança exceção."""
        orch, _, _ = orchestrator
        
        with pytest.raises(ValueError):
            orch.start_import("/path/that/does/not/exist")
    
    def test_get_session_progress_returns_dict(self, orchestrator, temp_db):
        """Teste de obtenção de progresso."""
        orch, mock_pipeline, _ = orchestrator
        
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = orch.start_import(tmpdir)
            
            progress = orch.get_session_progress(session_id)
            
            assert isinstance(progress, dict)
            assert 'session_id' in progress
            assert 'percentage' in progress
            assert 'status' in progress
    
    def test_get_incomplete_sessions_returns_list(self, orchestrator, temp_db):
        """Teste de obtenção de sessões incompletas."""
        orch, _, _ = orchestrator
        
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = orch.start_import(tmpdir)
            
            incomplete = orch.get_incomplete_sessions()
            
            assert isinstance(incomplete, list)
            assert len(incomplete) > 0
    
    def test_progress_percentage_calculation(self, orchestrator, temp_db):
        """Teste de cálculo de percentual de progresso."""
        orch, _, _ = orchestrator
        
        # Testar cálculo com diferentes estatísticas
        stats = {
            'total_files_found': 100,
            'total_files_imported': 50,
            'total_files_failed': 0
        }
        
        percentage = orch._calculate_progress_percentage(stats)
        
        assert percentage == 50
    
    def test_progress_percentage_caps_at_100(self, orchestrator):
        """Teste que percentual não excede 100%."""
        orch, _, _ = orchestrator
        
        stats = {
            'total_files_found': 100,
            'total_files_imported': 101,  # Impossível mas testa o cap
            'total_files_failed': 0
        }
        
        percentage = orch._calculate_progress_percentage(stats)
        
        assert percentage <= 100


class TestImportWorkflow:
    """Testes do fluxo completo de importação."""
    
    def test_full_import_workflow(self, orchestrator, temp_db):
        """Teste do fluxo completo de importação."""
        orch, mock_pipeline, scheduler = orchestrator
        
        # Simular resultado do pipeline
        mock_pipeline.process_directory.return_value = {
            'total_files_found': 10,
            'total_files_valid': 8,
            'total_files_imported': 8,
            'total_files_failed': 0,
            'total_duration_seconds': 3600.0,
            'total_size_bytes': 5368709120
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = orch.start_import(tmpdir)
            
            # Aguardar conclusão (simulado)
            progress = orch.get_session_progress(session_id)
            
            assert session_id is not None
            assert progress['percentage'] >= 0
    
    def test_resume_import_workflow(self, orchestrator):
        """Teste de resumo de importação."""
        orch, mock_pipeline, scheduler = orchestrator
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Iniciar importação
            session_id = orch.start_import(tmpdir)
            
            # Obter sessões incompletas
            incomplete = orch.get_incomplete_sessions()
            
            assert len(incomplete) > 0
            assert incomplete[0]['session_id'] == session_id

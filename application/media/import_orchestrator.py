"""Orquestrador de importação de biblioteca de mídia.

Coordenação entre MediaPipeline, TaskScheduler e Repositório.
"""

import logging
from typing import Callable, Optional, Dict, Any
from pathlib import Path
from uuid import uuid4
from datetime import datetime

from application.media.media_pipeline import MediaPipeline
from application.task_management import TaskScheduler, Task, TaskStatus, TaskPriority
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from domain.media.processing_status import ProcessingStatus
from application.event_bus import EventBus


logger = logging.getLogger(__name__)


class ImportOrchestrator:
    """Orquestrador de importação de mídia.
    
    Coordena:
    - MediaPipeline para processar arquivos
    - TaskScheduler para execução em background
    - SQLiteMediaRepository para persistência
    - EventBus para notificações
    """
    
    def __init__(self,
                 media_pipeline: MediaPipeline,
                 task_scheduler: TaskScheduler,
                 repository: SQLiteMediaRepository,
                 event_bus: EventBus):
        """Inicializar orquestrador.
        
        Args:
            media_pipeline: Pipeline de processamento de mídia
            task_scheduler: Agendador de tarefas
            repository: Repository de persistência
            event_bus: Barramento de eventos
        """
        self.pipeline = media_pipeline
        self.scheduler = task_scheduler
        self.repository = repository
        self.event_bus = event_bus
        self.current_session_id: Optional[str] = None
        self.progress_callbacks: Dict[str, Callable] = {}
        
        logger.info("ImportOrchestrator inicializado")
    
    def start_import(self, folder_path: str,
                    progress_callback: Optional[Callable] = None,
                    cancel_callback: Optional[Callable] = None) -> str:
        """Iniciar importação de pasta em background.
        
        Args:
            folder_path: Caminho da pasta a importar
            progress_callback: Callback para atualizações de progresso
            cancel_callback: Callback para cancelamento
            
        Returns:
            Session ID para rastreamento
        """
        try:
            # Validar pasta
            folder = Path(folder_path)
            if not folder.exists() or not folder.is_dir():
                raise ValueError(f"Pasta inválida: {folder_path}")
            
            # Criar sessão
            session_id = str(uuid4())
            self.current_session_id = session_id
            
            # Registrar no repositório
            self.repository.create_import_session(session_id, folder_path)
            
            # Guardar callbacks
            self.progress_callbacks[session_id] = progress_callback
            
            # Criar tarefa
            task = Task(
                name=f"Importar biblioteca: {folder.name}",
                priority=TaskPriority.HIGH,
                description=f"Importando mídia de {folder_path}"
            )
            
            # Submeter para execução
            def import_handler(t: Task) -> None:
                """Handler de importação."""
                self._execute_import(session_id, folder_path, progress_callback)
            
            future = self.scheduler.submit_task(task, import_handler)
            
            logger.info(f"Importação iniciada: session_id={session_id}, folder={folder_path}")
            return session_id
            
        except Exception as e:
            logger.error(f"Erro ao iniciar importação: {e}", exc_info=True)
            raise
    
    def _execute_import(self, session_id: str, folder_path: str,
                       progress_callback: Optional[Callable]) -> None:
        """Executar importação (rodado em thread de background).
        
        Args:
            session_id: ID da sessão
            folder_path: Caminho da pasta
            progress_callback: Callback de progresso
        """
        try:
            logger.info(f"Executando importação: {session_id}")
            
            # Definir callback de progresso wrapper
            def progress_wrapper(stage: str, current: int = 0, total: int = 0) -> None:
                """Wrapper de progresso com persistência."""
                if progress_callback:
                    progress_callback(stage, current, total)
            
            # Executar pipeline
            stats = self.pipeline.process_directory(
                folder_path,
                progress_callback=progress_wrapper
            )
            
            # Persister results
            stats['status'] = 'COMPLETED'
            self.repository.update_session_stats(session_id, stats)
            
            logger.info(f"Importação concluída: {session_id}")
            logger.info(f"Estatísticas: {stats}")
            
            # Emitir evento de conclusão
            self.event_bus.emit({
                'type': 'IMPORT_COMPLETED',
                'session_id': session_id,
                'stats': stats
            })
            
        except Exception as e:
            logger.error(f"Erro ao executar importação: {e}", exc_info=True)
            
            # Atualizar status como falho
            try:
                self.repository.update_session_stats(
                    session_id,
                    {'status': 'FAILED', 'error': str(e)}
                )
            except:
                pass
            
            # Emitir evento de erro
            self.event_bus.emit({
                'type': 'IMPORT_FAILED',
                'session_id': session_id,
                'error': str(e)
            })
    
    def get_session_progress(self, session_id: str) -> Dict[str, Any]:
        """Obter progresso da sessão.
        
        Args:
            session_id: ID da sessão
            
        Returns:
            Dicionário com informações de progresso
        """
        try:
            stats = self.repository.get_session_stats(session_id)
            if stats:
                return {
                    'session_id': session_id,
                    'total_files_found': stats.get('total_files_found', 0),
                    'total_files_imported': stats.get('total_files_imported', 0),
                    'total_files_failed': stats.get('total_files_failed', 0),
                    'total_files_valid': stats.get('total_files_valid', 0),
                    'status': stats.get('status', 'IN_PROGRESS'),
                    'percentage': self._calculate_progress_percentage(stats)
                }
            return {}
        except Exception as e:
            logger.error(f"Erro ao obter progresso: {e}", exc_info=True)
            return {}
    
    def _calculate_progress_percentage(self, stats: Dict[str, Any]) -> int:
        """Calcular percentual de progresso.
        
        Args:
            stats: Estatísticas da sessão
            
        Returns:
            Percentual (0-100)
        """
        total = stats.get('total_files_found', 0)
        if total == 0:
            return 0
        
        imported = stats.get('total_files_imported', 0)
        failed = stats.get('total_files_failed', 0)
        processed = imported + failed
        
        percentage = int((processed / total) * 100)
        return min(percentage, 100)  # Cap at 100%
    
    def get_incomplete_sessions(self) -> list:
        """Obter sessões incompletas para resumo.
        
        Returns:
            Lista de sessões incompletas
        """
        try:
            return self.repository.get_incomplete_sessions()
        except Exception as e:
            logger.error(f"Erro ao obter sessões incompletas: {e}", exc_info=True)
            return []
    
    def resume_import(self, session_id: str,
                     progress_callback: Optional[Callable] = None) -> None:
        """Retomar importação incompleta.
        
        Args:
            session_id: ID da sessão a retomar
            progress_callback: Callback de progresso
        """
        try:
            logger.info(f"Retomando importação: {session_id}")
            
            # Obter informações da sessão
            sessions = self.repository.get_incomplete_sessions()
            session_info = next((s for s in sessions if s['session_id'] == session_id), None)
            
            if not session_info:
                raise ValueError(f"Sessão não encontrada: {session_id}")
            
            # Retomar processamento
            folder_path = session_info['folder_path']
            
            # Criar tarefa de resumo
            task = Task(
                name=f"Retomar importação: {Path(folder_path).name}",
                priority=TaskPriority.HIGH,
                description=f"Retomando importação de {folder_path}"
            )
            
            def resume_handler(t: Task) -> None:
                """Handler de resumo."""
                self._execute_import(session_id, folder_path, progress_callback)
            
            self.scheduler.submit_task(task, resume_handler)
            
            logger.info(f"Importação retomada: {session_id}")
            
        except Exception as e:
            logger.error(f"Erro ao retomar importação: {e}", exc_info=True)
            raise

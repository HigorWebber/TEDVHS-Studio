"""Application dependency injection container."""

import logging
from pathlib import Path
from typing import Optional

from core.database.connection import DatabaseConnection
from infrastructure.media.ffprobe_scanner import FFprobeMediaScanner
from infrastructure.media.media_library_service import MediaLibraryService
from infrastructure.persistence.repositories import Repository
from infrastructure.persistence.unit_of_work import UnitOfWork
from application.task_management import TaskQueue, TaskScheduler
from application.event_bus import EventBus


logger = logging.getLogger(__name__)


class ServiceContainer:
    """Dependency injection container.
    
    Centralized management of service instantiation and lifecycle.
    """
    
    def __init__(self, db_connection: DatabaseConnection, media_dir: Path,
                 ffprobe_path: str = 'ffprobe', max_workers: int = 4):
        """Initialize service container.
        
        Args:
            db_connection: Database connection
            media_dir: Media storage directory
            ffprobe_path: Path to ffprobe executable
            max_workers: Maximum concurrent workers
        """
        self.db_connection = db_connection
        self.media_dir = Path(media_dir)
        self.ffprobe_path = ffprobe_path
        self.max_workers = max_workers
        
        # Initialize services
        self._services = {}
        self._initialize_services()
        
        logger.info("ServiceContainer initialized")
    
    def _initialize_services(self) -> None:
        """Initialize all services."""
        # Media services
        self._services['media_scanner'] = FFprobeMediaScanner(self.ffprobe_path)
        
        episode_repo = Repository(self.db_connection, 'episode')
        self._services['media_library'] = MediaLibraryService(
            self._services['media_scanner'],
            episode_repo,
            self.media_dir
        )
        
        # Data access
        self._services['unit_of_work'] = UnitOfWork(self.db_connection)
        
        # Task management
        self._services['task_queue'] = TaskQueue(max_concurrent_tasks=self.max_workers)
        self._services['task_scheduler'] = TaskScheduler(
            self._services['task_queue'],
            max_workers=self.max_workers
        )
        
        # Event system
        self._services['event_bus'] = EventBus()
        
        logger.debug(f"Initialized {len(self._services)} services")
    
    def get(self, service_name: str):
        """Get service by name.
        
        Args:
            service_name: Service identifier
            
        Returns:
            Service instance
            
        Raises:
            KeyError: If service not found
        """
        if service_name not in self._services:
            raise KeyError(f"Service not found: {service_name}")
        return self._services[service_name]
    
    def get_media_library(self) -> MediaLibraryService:
        """Get media library service."""
        return self.get('media_library')
    
    def get_task_queue(self) -> TaskQueue:
        """Get task queue."""
        return self.get('task_queue')
    
    def get_task_scheduler(self) -> TaskScheduler:
        """Get task scheduler."""
        return self.get('task_scheduler')
    
    def get_event_bus(self) -> EventBus:
        """Get event bus."""
        return self.get('event_bus')
    
    def get_unit_of_work(self) -> UnitOfWork:
        """Get unit of work."""
        return self.get('unit_of_work')
    
    def shutdown(self) -> None:
        """Shutdown container and all services."""
        logger.info("Shutting down ServiceContainer")
        
        # Stop task scheduler
        if 'task_scheduler' in self._services:
            self._services['task_scheduler'].stop()
        
        # Close unit of work
        if 'unit_of_work' in self._services:
            self._services['unit_of_work'].close()
        
        self._services.clear()
        logger.info("ServiceContainer shutdown complete")

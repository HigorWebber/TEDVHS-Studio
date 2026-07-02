"""Task management system for background operations."""

from enum import Enum
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable
import logging


logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents a background task.
    
    Attributes:
        id: Unique task identifier
        name: Human-readable task name
        priority: Task priority level
        status: Current execution status
        progress: Progress percentage (0-100)
        created_at: Creation timestamp
        started_at: Start timestamp
        completed_at: Completion timestamp
        total_steps: Total steps for progress tracking
        current_step: Current step being processed
        metadata: Custom task-specific data
        error_message: Error description if failed
    """
    
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_steps: int = 0
    current_step: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    
    def update_progress(self, current_step: int, total_steps: Optional[int] = None) -> None:
        """Update task progress.
        
        Args:
            current_step: Current step number
            total_steps: Total steps (updates if provided)
        """
        if total_steps is not None:
            self.total_steps = total_steps
        
        self.current_step = current_step
        if self.total_steps > 0:
            self.progress = (current_step / self.total_steps) * 100
        
        logger.debug(f"Task {self.id} progress: {self.progress:.1f}%")
    
    def mark_completed(self) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.progress = 100.0
        logger.info(f"Task {self.id} completed")
    
    def mark_failed(self, error: str) -> None:
        """Mark task as failed.
        
        Args:
            error: Error message
        """
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error_message = error
        logger.error(f"Task {self.id} failed: {error}")
    
    def mark_paused(self) -> None:
        """Pause task execution."""
        if self.status == TaskStatus.RUNNING:
            self.status = TaskStatus.PAUSED
            logger.info(f"Task {self.id} paused")
    
    def mark_resumed(self) -> None:
        """Resume paused task."""
        if self.status == TaskStatus.PAUSED:
            self.status = TaskStatus.RUNNING
            logger.info(f"Task {self.id} resumed")
    
    def mark_cancelled(self) -> None:
        """Cancel task execution."""
        if self.status in (TaskStatus.PENDING, TaskStatus.PAUSED, TaskStatus.RUNNING):
            self.status = TaskStatus.CANCELLED
            self.completed_at = datetime.utcnow()
            logger.info(f"Task {self.id} cancelled")
    
    def get_duration_seconds(self) -> float:
        """Get task duration in seconds.
        
        Returns:
            Duration in seconds, or 0 if not started/completed
        """
        if not self.started_at:
            return 0.0
        
        end = self.completed_at or datetime.utcnow()
        return (end - self.started_at).total_seconds()
    
    def is_running(self) -> bool:
        """Check if task is currently running."""
        return self.status == TaskStatus.RUNNING
    
    def is_finished(self) -> bool:
        """Check if task has finished (completed or failed)."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

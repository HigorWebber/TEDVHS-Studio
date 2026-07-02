"""Job system foundation for processing management."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
import logging


logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Job execution status."""
    
    PENDING = "pending"          # Awaiting execution
    RUNNING = "running"          # Currently executing
    PAUSED = "paused"            # Paused by user
    COMPLETED = "completed"      # Successfully completed
    FAILED = "failed"            # Execution failed
    CANCELLED = "cancelled"      # Cancelled by user


class JobPriority(Enum):
    """Job execution priority."""
    
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0


@dataclass
class JobProgress:
    """Tracks job progress."""
    
    current_step: int = 0
    total_steps: int = 0
    percentage: float = 0.0
    message: str = ""
    
    def update(self, current: int, total: int, message: str = "") -> None:
        """Update progress.
        
        Args:
            current: Current step
            total: Total steps
            message: Progress message
        """
        self.current_step = current
        self.total_steps = total
        self.percentage = (current / total * 100) if total > 0 else 0
        self.message = message


class IJob(ABC):
    """Base interface for all jobs.
    
    Jobs are discrete units of work that can be executed,
    paused, resumed, and cancelled.
    """
    
    @property
    @abstractmethod
    def job_id(self) -> str:
        """Get unique job identifier."""
        pass
    
    @property
    @abstractmethod
    def status(self) -> JobStatus:
        """Get current job status."""
        pass
    
    @property
    @abstractmethod
    def progress(self) -> JobProgress:
        """Get job progress."""
        pass
    
    @abstractmethod
    def execute(self) -> Dict[str, Any]:
        """Execute the job.
        
        Returns:
            Job execution results
            
        Raises:
            Exception: If execution fails
        """
        pass
    
    @abstractmethod
    def pause(self) -> bool:
        """Pause job execution.
        
        Returns:
            True if paused successfully
        """
        pass
    
    @abstractmethod
    def resume(self) -> bool:
        """Resume paused job.
        
        Returns:
            True if resumed successfully
        """
        pass
    
    @abstractmethod
    def cancel(self) -> bool:
        """Cancel job execution.
        
        Returns:
            True if cancelled successfully
        """
        pass
    
    @abstractmethod
    def get_result(self) -> Optional[Dict[str, Any]]:
        """Get job execution result.
        
        Returns:
            Result if completed, None otherwise
        """
        pass


class BaseJob(IJob):
    """Base implementation for jobs.
    
    Provides common job functionality.
    Subclasses implement specific execute logic.
    """
    
    def __init__(self, job_id: str, priority: JobPriority = JobPriority.NORMAL):
        """Initialize job.
        
        Args:
            job_id: Unique job identifier
            priority: Execution priority
        """
        self._job_id = job_id
        self._priority = priority
        self._status = JobStatus.PENDING
        self._progress = JobProgress()
        self._result: Optional[Dict[str, Any]] = None
        self._error: Optional[str] = None
        self._created_at = datetime.utcnow()
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None
    
    @property
    def job_id(self) -> str:
        return self._job_id
    
    @property
    def status(self) -> JobStatus:
        return self._status
    
    @property
    def progress(self) -> JobProgress:
        return self._progress
    
    def pause(self) -> bool:
        """Pause job."""
        if self._status == JobStatus.RUNNING:
            self._status = JobStatus.PAUSED
            logger.debug(f"Job paused: {self._job_id}")
            return True
        return False
    
    def resume(self) -> bool:
        """Resume job."""
        if self._status == JobStatus.PAUSED:
            self._status = JobStatus.RUNNING
            logger.debug(f"Job resumed: {self._job_id}")
            return True
        return False
    
    def cancel(self) -> bool:
        """Cancel job."""
        if self._status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED):
            self._status = JobStatus.CANCELLED
            self._completed_at = datetime.utcnow()
            logger.debug(f"Job cancelled: {self._job_id}")
            return True
        return False
    
    def get_result(self) -> Optional[Dict[str, Any]]:
        return self._result
    
    def _mark_started(self) -> None:
        """Mark job as started."""
        self._status = JobStatus.RUNNING
        self._started_at = datetime.utcnow()
    
    def _mark_completed(self, result: Dict[str, Any]) -> None:
        """Mark job as completed.
        
        Args:
            result: Execution result
        """
        self._status = JobStatus.COMPLETED
        self._result = result
        self._completed_at = datetime.utcnow()
    
    def _mark_failed(self, error: str) -> None:
        """Mark job as failed.
        
        Args:
            error: Error message
        """
        self._status = JobStatus.FAILED
        self._error = error
        self._completed_at = datetime.utcnow()

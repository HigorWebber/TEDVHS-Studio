"""Task queue for managing background operations."""

import logging
from typing import List, Optional, Callable, Any
from queue import PriorityQueue, Empty
from datetime import datetime
import threading

from application.task_management.task import Task, TaskStatus, TaskPriority
from shared.types import EventType


logger = logging.getLogger(__name__)


class TaskQueue:
    """Priority queue for background tasks.
    
    Manages task queuing with priority levels, pausing, resuming, and cancellation.
    """
    
    def __init__(self, max_concurrent_tasks: int = 1):
        """Initialize task queue.
        
        Args:
            max_concurrent_tasks: Maximum concurrent tasks to process
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.queue: PriorityQueue = PriorityQueue()
        self.active_tasks: dict[str, Task] = {}
        self.completed_tasks: dict[str, Task] = {}
        self.lock = threading.RLock()
        self.is_running = False
        logger.info(f"TaskQueue initialized with {max_concurrent_tasks} concurrent tasks")
    
    def enqueue(self, task: Task) -> None:
        """Add task to queue.
        
        Args:
            task: Task to enqueue
        """
        with self.lock:
            # Higher priority value = higher priority = process sooner
            priority = -task.priority.value  # Negative for min-heap behavior
            self.queue.put((priority, task.created_at.timestamp(), task))
            logger.info(f"Task {task.id} enqueued with priority {task.priority.name}")
    
    def dequeue(self, timeout: Optional[float] = None) -> Optional[Task]:
        """Get next task from queue.
        
        Args:
            timeout: Wait timeout in seconds
            
        Returns:
            Next task or None if queue empty
        """
        try:
            _, _, task = self.queue.get(timeout=timeout)
            return task
        except Empty:
            return None
    
    def add_task(self, name: str, priority: TaskPriority = TaskPriority.NORMAL,
                 metadata: Optional[dict] = None) -> Task:
        """Create and enqueue a new task.
        
        Args:
            name: Task name
            priority: Task priority
            metadata: Custom metadata
            
        Returns:
            Created task
        """
        task = Task(
            name=name,
            priority=priority,
            metadata=metadata or {}
        )
        self.enqueue(task)
        return task
    
    def start_task(self, task: Task) -> None:
        """Mark task as started.
        
        Args:
            task: Task to start
        """
        with self.lock:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            self.active_tasks[task.id] = task
            logger.info(f"Task {task.id} started")
    
    def complete_task(self, task: Task) -> None:
        """Mark task as completed.
        
        Args:
            task: Task to complete
        """
        with self.lock:
            task.mark_completed()
            self.active_tasks.pop(task.id, None)
            self.completed_tasks[task.id] = task
            logger.info(f"Task {task.id} completed")
    
    def fail_task(self, task: Task, error: str) -> None:
        """Mark task as failed.
        
        Args:
            task: Task that failed
            error: Error message
        """
        with self.lock:
            task.mark_failed(error)
            self.active_tasks.pop(task.id, None)
            self.completed_tasks[task.id] = task
            logger.error(f"Task {task.id} failed: {error}")
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task.
        
        Args:
            task_id: ID of task to cancel
            
        Returns:
            True if cancelled, False if not found or already finished
        """
        with self.lock:
            # Try active tasks first
            task = self.active_tasks.get(task_id)
            if not task:
                # Check queue by reconstructing (inefficient, but simple)
                logger.warning(f"Task {task_id} not in active tasks")
                return False
            
            if not task.is_finished():
                task.mark_cancelled()
                self.active_tasks.pop(task_id, None)
                self.completed_tasks[task_id] = task
                logger.info(f"Task {task_id} cancelled")
                return True
            
            return False
    
    def pause_task(self, task_id: str) -> bool:
        """Pause a running task.
        
        Args:
            task_id: ID of task to pause
            
        Returns:
            True if paused, False if not found or not running
        """
        with self.lock:
            task = self.active_tasks.get(task_id)
            if task and task.is_running():
                task.mark_paused()
                logger.info(f"Task {task_id} paused")
                return True
            return False
    
    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task.
        
        Args:
            task_id: ID of task to resume
            
        Returns:
            True if resumed, False if not found or not paused
        """
        with self.lock:
            task = self.active_tasks.get(task_id)
            if task and task.status == TaskStatus.PAUSED:
                task.mark_resumed()
                logger.info(f"Task {task_id} resumed")
                return True
            return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task or None if not found
        """
        with self.lock:
            return self.active_tasks.get(task_id) or self.completed_tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Task]:
        """Get all tasks (active and completed).
        
        Returns:
            List of all tasks
        """
        with self.lock:
            return list(self.active_tasks.values()) + list(self.completed_tasks.values())
    
    def get_active_tasks(self) -> List[Task]:
        """Get currently active tasks.
        
        Returns:
            List of active tasks
        """
        with self.lock:
            return list(self.active_tasks.values())
    
    def queue_size(self) -> int:
        """Get number of pending tasks in queue.
        
        Returns:
            Queue size
        """
        return self.queue.qsize()
    
    def clear_completed(self) -> int:
        """Clear completed tasks from history.
        
        Returns:
            Number of tasks cleared
        """
        with self.lock:
            count = len(self.completed_tasks)
            self.completed_tasks.clear()
            logger.info(f"Cleared {count} completed tasks")
            return count

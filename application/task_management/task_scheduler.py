"""Task scheduler for executing queued tasks."""

import logging
import threading
import time
from typing import Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, Future

from application.task_management.task import Task, TaskStatus
from application.task_management.task_queue import TaskQueue


logger = logging.getLogger(__name__)


class TaskScheduler:
    """Executes tasks from queue in dedicated threads.
    
    Manages task execution with proper error handling and status tracking.
    """
    
    def __init__(self, queue: TaskQueue, max_workers: int = 4):
        """Initialize task scheduler.
        
        Args:
            queue: Task queue to process
            max_workers: Maximum concurrent worker threads
        """
        self.queue = queue
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.running = False
        self.lock = threading.RLock()
        self.futures: dict[str, Future] = {}
        logger.info(f"TaskScheduler initialized with {max_workers} workers")
    
    def start(self) -> None:
        """Start the scheduler."""
        with self.lock:
            if self.running:
                logger.warning("Scheduler already running")
                return
            
            self.running = True
            logger.info("TaskScheduler started")
    
    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler.
        
        Args:
            wait: Wait for running tasks to complete
        """
        with self.lock:
            self.running = False
            logger.info("TaskScheduler stopping")
        
        if wait:
            self.executor.shutdown(wait=True)
            logger.info("TaskScheduler stopped")
    
    def submit_task(self, task: Task, handler: Callable[[Task], Any]) -> Optional[Future]:
        """Submit task for execution.
        
        Args:
            task: Task to execute
            handler: Callable that executes the task
            
        Returns:
            Future object for tracking execution
        """
        if not self.running:
            logger.warning("Scheduler not running, cannot submit task")
            return None
        
        with self.lock:
            self.queue.start_task(task)
            
            # Submit to executor
            future = self.executor.submit(
                self._execute_task,
                task,
                handler
            )
            
            self.futures[task.id] = future
            logger.debug(f"Task {task.id} submitted for execution")
            
            return future
    
    def _execute_task(self, task: Task, handler: Callable[[Task], Any]) -> None:
        """Execute a task with error handling.
        
        Args:
            task: Task to execute
            handler: Callable that executes the task
        """
        try:
            logger.info(f"Executing task {task.id}: {task.name}")
            handler(task)
            self.queue.complete_task(task)
            
        except Exception as e:
            logger.error(f"Task {task.id} execution failed", exc_info=True)
            self.queue.fail_task(task, str(e))
        
        finally:
            # Clean up future reference
            with self.lock:
                self.futures.pop(task.id, None)
    
    def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> bool:
        """Wait for task completion.
        
        Args:
            task_id: Task ID to wait for
            timeout: Wait timeout in seconds
            
        Returns:
            True if completed, False if timeout
        """
        with self.lock:
            future = self.futures.get(task_id)
        
        if not future:
            return True  # Already completed
        
        try:
            future.result(timeout=timeout)
            return True
        except Exception:
            return False
    
    def get_running_tasks_count(self) -> int:
        """Get number of currently running tasks.
        
        Returns:
            Count of running tasks
        """
        with self.lock:
            return len([f for f in self.futures.values() if f.running()])

"""Task management tests."""

import unittest
from datetime import datetime

from application.task_management import Task, TaskQueue, TaskStatus, TaskPriority


class TestTask(unittest.TestCase):
    """Test Task class."""
    
    def test_task_creation(self):
        """Test creating a task."""
        task = Task(name="Test Task", priority=TaskPriority.HIGH)
        
        self.assertEqual(task.name, "Test Task")
        self.assertEqual(task.priority, TaskPriority.HIGH)
        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(task.progress, 0.0)
    
    def test_task_progress_update(self):
        """Test updating task progress."""
        task = Task(name="Test")
        task.update_progress(5, total_steps=10)
        
        self.assertEqual(task.progress, 50.0)
        self.assertEqual(task.current_step, 5)
    
    def test_task_completion(self):
        """Test marking task as completed."""
        task = Task(name="Test")
        task.mark_completed()
        
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.progress, 100.0)
        self.assertIsNotNone(task.completed_at)
    
    def test_task_failure(self):
        """Test marking task as failed."""
        task = Task(name="Test")
        task.mark_failed("Test error")
        
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.error_message, "Test error")


class TestTaskQueue(unittest.TestCase):
    """Test TaskQueue class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.queue = TaskQueue()
    
    def test_enqueue_task(self):
        """Test enqueuing a task."""
        task = Task(name="Test")
        self.queue.enqueue(task)
        
        self.assertEqual(self.queue.queue_size(), 1)
    
    def test_add_task(self):
        """Test adding a task via helper."""
        task = self.queue.add_task("Test", priority=TaskPriority.HIGH)
        
        self.assertEqual(task.name, "Test")
        self.assertEqual(task.priority, TaskPriority.HIGH)
    
    def test_get_task(self):
        """Test retrieving task by ID."""
        task = self.queue.add_task("Test")
        retrieved = self.queue.get_task(task.id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, task.id)
    
    def test_cancel_task(self):
        """Test cancelling a task."""
        task = self.queue.add_task("Test")
        self.queue.start_task(task)
        
        success = self.queue.cancel_task(task.id)
        
        self.assertTrue(success)
        self.assertEqual(task.status, TaskStatus.CANCELLED)


if __name__ == '__main__':
    unittest.main()

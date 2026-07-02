# CONTRIBUTING

## Development Guidelines

This document outlines best practices for contributing to TEDVHS Studio.

## Architecture

The project follows **Clean Architecture** with these layers:

```
Presentation → Application → Domain ← Infrastructure
                    ↓
                  Shared
```

**Rules**:
- Domain layer should NEVER import from Infrastructure
- Presentation should ONLY import from Application
- Use interfaces (domain/interfaces.py) for abstractions
- All external dependencies in Infrastructure layer

## Code Standards

### Type Hints

```python
# ✅ GOOD
def process_task(task: Task) -> TaskStatus:
    return task.status

# ❌ BAD
def process_task(task):
    return task.status
```

### Docstrings

All public classes and methods must have docstrings:

```python
class MediaLibrary(IMediaLibrary):
    """Manages media import and metadata.
    
    This service centralizes all video access.
    No other module accesses files directly.
    """
    
    def import_episode(self, file_path: Path) -> int:
        """Import episode to library.
        
        Args:
            file_path: Path to episode file
            
        Returns:
            Episode ID
            
        Raises:
            MediaProcessingException: If import fails
        """
```

### Naming Conventions

```python
# Classes: PascalCase
class ProjectManager:
    pass

# Functions/methods: snake_case
def create_project(name: str):
    pass

# Constants: UPPER_SNAKE_CASE
MAX_WORKERS = 4

# Private: _leading_underscore
self._internal_state = None
```

## Testing

Write tests for all new features:

```bash
# Run tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

**Test template**:

```python
import unittest
from application.task_management import Task, TaskStatus

class TestTask(unittest.TestCase):
    def setUp(self):
        """Setup test fixtures."""
        self.task = Task(name="Test")
    
    def test_task_creation(self):
        """Test task is created correctly."""
        self.assertEqual(self.task.name, "Test")
        self.assertEqual(self.task.status, TaskStatus.PENDING)
```

## Performance

### No UI Blocking

```python
# ❌ BAD - Blocks UI
def on_import_button_clicked():
    media_library.import_episode(file_path)  # Blocks UI!

# ✅ GOOD - Uses task queue
def on_import_button_clicked():
    task = task_queue.add_task("Import Episode", priority=TaskPriority.HIGH)
    task_scheduler.submit_task(task, lambda t: media_library.import_episode(file_path))
```

### Database Queries

```python
# ❌ BAD - N+1 query problem
for episode in episodes:
    metadata = repository.find_by_id(episode['id'])  # Query in loop!

# ✅ GOOD - Single query
episodes = repository.find_all(limit=100)
```

## Logging

Use structured logging:

```python
import logging

logger = logging.getLogger(__name__)

# Different log levels
logger.debug("Debug information")          # development
logger.info("Application started")        # key events
logger.warning("Deprecated function")     # potential issues
logger.error("Failed to import", exc_info=True)  # errors
```

## Dependencies

### Adding New Dependencies

1. Discuss in issue first
2. Update requirements.txt
3. Update CHANGELOG.md
4. Document why it's needed

### Preferred Libraries

```
UI:          PySide6 (Qt)
Database:    SQLite (dev), PostgreSQL (prod)
Testing:     pytest
Logging:     Python stdlib logging
Processing:  subprocess, threading
```

## Pull Request Process

1. Create feature branch: `git checkout -b feature/my-feature`
2. Write tests first (TDD encouraged)
3. Implement feature
4. Run tests: `pytest tests/`
5. Check code quality: `pylint`
6. Update documentation
7. Push and create PR

## Commit Messages

```
[CATEGORY] Brief description

Detailed explanation if needed.

Categories:
- FEAT: New feature
- FIX: Bug fix
- REFACTOR: Code reorganization
- DOCS: Documentation
- TEST: Test additions
- PERF: Performance improvement
- ARCH: Architectural changes
```

## Review Checklist

Before marking PR ready:

- [ ] Code follows style guidelines
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No circular dependencies introduced
- [ ] Layer separation maintained
- [ ] Performance impact considered
- [ ] Security implications reviewed

## Questions?

Open an issue for discussions!

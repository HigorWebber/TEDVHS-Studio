"""Unit tests for domain events."""

import pytest
from datetime import datetime
from domain.media.events import (
    MediaDiscoveredEvent, MediaValidatedEvent, MetadataExtractedEvent,
    DuplicateDetectedEvent, MediaImportedEvent, StateTransitionEvent,
    ProcessingFailedEvent, ImportStartedEvent, ImportCompletedEvent
)
from domain.media.processing_status import ProcessingStatus


class TestMediaDiscoveredEvent:
    """Tests for MediaDiscoveredEvent."""
    
    def test_event_creation(self):
        """Test creating a discovery event."""
        event = MediaDiscoveredEvent(
            file_hash="a" * 64,
            file_path="/path/to/video.mp4",
            file_name="video.mp4",
            file_size=1024
        )
        
        assert event.file_hash == "a" * 64
        assert event.event_name == "media.discovered"
        assert event.timestamp is not None
        assert event.event_id is not None


class TestStateTransitionEvent:
    """Tests for StateTransitionEvent."""
    
    def test_event_creation(self):
        """Test creating a state transition event."""
        event = StateTransitionEvent(
            file_hash="a" * 64,
            from_status=ProcessingStatus.DISCOVERED,
            to_status=ProcessingStatus.VALIDATED
        )
        
        assert event.file_hash == "a" * 64
        assert event.from_status == ProcessingStatus.DISCOVERED
        assert event.to_status == ProcessingStatus.VALIDATED
        assert event.event_name == "state.transitioned"


class TestProcessingFailedEvent:
    """Tests for ProcessingFailedEvent."""
    
    def test_event_creation(self):
        """Test creating a failure event."""
        event = ProcessingFailedEvent(
            file_hash="a" * 64,
            error_message="Test error",
            stage="validation",
            attempt_number=1
        )
        
        assert event.error_message == "Test error"
        assert event.stage == "validation"
        assert event.attempt_number == 1
        assert event.event_name == "processing.failed"


class TestImportEvents:
    """Tests for import lifecycle events."""
    
    def test_import_started(self):
        """Test import started event."""
        event = ImportStartedEvent(
            import_session_id="session-123",
            folder_path="/path/to/folder"
        )
        
        assert event.import_session_id == "session-123"
        assert event.event_name == "import.started"
    
    def test_import_completed(self):
        """Test import completed event."""
        event = ImportCompletedEvent(
            import_session_id="session-123",
            total_files=100,
            imported_files=95,
            duplicate_files=3,
            failed_files=2,
            total_size_bytes=1024 * 1024 * 1024,
            duration_seconds=60.5
        )
        
        assert event.total_files == 100
        assert event.imported_files == 95
        assert event.event_name == "import.completed"

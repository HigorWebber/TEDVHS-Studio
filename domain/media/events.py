"""Domain events for media processing.

Domain events represent significant things that happen in the domain.
They are immutable, occur in the past (named in past tense),
and carry business-relevant information.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import uuid4

from domain.media.processing_status import ProcessingStatus


class DomainEvent(ABC):
    """Base class for all domain events.
    
    Events are immutable, timestamped, and uniquely identified.
    """
    
    @property
    @abstractmethod
    def event_name(self) -> str:
        """Get event name for identification."""
        pass


@dataclass(frozen=True)
class MediaDiscoveredEvent(DomainEvent):
    """Emitted when a media file is discovered during scanning."""
    
    file_hash: str
    file_path: str
    file_name: str
    file_size: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "media.discovered"


@dataclass(frozen=True)
class MediaValidatedEvent(DomainEvent):
    """Emitted when a media file passes validation."""
    
    file_hash: str
    file_path: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "media.validated"


@dataclass(frozen=True)
class MetadataExtractedEvent(DomainEvent):
    """Emitted when metadata is successfully extracted."""
    
    file_hash: str
    duration: float
    fps: float
    resolution: str
    codec_video: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "metadata.extracted"


@dataclass(frozen=True)
class DuplicateDetectedEvent(DomainEvent):
    """Emitted when a duplicate file is detected."""
    
    file_hash: str
    original_hash: str
    file_path: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "duplicate.detected"


@dataclass(frozen=True)
class MediaImportedEvent(DomainEvent):
    """Emitted when a media file is successfully imported."""
    
    media_id: int
    file_hash: str
    file_path: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "media.imported"


@dataclass(frozen=True)
class StateTransitionEvent(DomainEvent):
    """Emitted when a media file changes processing state."""
    
    file_hash: str
    from_status: ProcessingStatus
    to_status: ProcessingStatus
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def event_name(self) -> str:
        return "state.transitioned"


@dataclass(frozen=True)
class ProcessingFailedEvent(DomainEvent):
    """Emitted when media processing fails."""
    
    file_hash: str
    error_message: str
    stage: str  # e.g., "validation", "metadata_extraction"
    attempt_number: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "processing.failed"


@dataclass(frozen=True)
class ImportStartedEvent(DomainEvent):
    """Emitted when a library import operation starts."""
    
    import_session_id: str
    folder_path: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "import.started"


@dataclass(frozen=True)
class ImportCompletedEvent(DomainEvent):
    """Emitted when a library import operation completes."""
    
    import_session_id: str
    total_files: int
    imported_files: int
    duplicate_files: int
    failed_files: int
    total_size_bytes: int
    duration_seconds: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    
    @property
    def event_name(self) -> str:
        return "import.completed"

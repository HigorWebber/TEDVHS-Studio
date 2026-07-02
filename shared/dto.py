"""Data Transfer Objects (DTOs)."""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class TaskDTO:
    """DTO for task information."""
    id: str
    name: str
    status: str
    progress: float
    created_at: datetime
    updated_at: datetime
    elapsed_seconds: float
    estimated_seconds: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class EventDTO:
    """DTO for event information."""
    event_type: str
    timestamp: datetime
    data: Dict[str, Any]
    source: Optional[str] = None


@dataclass
class MediaMetadataDTO:
    """DTO for media file metadata."""
    duration: float
    fps: float
    codec: str
    width: int
    height: int
    bitrate: int
    file_size: int
    has_audio: bool
    audio_codec: Optional[str] = None

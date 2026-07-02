"""Type definitions and aliases."""

from typing import TypeVar, Generic, Callable, Any, Dict
from enum import Enum


# Generic types
T = TypeVar('T')
U = TypeVar('U')


class TaskStatus(Enum):
    """Status of a background task."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(Enum):
    """Event types in the system."""
    # Project events
    PROJECT_CREATED = "project.created"
    PROJECT_OPENED = "project.opened"
    PROJECT_SAVED = "project.saved"
    PROJECT_DELETED = "project.deleted"
    
    # Episode events
    EPISODE_IMPORTED = "episode.imported"
    EPISODE_PROCESSED = "episode.processed"
    EPISODE_DELETED = "episode.deleted"
    
    # Clip events
    CLIP_CREATED = "clip.created"
    CLIP_EXPORTED = "clip.exported"
    CLIP_DELETED = "clip.deleted"
    
    # Scene detection
    SCENE_DETECTION_STARTED = "scene.detection_started"
    SCENE_DETECTION_COMPLETED = "scene.detection_completed"
    SCENES_DETECTED = "scenes.detected"
    
    # Thumbnail events
    THUMBNAIL_GENERATED = "thumbnail.generated"
    
    # Task events
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"


class MediaMetadata(Dict[str, Any]):
    """Dictionary containing media file metadata.
    
    Keys:
        duration: Duration in seconds
        fps: Frames per second
        codec: Video codec name
        resolution: Tuple of (width, height)
        bitrate: Bitrate in kbps
        file_size: File size in bytes
        audio: Audio information
    """
    pass
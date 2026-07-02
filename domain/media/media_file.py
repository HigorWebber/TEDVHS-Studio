"""Refactored MediaFile with Value Objects.

Decomposes large entity into cohesive value objects.
Maintains aggregate root pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import (
    FileHash, MediaId, FileSize, Duration, Resolution, AspectRatio
)


@dataclass
class FileInfo:
    """Value object for file-related information."""
    
    file_path: str
    file_name: str
    file_name_clean: str
    file_extension: str
    file_size: FileSize
    file_created_at: Optional[datetime] = None
    file_modified_at: Optional[datetime] = None
    
    def get_path(self) -> Path:
        """Get file path as Path object."""
        return Path(self.file_path)


@dataclass
class VideoInfo:
    """Value object for video-related metadata."""
    
    duration: Duration
    fps: float = 0.0
    resolution: Optional[Resolution] = None
    aspect_ratio: Optional[AspectRatio] = None
    codec_video: str = ""
    bitrate: int = 0
    num_streams: int = 0


@dataclass
class AudioInfo:
    """Value object for audio-related metadata."""
    
    codec_audio: Optional[str] = None
    audio_channels: int = 0
    language_code: Optional[str] = None


@dataclass
class ProcessingInfo:
    """Value object for processing state tracking."""
    
    status: ProcessingStatus = ProcessingStatus.DISCOVERED
    import_date: datetime = field(default_factory=datetime.utcnow)
    last_scan_date: Optional[datetime] = None
    
    metadata_version: int = 0
    scenes_version: int = 0
    thumbnails_version: int = 0
    clips_version: int = 0
    
    processing_attempts: int = 0
    last_error: Optional[str] = None


@dataclass
class HashInfo:
    """Value object for hash and duplicate tracking."""
    
    file_hash: FileHash
    is_duplicate: bool = False
    duplicate_of_hash: Optional[FileHash] = None


@dataclass
class MediaFile:
    """Media file aggregate root.
    
    Central entity representing a media file in the system.
    Decomposes into value objects for better organization.
    """
    
    # Identifier
    id: Optional[MediaId] = None
    
    # Value objects
    file_info: FileInfo = field(default_factory=lambda: FileInfo(
        file_path="", file_name="", file_name_clean="",
        file_extension="", file_size=FileSize(0)
    ))
    video_info: VideoInfo = field(default_factory=lambda: VideoInfo(
        duration=Duration(0.0)
    ))
    audio_info: AudioInfo = field(default_factory=AudioInfo)
    processing_info: ProcessingInfo = field(default_factory=ProcessingInfo)
    hash_info: HashInfo = field(default_factory=lambda: HashInfo(
        file_hash=FileHash("0" * 64)
    ))
    
    # Extensibility
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Convenience methods
    def get_path(self) -> Path:
        """Get file path as Path object."""
        return self.file_info.get_path()
    
    def is_ready(self) -> bool:
        """Check if media is ready for use."""
        return self.processing_info.status == ProcessingStatus.READY
    
    def has_error(self) -> bool:
        """Check if media has processing error."""
        return self.processing_info.status == ProcessingStatus.FAILED
    
    def is_pending_work(self) -> bool:
        """Check if media has pending work."""
        return ProcessingStatus.is_pending_work(self.processing_info.status)
    
    def is_processing(self) -> bool:
        """Check if media is currently processing."""
        return ProcessingStatus.is_processing(self.processing_info.status)
    
    def is_finished(self) -> bool:
        """Check if media processing is finished."""
        return ProcessingStatus.is_terminal(self.processing_info.status)
    
    def requires_reprocessing(self) -> bool:
        """Check if media requires reprocessing."""
        return self.processing_info.status == ProcessingStatus.REPROCESS_REQUIRED
    
    def mark_as_duplicate(self, original_hash: FileHash) -> None:
        """Mark this file as duplicate.
        
        Args:
            original_hash: Hash of the original file
        """
        self.hash_info.is_duplicate = True
        self.hash_info.duplicate_of_hash = original_hash
        self.processing_info.status = ProcessingStatus.SKIPPED
    
    def increment_attempts(self) -> None:
        """Increment processing attempt counter."""
        self.processing_info.processing_attempts += 1
    
    def set_error(self, error_message: str) -> None:
        """Set error message.
        
        Args:
            error_message: Error description
        """
        self.processing_info.last_error = error_message
        self.processing_info.status = ProcessingStatus.FAILED
    
    def __repr__(self) -> str:
        return (f"MediaFile(hash={str(self.hash_info.file_hash)[:8]}..., "
                f"name={self.file_info.file_name}, "
                f"status={self.processing_info.status.value})")

"""Media file entity with complete metadata."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import uuid4

from domain.media.processing_status import ProcessingStatus


@dataclass
class MediaFile:
    """Represents a media file in the system.
    
    This is the central entity for the Media Library Engine.
    Each file has a unique SHA-256 hash as its permanent identifier.
    
    Attributes:
        id: Unique numeric ID (database primary key)
        file_hash: SHA-256 hash (permanent unique identifier)
        file_path: Full path to the media file
        file_name: File name with extension
        file_name_clean: File name without extension
        file_extension: File extension (lowercase, without dot)
        file_size: File size in bytes
        file_created_at: File creation timestamp
        file_modified_at: File last modification timestamp
        
        duration: Video duration in seconds
        fps: Frames per second
        resolution: Resolution string (e.g., "1920x1080")
        aspect_ratio: Aspect ratio (e.g., "16:9")
        codec_video: Video codec name
        codec_audio: Audio codec name
        bitrate: Bitrate in kbps
        audio_channels: Number of audio channels
        num_streams: Total number of streams
        
        processing_status: Current processing status
        import_date: When file was imported
        last_scan_date: When file was last scanned
        
        metadata_version: Metadata extraction version
        scenes_version: Scene detection version
        thumbnails_version: Thumbnail generation version
        clips_version: Clip extraction version
        
        processing_attempts: Number of processing attempts
        last_error: Last error message if failed
        
        is_duplicate: True if duplicate of another file
        duplicate_of_hash: Hash of original if duplicate
        
        custom_metadata: Custom user-defined data
    """
    
    # Core identifiers
    id: Optional[int] = None
    file_hash: str = field(default_factory=lambda: str(uuid4()))
    
    # File information
    file_path: str = ""
    file_name: str = ""
    file_name_clean: str = ""
    file_extension: str = ""
    file_size: int = 0
    file_created_at: Optional[datetime] = None
    file_modified_at: Optional[datetime] = None
    
    # Media metadata
    duration: float = 0.0
    fps: float = 0.0
    resolution: str = ""
    aspect_ratio: str = ""
    codec_video: str = ""
    codec_audio: str = ""
    bitrate: int = 0
    audio_channels: int = 0
    num_streams: int = 0
    
    # Processing state
    processing_status: ProcessingStatus = ProcessingStatus.DISCOVERED
    import_date: datetime = field(default_factory=datetime.utcnow)
    last_scan_date: Optional[datetime] = None
    
    # Version tracking
    metadata_version: int = 0
    scenes_version: int = 0
    thumbnails_version: int = 0
    clips_version: int = 0
    
    # Error tracking
    processing_attempts: int = 0
    last_error: Optional[str] = None
    
    # Duplicate detection
    is_duplicate: bool = False
    duplicate_of_hash: Optional[str] = None
    
    # Extensibility
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_path(self) -> Path:
        """Get file path as Path object.
        
        Returns:
            Path object
        """
        return Path(self.file_path)
    
    def is_ready(self) -> bool:
        """Check if media is ready for use.
        
        Returns:
            True if in READY status
        """
        return self.processing_status == ProcessingStatus.READY
    
    def has_error(self) -> bool:
        """Check if media has error.
        
        Returns:
            True if in FAILED status
        """
        return self.processing_status == ProcessingStatus.FAILED
    
    def is_pending_work(self) -> bool:
        """Check if media has pending work.
        
        Returns:
            True if has unfinished processing
        """
        return ProcessingStatus.is_pending_work(self.processing_status)
    
    def increment_attempts(self) -> None:
        """Increment processing attempt counter."""
        self.processing_attempts += 1
    
    def mark_as_duplicate(self, original_hash: str) -> None:
        """Mark this file as duplicate.
        
        Args:
            original_hash: Hash of the original file
        """
        self.is_duplicate = True
        self.duplicate_of_hash = original_hash
        self.processing_status = ProcessingStatus.SKIPPED
    
    def __repr__(self) -> str:
        return (f"MediaFile(hash={self.file_hash[:8]}..., "
                f"name={self.file_name}, "
                f"status={self.processing_status.value})")

"""Data Transfer Objects for media metadata."""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class MediaMetadataDTO:
    """DTO for complete media metadata.
    
    Used for transferring metadata between layers.
    """
    
    # Basic file info
    file_name: str
    file_size: int
    file_extension: str
    
    # Video properties
    duration: float
    fps: float
    resolution: str
    aspect_ratio: str
    codec_video: str
    bitrate: int
    num_streams: int
    
    # Audio properties
    codec_audio: Optional[str] = None
    audio_channels: int = 0
    
    # Optional
    language_code: Optional[str] = None


@dataclass
class ImportSummaryDTO:
    """DTO for import operation summary.
    
    Used to report results of import operations.
    """
    
    folders_scanned: int
    files_found: int
    files_valid: int
    files_duplicate: int
    files_ignored: int
    files_failed: int
    total_size_bytes: int
    total_duration_seconds: float
    processing_time_seconds: float
    
    def files_imported(self) -> int:
        """Get count of successfully imported files.
        
        Returns:
            Count of imported files
        """
        return self.files_valid
    
    def success_rate(self) -> float:
        """Calculate success rate percentage.
        
        Returns:
            Success rate 0-100
        """
        if self.files_found == 0:
            return 0.0
        return (self.files_valid / self.files_found) * 100
    
    def average_speed_mbps(self) -> float:
        """Calculate average processing speed.
        
        Returns:
            Speed in MB/s
        """
        if self.processing_time_seconds == 0:
            return 0.0
        total_mb = self.total_size_bytes / (1024 * 1024)
        return total_mb / self.processing_time_seconds

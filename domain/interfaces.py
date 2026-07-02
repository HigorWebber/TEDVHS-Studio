"""Domain interfaces (contracts) for the system."""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from pathlib import Path

from shared.dto import MediaMetadataDTO


class IRepository(ABC):
    """Interface for data repository operations."""
    
    @abstractmethod
    def find_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Find record by ID."""
        pass
    
    @abstractmethod
    def find_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """Find all records."""
        pass
    
    @abstractmethod
    def create(self, data: Dict[str, Any]) -> int:
        """Create new record."""
        pass
    
    @abstractmethod
    def update(self, item_id: int, data: Dict[str, Any]) -> bool:
        """Update existing record."""
        pass
    
    @abstractmethod
    def delete(self, item_id: int) -> bool:
        """Delete record."""
        pass


class IMediaScanner(ABC):
    """Interface for scanning media file metadata."""
    
    @abstractmethod
    def scan_file(self, file_path: Path) -> MediaMetadataDTO:
        """Scan media file and extract metadata.
        
        Args:
            file_path: Path to media file
            
        Returns:
            Media metadata
            
        Raises:
            MediaProcessingException: If file cannot be scanned
        """
        pass
    
    @abstractmethod
    def is_supported(self, file_path: Path) -> bool:
        """Check if file format is supported.
        
        Args:
            file_path: Path to media file
            
        Returns:
            True if supported
        """
        pass


class IClipExporter(ABC):
    """Interface for exporting video clips."""
    
    @abstractmethod
    def export_clip(self, source_path: Path, output_path: Path,
                   start_time: float, end_time: float) -> bool:
        """Export a clip from source video.
        
        Args:
            source_path: Source video path
            output_path: Output clip path
            start_time: Start time in seconds
            end_time: End time in seconds
            
        Returns:
            True if successful
            
        Raises:
            MediaProcessingException: If export fails
        """
        pass


class ISceneDetector(ABC):
    """Interface for detecting scene changes in video."""
    
    @abstractmethod
    def detect_scenes(self, file_path: Path, threshold: float = 0.5) -> List[float]:
        """Detect scene changes.
        
        Args:
            file_path: Path to video file
            threshold: Detection threshold (0-1)
            
        Returns:
            List of scene change timestamps in seconds
            
        Raises:
            MediaProcessingException: If detection fails
        """
        pass


class IThumbnailGenerator(ABC):
    """Interface for generating video thumbnails."""
    
    @abstractmethod
    def generate_thumbnail(self, video_path: Path, output_path: Path,
                          timestamp: float, width: int = 320, height: int = 180) -> bool:
        """Generate thumbnail from video.
        
        Args:
            video_path: Source video path
            output_path: Output thumbnail path
            timestamp: Timestamp in seconds
            width: Thumbnail width
            height: Thumbnail height
            
        Returns:
            True if successful
            
        Raises:
            MediaProcessingException: If generation fails
        """
        pass


class IMediaLibrary(ABC):
    """Interface for media library operations."""
    
    @abstractmethod
    def import_episode(self, file_path: Path, anime_id: int) -> int:
        """Import episode to library.
        
        Args:
            file_path: Path to episode file
            anime_id: Associated anime ID
            
        Returns:
            Episode ID
            
        Raises:
            MediaProcessingException: If import fails
        """
        pass
    
    @abstractmethod
    def get_episode_metadata(self, episode_id: int) -> Optional[Dict[str, Any]]:
        """Get episode metadata.
        
        Args:
            episode_id: Episode ID
            
        Returns:
            Episode metadata or None
        """
        pass
    
    @abstractmethod
    def list_episodes(self, anime_id: int) -> List[Dict[str, Any]]:
        """List all episodes for anime.
        
        Args:
            anime_id: Anime ID
            
        Returns:
            List of episodes
        """
        pass


class IAIProvider(ABC):
    """Interface for AI service providers (prepared for future use)."""
    
    @abstractmethod
    def process(self, input_data: Any) -> Any:
        """Process data through AI model.
        
        Args:
            input_data: Input to process
            
        Returns:
            Processed result
        """
        pass

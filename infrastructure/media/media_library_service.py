"""Media library service for video import and metadata management."""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from domain.interfaces import IMediaScanner, IMediaLibrary
from infrastructure.persistence.repositories import IRepository
from shared.exceptions import MediaProcessingException
from shared.types import EventType


logger = logging.getLogger('processing')


class MediaLibraryService(IMediaLibrary):
    """Manages media import, storage, and metadata.
    
    Centralizes all video access and processing. No other module
    should directly access video files.
    """
    
    def __init__(self, media_scanner: IMediaScanner, episode_repository: IRepository,
                 media_storage_path: Path):
        """Initialize media library service.
        
        Args:
            media_scanner: Media scanner implementation
            episode_repository: Episode data repository
            media_storage_path: Base path for stored media
        """
        self.media_scanner = media_scanner
        self.episode_repo = episode_repository
        self.media_storage_path = Path(media_storage_path)
        self.media_storage_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"MediaLibraryService initialized with storage: {self.media_storage_path}")
    
    def import_episode(self, file_path: Path, anime_id: int,
                      episode_number: int, title: Optional[str] = None) -> int:
        """Import episode to library.
        
        Process:
        1. Validate file
        2. Scan metadata
        3. Create storage directory
        4. Copy/move file
        5. Store metadata in database
        6. Emit event
        
        Args:
            file_path: Path to source episode file
            anime_id: Associated anime ID
            episode_number: Episode number
            title: Episode title (optional)
            
        Returns:
            Episode ID
            
        Raises:
            MediaProcessingException: If import fails
        """
        try:
            # Validate file exists
            if not file_path.exists():
                raise MediaProcessingException(f"File not found: {file_path}")
            
            # Check if format is supported
            if not self.media_scanner.is_supported(file_path):
                raise MediaProcessingException(f"Unsupported format: {file_path}")
            
            logger.info(f"Starting import: {file_path}")
            
            # Scan metadata
            metadata = self.media_scanner.scan_file(file_path)
            logger.debug(f"Metadata scanned: {metadata}")
            
            # Create storage directory
            storage_dir = self._get_episode_storage_path(anime_id, episode_number)
            storage_dir.mkdir(parents=True, exist_ok=True)
            
            # Store file
            stored_path = storage_dir / file_path.name
            import shutil
            shutil.copy2(file_path, stored_path)
            logger.info(f"File stored: {stored_path}")
            
            # Store metadata in database
            episode_data = {
                "anime_id": anime_id,
                "episode_number": episode_number,
                "title": title,
                "file_path": str(stored_path),
                "duration": metadata.duration,
                "fps": metadata.fps,
                "codec": metadata.codec,
                "width": metadata.width,
                "height": metadata.height,
                "bitrate": metadata.bitrate,
                "file_size": metadata.file_size,
                "has_audio": metadata.has_audio,
                "audio_codec": metadata.audio_codec,
                "created_at": datetime.utcnow().isoformat(),
            }
            
            episode_id = self.episode_repo.create(episode_data)
            logger.info(f"Episode imported (ID: {episode_id})")
            
            return episode_id
            
        except MediaProcessingException:
            raise
        except Exception as e:
            logger.error(f"Episode import failed: {e}", exc_info=True)
            raise MediaProcessingException(f"Failed to import episode: {e}")
    
    def get_episode_metadata(self, episode_id: int) -> Optional[Dict[str, Any]]:
        """Get episode metadata.
        
        Args:
            episode_id: Episode ID
            
        Returns:
            Episode metadata or None
        """
        try:
            return self.episode_repo.find_by_id(episode_id)
        except Exception as e:
            logger.error(f"Failed to get episode metadata: {e}", exc_info=True)
            return None
    
    def list_episodes(self, anime_id: int) -> List[Dict[str, Any]]:
        """List all episodes for anime.
        
        Args:
            anime_id: Anime ID
            
        Returns:
            List of episodes
        """
        try:
            # Note: This is a simplified version.
            # Real implementation would query with WHERE anime_id = ?
            all_episodes = self.episode_repo.find_all()
            return [e for e in all_episodes if e.get('anime_id') == anime_id]
        except Exception as e:
            logger.error(f"Failed to list episodes: {e}", exc_info=True)
            return []
    
    def get_episode_file_path(self, episode_id: int) -> Optional[Path]:
        """Get file path for episode.
        
        Args:
            episode_id: Episode ID
            
        Returns:
            File path or None if not found
        """
        episode = self.get_episode_metadata(episode_id)
        if episode and 'file_path' in episode:
            return Path(episode['file_path'])
        return None
    
    def _get_episode_storage_path(self, anime_id: int, episode_number: int) -> Path:
        """Get storage path for episode.
        
        Args:
            anime_id: Anime ID
            episode_number: Episode number
            
        Returns:
            Storage directory path
        """
        return self.media_storage_path / f"anime_{anime_id}" / f"episode_{episode_number}"
    
    def validate_file_exists(self, episode_id: int) -> bool:
        """Verify episode file still exists.
        
        Args:
            episode_id: Episode ID
            
        Returns:
            True if file exists
        """
        file_path = self.get_episode_file_path(episode_id)
        return file_path and file_path.exists() if file_path else False

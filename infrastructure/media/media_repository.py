"""Media repository for data persistence."""

import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from domain.media.media_file import MediaFile
from domain.media.value_objects import FileHash, MediaId
from domain.media.processing_status import ProcessingStatus


logger = logging.getLogger(__name__)


class IMediaRepository:
    """Interface for media persistence."""
    
    def add(self, media: MediaFile) -> MediaFile:
        """Add media file to repository."""
        raise NotImplementedError
    
    def update(self, media: MediaFile) -> None:
        """Update media file in repository."""
        raise NotImplementedError
    
    def find_by_id(self, media_id: MediaId) -> Optional[MediaFile]:
        """Find media by ID."""
        raise NotImplementedError
    
    def find_by_hash(self, file_hash: FileHash) -> Optional[MediaFile]:
        """Find media by hash."""
        raise NotImplementedError
    
    def find_by_status(self, status: ProcessingStatus,
                      limit: int = 100) -> List[MediaFile]:
        """Find media by processing status."""
        raise NotImplementedError
    
    def find_all(self, limit: int = 100, offset: int = 0) -> List[MediaFile]:
        """Find all media files."""
        raise NotImplementedError


class InMemoryMediaRepository(IMediaRepository):
    """In-memory implementation for testing and development."""
    
    def __init__(self):
        """Initialize repository."""
        self._media: Dict[str, MediaFile] = {}
        self._by_hash: Dict[str, MediaFile] = {}
        self._next_id = 1
        logger.info("InMemoryMediaRepository initialized")
    
    def add(self, media: MediaFile) -> MediaFile:
        """Add media file."""
        # Assign ID if not present
        if media.id is None:
            media.id = MediaId(self._next_id)
            self._next_id += 1
        
        # Store by ID and hash
        media_id_str = str(media.id.value)
        self._media[media_id_str] = media
        self._by_hash[str(media.hash_info.file_hash)] = media
        
        logger.debug(f"Added media: {media.id}")
        return media
    
    def update(self, media: MediaFile) -> None:
        """Update media file."""
        if media.id is None:
            raise ValueError("Cannot update media without ID")
        
        media_id_str = str(media.id.value)
        if media_id_str not in self._media:
            raise ValueError(f"Media not found: {media.id}")
        
        self._media[media_id_str] = media
        logger.debug(f"Updated media: {media.id}")
    
    def find_by_id(self, media_id: MediaId) -> Optional[MediaFile]:
        """Find media by ID."""
        return self._media.get(str(media_id.value))
    
    def find_by_hash(self, file_hash: FileHash) -> Optional[MediaFile]:
        """Find media by hash."""
        return self._by_hash.get(str(file_hash))
    
    def find_by_status(self, status: ProcessingStatus,
                      limit: int = 100) -> List[MediaFile]:
        """Find media by status."""
        result = [
            m for m in self._media.values()
            if m.processing_info.status == status
        ]
        return result[:limit]
    
    def find_all(self, limit: int = 100, offset: int = 0) -> List[MediaFile]:
        """Find all media."""
        all_media = list(self._media.values())
        return all_media[offset:offset + limit]

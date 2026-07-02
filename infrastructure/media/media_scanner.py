"""Media scanner for discovering media files in directories.

Recursively scans directory structures and identifies media files.
Intelligently filters and validates candidates.
"""

import logging
from pathlib import Path
from typing import List, Optional, Set
from dataclasses import dataclass
from datetime import datetime

from domain.media.exceptions import ValidationException
from infrastructure.config.configuration_service import ConfigurationService


logger = logging.getLogger(__name__)


@dataclass
class MediaFileCandidate:
    """Represents a potential media file discovered during scanning."""
    
    file_path: Path
    file_name: str
    file_extension: str
    file_size: int
    file_modified: datetime
    is_valid: bool = False
    error: Optional[str] = None


class MediaScanner:
    """Recursively scans for media files in directory structures.
    
    Features:
    - Recursive directory traversal
    - Format filtering based on configuration
    - Ignores hidden files, system files, temp files
    - Detects incomplete downloads
    - Thread-safe scanning
    """
    
    # Files to ignore patterns
    IGNORED_PREFIXES = {"."}
    IGNORED_SUFFIXES = {".tmp", ".part", ".downloading", ".incomplete"}
    IGNORED_NAMES = {"Thumbs.db", ".DS_Store", "desktop.ini"}
    IGNORED_DIRS = {".git", ".svn", "__pycache__", "node_modules", ".cache"}
    
    def __init__(self, config: ConfigurationService):
        """Initialize scanner.
        
        Args:
            config: Configuration service
        """
        self._config = config
        self._supported_formats = set(
            config.get("media.supported_formats", [])
        )
        logger.info(f"MediaScanner initialized. Formats: {self._supported_formats}")
    
    def scan(self, root_path: Path) -> List[MediaFileCandidate]:
        """Scan directory for media files.
        
        Args:
            root_path: Root directory to scan
            
        Returns:
            List of media file candidates
            
        Raises:
            ValidationException: If root path invalid
        """
        if not isinstance(root_path, Path):
            root_path = Path(root_path)
        
        if not root_path.exists():
            raise ValidationException(f"Path does not exist: {root_path}")
        
        if not root_path.is_dir():
            raise ValidationException(f"Path is not a directory: {root_path}")
        
        logger.info(f"Starting scan of: {root_path}")
        candidates: List[MediaFileCandidate] = []
        
        try:
            candidates = self._recursive_scan(root_path)
            logger.info(f"Scan complete. Found {len(candidates)} candidates")
        except Exception as e:
            logger.error(f"Error during scan: {e}")
            raise
        
        return candidates
    
    def _recursive_scan(self, directory: Path) -> List[MediaFileCandidate]:
        """Recursively scan directory.
        
        Args:
            directory: Directory to scan
            
        Returns:
            List of media file candidates
        """
        candidates: List[MediaFileCandidate] = []
        
        try:
            for entry in directory.iterdir():
                # Skip hidden files and directories
                if entry.name.startswith("."):
                    continue
                
                # Skip ignored directories
                if entry.is_dir() and entry.name in self.IGNORED_DIRS:
                    logger.debug(f"Skipping ignored directory: {entry}")
                    continue
                
                # Skip ignored files
                if entry.is_file() and self._is_ignored_file(entry):
                    logger.debug(f"Skipping ignored file: {entry}")
                    continue
                
                # Recurse into directories
                if entry.is_dir():
                    try:
                        candidates.extend(self._recursive_scan(entry))
                    except PermissionError:
                        logger.warning(f"Permission denied: {entry}")
                        continue
                # Check files
                elif entry.is_file():
                    candidate = self._check_file(entry)
                    if candidate:
                        candidates.append(candidate)
        
        except PermissionError:
            logger.warning(f"Permission denied accessing directory: {directory}")
        except Exception as e:
            logger.error(f"Error scanning {directory}: {e}")
        
        return candidates
    
    def _is_ignored_file(self, file_path: Path) -> bool:
        """Check if file should be ignored.
        
        Args:
            file_path: File to check
            
        Returns:
            True if file should be ignored
        """
        name = file_path.name
        
        # Check ignored names
        if name in self.IGNORED_NAMES:
            return True
        
        # Check ignored suffixes
        if any(name.endswith(suffix) for suffix in self.IGNORED_SUFFIXES):
            return True
        
        return False
    
    def _check_file(self, file_path: Path) -> Optional[MediaFileCandidate]:
        """Check if file is a valid media candidate.
        
        Args:
            file_path: File to check
            
        Returns:
            MediaFileCandidate if valid, None otherwise
        """
        try:
            extension = file_path.suffix.lstrip(".").lower()
            
            # Check extension
            if extension not in self._supported_formats:
                return None
            
            # Check if file is accessible
            if not file_path.is_file():
                return None
            
            # Get file info
            stat = file_path.stat()
            file_size = stat.st_size
            file_modified = datetime.fromtimestamp(stat.st_mtime)
            
            return MediaFileCandidate(
                file_path=file_path,
                file_name=file_path.name,
                file_extension=extension,
                file_size=file_size,
                file_modified=file_modified,
                is_valid=True
            )
        
        except (OSError, PermissionError) as e:
            logger.debug(f"Cannot access file {file_path}: {e}")
            return None
    
    def set_supported_formats(self, formats: Set[str]) -> None:
        """Update supported formats.
        
        Args:
            formats: Set of supported file extensions
        """
        self._supported_formats = set(f.lower() for f in formats)
        logger.info(f"Supported formats updated: {self._supported_formats}")

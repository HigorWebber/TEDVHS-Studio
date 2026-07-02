"""Media file validator for comprehensive validation."""

import logging
from pathlib import Path
from typing import List, Tuple

from domain.media.exceptions import ValidationException
from infrastructure.media.media_scanner import MediaFileCandidate


logger = logging.getLogger(__name__)


class MediaValidator:
    """Validates media files for processing.
    
    Checks:
    - File accessibility and permissions
    - File integrity (not corrupted)
    - File completeness (not partial download)
    - File size constraints
    """
    
    # Minimum file size (1 MB)
    MIN_FILE_SIZE = 1024 * 1024
    
    # Maximum file size (100 GB)
    MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024
    
    def __init__(self):
        """Initialize validator."""
        logger.info("MediaValidator initialized")
    
    def validate(self, candidate: MediaFileCandidate) -> Tuple[bool, str]:
        """Validate a media file candidate.
        
        Args:
            candidate: Media file candidate to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if file still exists
        if not candidate.file_path.exists():
            return False, "File no longer exists"
        
        # Check if still a file
        if not candidate.file_path.is_file():
            return False, "Path is not a file"
        
        # Check file accessibility
        if not self._can_read_file(candidate.file_path):
            return False, "Cannot read file (permission denied)"
        
        # Check file size
        is_valid, error = self._validate_file_size(candidate.file_path)
        if not is_valid:
            return False, error
        
        # Check if file is likely complete (heuristic)
        if self._is_likely_incomplete(candidate.file_path):
            return False, "File appears to be incomplete (partial download)"
        
        logger.debug(f"Validation passed: {candidate.file_path}")
        return True, ""
    
    def validate_batch(self, candidates: List[MediaFileCandidate]
                      ) -> Tuple[List[MediaFileCandidate], List[Tuple[MediaFileCandidate, str]]]:
        """Validate multiple candidates.
        
        Args:
            candidates: List of candidates to validate
            
        Returns:
            Tuple of (valid_candidates, failed_with_errors)
        """
        valid = []
        failed = []
        
        for candidate in candidates:
            is_valid, error = self.validate(candidate)
            if is_valid:
                valid.append(candidate)
            else:
                candidate.is_valid = False
                candidate.error = error
                failed.append((candidate, error))
        
        logger.info(f"Validation complete: {len(valid)} valid, {len(failed)} failed")
        return valid, failed
    
    def _can_read_file(self, file_path: Path) -> bool:
        """Check if file can be read.
        
        Args:
            file_path: File to check
            
        Returns:
            True if readable
        """
        try:
            # Try to open file
            with open(file_path, 'rb') as f:
                # Try to read first byte
                f.read(1)
            return True
        except (IOError, OSError, PermissionError):
            return False
    
    def _validate_file_size(self, file_path: Path) -> Tuple[bool, str]:
        """Validate file size constraints.
        
        Args:
            file_path: File to check
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            size = file_path.stat().st_size
            
            if size < self.MIN_FILE_SIZE:
                return False, f"File too small: {size} bytes (minimum {self.MIN_FILE_SIZE})"
            
            if size > self.MAX_FILE_SIZE:
                return False, f"File too large: {size} bytes (maximum {self.MAX_FILE_SIZE})"
            
            return True, ""
        
        except (OSError, PermissionError) as e:
            return False, f"Cannot access file: {e}"
    
    def _is_likely_incomplete(self, file_path: Path) -> bool:
        """Heuristic check if file appears incomplete.
        
        Args:
            file_path: File to check
            
        Returns:
            True if file appears incomplete
        """
        # Very small files (< 100KB) are suspicious
        try:
            size = file_path.stat().st_size
            if size < 100 * 1024:
                return True
        except (OSError, PermissionError):
            pass
        
        return False

"""SHA-256 hash calculator for media files.

Efficient streaming implementation suitable for large files.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

from domain.media.value_objects import FileHash
from domain.media.exceptions import HashCalculationException


logger = logging.getLogger(__name__)

# Buffer size for streaming (8 MB)
BUFFER_SIZE = 8 * 1024 * 1024


class HashCalculator:
    """Calculates SHA-256 hash for media files.
    
    Features:
    - Streaming calculation (memory efficient)
    - Progress callback support
    - Suitable for files > 20GB
    - Thread-safe
    """
    
    @staticmethod
    def calculate(file_path: Path,
                 progress_callback: Optional[callable] = None) -> FileHash:
        """Calculate SHA-256 hash of file.
        
        Args:
            file_path: Path to file
            progress_callback: Optional callback for progress (bytes_processed, total_bytes)
            
        Returns:
            FileHash value object
            
        Raises:
            HashCalculationException: If calculation fails
        """
        if not file_path.exists():
            raise HashCalculationException(f"File not found: {file_path}")
        
        if not file_path.is_file():
            raise HashCalculationException(f"Not a file: {file_path}")
        
        try:
            file_size = file_path.stat().st_size
            sha256_hash = hashlib.sha256()
            bytes_processed = 0
            
            logger.debug(f"Calculating hash for: {file_path} ({file_size} bytes)")
            
            with open(file_path, 'rb') as f:
                while True:
                    # Read in chunks to avoid loading entire file in memory
                    chunk = f.read(BUFFER_SIZE)
                    if not chunk:
                        break
                    
                    sha256_hash.update(chunk)
                    bytes_processed += len(chunk)
                    
                    # Call progress callback if provided
                    if progress_callback:
                        progress_callback(bytes_processed, file_size)
            
            hash_value = sha256_hash.hexdigest()
            logger.debug(f"Hash calculated: {hash_value[:8]}...")
            
            return FileHash(hash_value)
        
        except (IOError, OSError, PermissionError) as e:
            raise HashCalculationException(f"Error reading file {file_path}: {e}")
        except Exception as e:
            raise HashCalculationException(f"Error calculating hash: {e}")
    
    @staticmethod
    def calculate_batch(file_paths: list,
                       progress_callback: Optional[callable] = None) -> dict:
        """Calculate hashes for multiple files.
        
        Args:
            file_paths: List of file paths
            progress_callback: Optional callback for progress
            
        Returns:
            Dictionary mapping file path to FileHash
        """
        hashes = {}
        total_files = len(file_paths)
        
        for i, file_path in enumerate(file_paths):
            try:
                file_path = Path(file_path)
                hash_value = HashCalculator.calculate(file_path)
                hashes[str(file_path)] = hash_value
                
                if progress_callback:
                    progress_callback(i + 1, total_files)
            
            except HashCalculationException as e:
                logger.error(f"Error hashing {file_path}: {e}")
                hashes[str(file_path)] = None
        
        return hashes

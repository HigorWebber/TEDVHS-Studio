"""Value Objects for media domain.

Value objects are immutable, comparable by value, and enforce constraints.
They prevent primitive obsession and add semantic meaning to the domain.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import hashlib
import re

from shared.exceptions import ValidationException


@dataclass(frozen=True)
class FileHash:
    """Immutable representation of a file's SHA-256 hash.
    
    Prevents treating hash as simple string.
    Enforces hash format and length validation.
    """
    
    value: str
    
    def __post_init__(self):
        """Validate hash format."""
        if not isinstance(self.value, str):
            raise ValidationException("Hash must be a string")
        if len(self.value) != 64:
            raise ValidationException("SHA-256 hash must be 64 characters")
        if not re.match(r'^[a-f0-9]{64}$', self.value.lower()):
            raise ValidationException("Invalid SHA-256 hash format")
    
    def __str__(self) -> str:
        return self.value
    
    def __repr__(self) -> str:
        return f"FileHash({self.value[:8]}...)"


@dataclass(frozen=True)
class MediaId:
    """Immutable representation of a media file's unique identifier.
    
    Database primary key wrapper.
    Prevents confusion with other ID types.
    """
    
    value: int
    
    def __post_init__(self):
        """Validate ID."""
        if not isinstance(self.value, int):
            raise ValidationException("MediaId must be an integer")
        if self.value < 0:
            raise ValidationException("MediaId must be non-negative")
    
    def __str__(self) -> str:
        return str(self.value)
    
    def __repr__(self) -> str:
        return f"MediaId({self.value})"


@dataclass(frozen=True)
class ProjectId:
    """Immutable representation of a project's unique identifier."""
    
    value: int
    
    def __post_init__(self):
        """Validate ID."""
        if not isinstance(self.value, int):
            raise ValidationException("ProjectId must be an integer")
        if self.value < 0:
            raise ValidationException("ProjectId must be non-negative")


@dataclass(frozen=True)
class FileSize:
    """Immutable representation of file size in bytes.
    
    Provides convenience methods for size conversion.
    """
    
    bytes: int
    
    def __post_init__(self):
        """Validate size."""
        if not isinstance(self.bytes, int):
            raise ValidationException("FileSize must be in bytes (integer)")
        if self.bytes < 0:
            raise ValidationException("FileSize cannot be negative")
    
    @property
    def megabytes(self) -> float:
        """Get size in megabytes."""
        return self.bytes / (1024 * 1024)
    
    @property
    def gigabytes(self) -> float:
        """Get size in gigabytes."""
        return self.bytes / (1024 * 1024 * 1024)
    
    def __str__(self) -> str:
        if self.gigabytes > 1:
            return f"{self.gigabytes:.2f} GB"
        return f"{self.megabytes:.2f} MB"


@dataclass(frozen=True)
class Duration:
    """Immutable representation of video duration in seconds.
    
    Provides convenience methods for time formatting.
    """
    
    seconds: float
    
    def __post_init__(self):
        """Validate duration."""
        if not isinstance(self.seconds, (int, float)):
            raise ValidationException("Duration must be numeric")
        if self.seconds < 0:
            raise ValidationException("Duration cannot be negative")
    
    @property
    def minutes(self) -> float:
        """Get duration in minutes."""
        return self.seconds / 60
    
    @property
    def hours(self) -> float:
        """Get duration in hours."""
        return self.seconds / 3600
    
    def format_hms(self) -> str:
        """Format as HH:MM:SS.
        
        Returns:
            Formatted duration string
        """
        hours = int(self.seconds // 3600)
        minutes = int((self.seconds % 3600) // 60)
        secs = int(self.seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def __str__(self) -> str:
        return self.format_hms()


@dataclass(frozen=True)
class Resolution:
    """Immutable representation of video resolution.
    
    Validates and normalizes resolution format.
    """
    
    width: int
    height: int
    
    def __post_init__(self):
        """Validate resolution."""
        if not isinstance(self.width, int) or not isinstance(self.height, int):
            raise ValidationException("Resolution dimensions must be integers")
        if self.width <= 0 or self.height <= 0:
            raise ValidationException("Resolution dimensions must be positive")
    
    @classmethod
    def from_string(cls, resolution_str: str) -> 'Resolution':
        """Parse resolution from string like '1920x1080'.
        
        Args:
            resolution_str: Resolution string
            
        Returns:
            Resolution instance
            
        Raises:
            ValidationException: If format invalid
        """
        try:
            width, height = resolution_str.split('x')
            return cls(int(width), int(height))
        except (ValueError, AttributeError):
            raise ValidationException(f"Invalid resolution format: {resolution_str}")
    
    @property
    def pixel_count(self) -> int:
        """Get total pixel count."""
        return self.width * self.height
    
    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


@dataclass(frozen=True)
class AspectRatio:
    """Immutable representation of aspect ratio.
    
    Normalizes to standard format.
    """
    
    ratio_str: str
    
    def __post_init__(self):
        """Validate ratio format."""
        if ':' not in self.ratio_str:
            raise ValidationException("Aspect ratio must be in format 'W:H'")
    
    @classmethod
    def from_dimensions(cls, width: int, height: int) -> 'AspectRatio':
        """Calculate aspect ratio from dimensions.
        
        Args:
            width: Video width
            height: Video height
            
        Returns:
            AspectRatio instance
        """
        from math import gcd
        divisor = gcd(width, height)
        w = width // divisor
        h = height // divisor
        return cls(f"{w}:{h}")
    
    def __str__(self) -> str:
        return self.ratio_str

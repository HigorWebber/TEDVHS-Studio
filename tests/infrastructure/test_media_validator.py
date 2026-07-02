"""Unit tests for media validator."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from infrastructure.media.media_validator import MediaValidator
from infrastructure.media.media_scanner import MediaFileCandidate
from datetime import datetime


class TestMediaValidator:
    """Tests for MediaValidator."""
    
    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return MediaValidator()
    
    def test_validator_initialization(self, validator):
        """Test validator initializes correctly."""
        assert validator is not None
    
    def test_validate_nonexistent_file(self, validator):
        """Test validating nonexistent file."""
        candidate = MediaFileCandidate(
            file_path=Path("/nonexistent/file.mp4"),
            file_name="file.mp4",
            file_extension="mp4",
            file_size=1024,
            file_modified=datetime.utcnow()
        )
        
        is_valid, error = validator.validate(candidate)
        assert is_valid is False
        assert "no longer exists" in error
    
    def test_validate_small_file(self, validator):
        """Test validation rejects too small files."""
        with TemporaryDirectory() as tmpdir:
            small_file = Path(tmpdir) / "small.mp4"
            small_file.write_bytes(b"tiny")  # Too small
            
            candidate = MediaFileCandidate(
                file_path=small_file,
                file_name="small.mp4",
                file_extension="mp4",
                file_size=4,
                file_modified=datetime.utcnow()
            )
            
            is_valid, error = validator.validate(candidate)
            assert is_valid is False
            assert "too small" in error.lower()
    
    def test_validate_valid_file(self, validator):
        """Test validation passes for valid file."""
        with TemporaryDirectory() as tmpdir:
            valid_file = Path(tmpdir) / "valid.mp4"
            # Create file > 1MB
            valid_file.write_bytes(b"x" * (2 * 1024 * 1024))
            
            candidate = MediaFileCandidate(
                file_path=valid_file,
                file_name="valid.mp4",
                file_extension="mp4",
                file_size=2 * 1024 * 1024,
                file_modified=datetime.utcnow()
            )
            
            is_valid, error = validator.validate(candidate)
            assert is_valid is True
            assert error == ""

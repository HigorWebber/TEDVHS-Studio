"""Unit tests for value objects."""

import pytest
from domain.media.value_objects import (
    FileHash, MediaId, ProjectId, FileSize, Duration, Resolution, AspectRatio
)
from shared.exceptions import ValidationException


class TestFileHash:
    """Tests for FileHash value object."""
    
    def test_valid_hash(self):
        """Test creation with valid SHA-256 hash."""
        valid_hash = "a" * 64
        fh = FileHash(valid_hash)
        assert str(fh) == valid_hash
    
    def test_invalid_length(self):
        """Test rejection of invalid hash length."""
        with pytest.raises(ValidationException):
            FileHash("a" * 63)  # Too short
    
    def test_invalid_format(self):
        """Test rejection of invalid hash format."""
        with pytest.raises(ValidationException):
            FileHash("z" * 64)  # Invalid character
    
    def test_case_insensitive(self):
        """Test that hash validation is case-insensitive."""
        fh = FileHash("A" * 64)
        assert str(fh) == "A" * 64


class TestMediaId:
    """Tests for MediaId value object."""
    
    def test_valid_id(self):
        """Test creation with valid ID."""
        mid = MediaId(123)
        assert mid.value == 123
    
    def test_negative_id_rejected(self):
        """Test rejection of negative ID."""
        with pytest.raises(ValidationException):
            MediaId(-1)
    
    def test_zero_id_accepted(self):
        """Test that zero ID is accepted."""
        mid = MediaId(0)
        assert mid.value == 0


class TestFileSize:
    """Tests for FileSize value object."""
    
    def test_valid_size(self):
        """Test creation with valid size."""
        fs = FileSize(1024 * 1024)  # 1 MB
        assert fs.bytes == 1024 * 1024
    
    def test_megabytes_conversion(self):
        """Test MB conversion."""
        fs = FileSize(1024 * 1024)  # 1 MB
        assert fs.megabytes == 1.0
    
    def test_gigabytes_conversion(self):
        """Test GB conversion."""
        fs = FileSize(1024 * 1024 * 1024)  # 1 GB
        assert fs.gigabytes == 1.0
    
    def test_negative_size_rejected(self):
        """Test rejection of negative size."""
        with pytest.raises(ValidationException):
            FileSize(-1)


class TestDuration:
    """Tests for Duration value object."""
    
    def test_valid_duration(self):
        """Test creation with valid duration."""
        d = Duration(90.5)  # 90.5 seconds
        assert d.seconds == 90.5
    
    def test_minutes_conversion(self):
        """Test minutes conversion."""
        d = Duration(120.0)  # 2 minutes
        assert d.minutes == 2.0
    
    def test_hours_conversion(self):
        """Test hours conversion."""
        d = Duration(3600.0)  # 1 hour
        assert d.hours == 1.0
    
    def test_hms_formatting(self):
        """Test HH:MM:SS formatting."""
        d = Duration(3661.0)  # 1 hour, 1 minute, 1 second
        assert d.format_hms() == "01:01:01"
    
    def test_negative_duration_rejected(self):
        """Test rejection of negative duration."""
        with pytest.raises(ValidationException):
            Duration(-1)


class TestResolution:
    """Tests for Resolution value object."""
    
    def test_valid_resolution(self):
        """Test creation with valid resolution."""
        res = Resolution(1920, 1080)
        assert res.width == 1920
        assert res.height == 1080
    
    def test_from_string(self):
        """Test parsing from string."""
        res = Resolution.from_string("1920x1080")
        assert res.width == 1920
        assert res.height == 1080
    
    def test_pixel_count(self):
        """Test pixel count calculation."""
        res = Resolution(1920, 1080)
        assert res.pixel_count == 1920 * 1080
    
    def test_invalid_string_format(self):
        """Test rejection of invalid string format."""
        with pytest.raises(ValidationException):
            Resolution.from_string("invalid")


class TestAspectRatio:
    """Tests for AspectRatio value object."""
    
    def test_valid_ratio(self):
        """Test creation with valid ratio."""
        ar = AspectRatio("16:9")
        assert str(ar) == "16:9"
    
    def test_from_dimensions(self):
        """Test calculation from dimensions."""
        ar = AspectRatio.from_dimensions(1920, 1080)
        assert str(ar) == "16:9"
    
    def test_invalid_format(self):
        """Test rejection of invalid format."""
        with pytest.raises(ValidationException):
            AspectRatio("16-9")  # Wrong separator

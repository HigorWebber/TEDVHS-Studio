"""Unit tests for media scanner."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from infrastructure.media.media_scanner import MediaScanner
from infrastructure.config.configuration_service import ConfigurationService
from shared.exceptions import ValidationException


class TestMediaScanner:
    """Tests for MediaScanner."""
    
    @pytest.fixture
    def config(self):
        """Create test configuration."""
        config = ConfigurationService()
        return config
    
    @pytest.fixture
    def scanner(self, config):
        """Create scanner instance."""
        return MediaScanner(config)
    
    def test_scanner_initialization(self, scanner):
        """Test scanner initializes correctly."""
        assert scanner is not None
        assert len(scanner._supported_formats) > 0
    
    def test_scan_nonexistent_path(self, scanner):
        """Test scanning nonexistent path raises error."""
        with pytest.raises(ValidationException):
            scanner.scan("/nonexistent/path")
    
    def test_scan_file_path_raises_error(self, scanner):
        """Test scanning file instead of directory raises error."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test")
            
            with pytest.raises(ValidationException):
                scanner.scan(test_file)
    
    def test_scan_empty_directory(self, scanner):
        """Test scanning empty directory."""
        with TemporaryDirectory() as tmpdir:
            candidates = scanner.scan(tmpdir)
            assert len(candidates) == 0
    
    def test_scan_finds_video_files(self, scanner):
        """Test scanner finds video files."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create a mock video file
            video_file = tmpdir_path / "test.mp4"
            video_file.write_bytes(b"mock video data" * 1000)  # Make it > 1MB
            
            candidates = scanner.scan(tmpdir)
            
            assert len(candidates) == 1
            assert candidates[0].file_name == "test.mp4"
    
    def test_scan_ignores_hidden_files(self, scanner):
        """Test scanner ignores hidden files."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create hidden video file
            hidden_video = tmpdir_path / ".hidden.mp4"
            hidden_video.write_bytes(b"mock video data" * 1000)
            
            candidates = scanner.scan(tmpdir)
            assert len(candidates) == 0
    
    def test_scan_recursive(self, scanner):
        """Test recursive scanning."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Create nested structure
            subdir = tmpdir_path / "subfolder"
            subdir.mkdir()
            
            video_file = subdir / "test.mp4"
            video_file.write_bytes(b"mock video data" * 1000)
            
            candidates = scanner.scan(tmpdir)
            
            assert len(candidates) == 1
            assert candidates[0].file_name == "test.mp4"

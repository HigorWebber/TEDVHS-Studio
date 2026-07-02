"""Unit tests for media file entity."""

import pytest
from datetime import datetime
from domain.media.media_file import MediaFile, FileInfo, VideoInfo, AudioInfo, ProcessingInfo, HashInfo
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileHash, FileSize, Duration, Resolution


class TestMediaFile:
    """Tests for MediaFile aggregate root."""
    
    @pytest.fixture
    def sample_media(self):
        """Create a sample media file."""
        return MediaFile(
            file_info=FileInfo(
                file_path="/path/to/video.mp4",
                file_name="video.mp4",
                file_name_clean="video",
                file_extension="mp4",
                file_size=FileSize(1024 * 1024 * 100),  # 100 MB
                file_modified_at=datetime.utcnow()
            ),
            video_info=VideoInfo(
                duration=Duration(3600.0),  # 1 hour
                fps=24.0,
                resolution=Resolution(1920, 1080),
                codec_video="h264",
                bitrate=5000
            ),
            audio_info=AudioInfo(
                codec_audio="aac",
                audio_channels=2,
                language_code="en"
            ),
            hash_info=HashInfo(
                file_hash=FileHash("a" * 64)
            )
        )
    
    def test_is_ready(self, sample_media):
        """Test is_ready() check."""
        sample_media.processing_info.status = ProcessingStatus.READY
        assert sample_media.is_ready() is True
        
        sample_media.processing_info.status = ProcessingStatus.DISCOVERED
        assert sample_media.is_ready() is False
    
    def test_has_error(self, sample_media):
        """Test has_error() check."""
        sample_media.processing_info.status = ProcessingStatus.FAILED
        assert sample_media.has_error() is True
        
        sample_media.processing_info.status = ProcessingStatus.READY
        assert sample_media.has_error() is False
    
    def test_is_pending_work(self, sample_media):
        """Test is_pending_work() check."""
        sample_media.processing_info.status = ProcessingStatus.DISCOVERED
        assert sample_media.is_pending_work() is True
        
        sample_media.processing_info.status = ProcessingStatus.READY
        assert sample_media.is_pending_work() is False
    
    def test_is_processing(self, sample_media):
        """Test is_processing() check."""
        sample_media.processing_info.status = ProcessingStatus.METADATA_PENDING
        assert sample_media.is_processing() is True
        
        sample_media.processing_info.status = ProcessingStatus.READY
        assert sample_media.is_processing() is False
    
    def test_is_finished(self, sample_media):
        """Test is_finished() check."""
        sample_media.processing_info.status = ProcessingStatus.READY
        assert sample_media.is_finished() is True
        
        sample_media.processing_info.status = ProcessingStatus.FAILED
        assert sample_media.is_finished() is True
        
        sample_media.processing_info.status = ProcessingStatus.DISCOVERED
        assert sample_media.is_finished() is False
    
    def test_requires_reprocessing(self, sample_media):
        """Test requires_reprocessing() check."""
        sample_media.processing_info.status = ProcessingStatus.REPROCESS_REQUIRED
        assert sample_media.requires_reprocessing() is True
        
        sample_media.processing_info.status = ProcessingStatus.READY
        assert sample_media.requires_reprocessing() is False
    
    def test_mark_as_duplicate(self, sample_media):
        """Test marking file as duplicate."""
        original_hash = FileHash("b" * 64)
        sample_media.mark_as_duplicate(original_hash)
        
        assert sample_media.hash_info.is_duplicate is True
        assert sample_media.hash_info.duplicate_of_hash == original_hash
        assert sample_media.processing_info.status == ProcessingStatus.SKIPPED
    
    def test_increment_attempts(self, sample_media):
        """Test incrementing processing attempts."""
        assert sample_media.processing_info.processing_attempts == 0
        
        sample_media.increment_attempts()
        assert sample_media.processing_info.processing_attempts == 1
        
        sample_media.increment_attempts()
        assert sample_media.processing_info.processing_attempts == 2
    
    def test_set_error(self, sample_media):
        """Test setting error message."""
        error_msg = "Test error"
        sample_media.set_error(error_msg)
        
        assert sample_media.processing_info.last_error == error_msg
        assert sample_media.processing_info.status == ProcessingStatus.FAILED

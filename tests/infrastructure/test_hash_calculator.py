"""Unit tests for hash calculator."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from infrastructure.media.hash_calculator import HashCalculator
from domain.media.value_objects import FileHash
from domain.media.exceptions import HashCalculationException


class TestHashCalculator:
    """Tests for HashCalculator."""
    
    def test_hash_nonexistent_file(self):
        """Test hashing nonexistent file raises error."""
        with pytest.raises(HashCalculationException):
            HashCalculator.calculate(Path("/nonexistent/file.mp4"))
    
    def test_hash_file(self):
        """Test calculating hash of file."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.bin"
            test_data = b"test content"
            test_file.write_bytes(test_data)
            
            hash_result = HashCalculator.calculate(test_file)
            
            assert isinstance(hash_result, FileHash)
            assert len(str(hash_result)) == 64
    
    def test_hash_consistency(self):
        """Test that hashing same file produces same hash."""
        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.bin"
            test_file.write_bytes(b"consistent content")
            
            hash1 = HashCalculator.calculate(test_file)
            hash2 = HashCalculator.calculate(test_file)
            
            assert str(hash1) == str(hash2)
    
    def test_hash_different_files(self):
        """Test that different files have different hashes."""
        with TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.bin"
            file2 = Path(tmpdir) / "file2.bin"
            
            file1.write_bytes(b"content1")
            file2.write_bytes(b"content2")
            
            hash1 = HashCalculator.calculate(file1)
            hash2 = HashCalculator.calculate(file2)
            
            assert str(hash1) != str(hash2)
    
    def test_hash_large_file(self):
        """Test hashing large file (streaming)."""
        with TemporaryDirectory() as tmpdir:
            large_file = Path(tmpdir) / "large.bin"
            # Create 50MB file
            with open(large_file, 'wb') as f:
                for _ in range(50):
                    f.write(b"x" * (1024 * 1024))
            
            hash_result = HashCalculator.calculate(large_file)
            assert isinstance(hash_result, FileHash)

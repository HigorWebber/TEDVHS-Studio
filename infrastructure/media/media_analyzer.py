"""Media metadata analyzer using FFprobe.

Extracts comprehensive metadata from media files.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from domain.media.value_objects import Duration, Resolution, AspectRatio, FileHash
from domain.media.exceptions import MetadataException
from infrastructure.config.configuration_service import ConfigurationService


logger = logging.getLogger(__name__)


class IMediaAnalyzer:
    """Interface for media analyzers."""
    
    def analyze(self, file_path: Path, file_hash: FileHash) -> Dict[str, Any]:
        """Analyze media file.
        
        Args:
            file_path: Path to media file
            file_hash: SHA-256 hash of file
            
        Returns:
            Dictionary with extracted metadata
        """
        raise NotImplementedError


class FFprobeAnalyzer(IMediaAnalyzer):
    """Metadata analyzer using FFprobe."""
    
    def __init__(self, config: ConfigurationService):
        """Initialize analyzer.
        
        Args:
            config: Configuration service
        """
        self._config = config
        self._ffprobe_path = config.get("ffmpeg.ffprobe_path", "ffprobe")
        logger.info(f"FFprobeAnalyzer initialized with path: {self._ffprobe_path}")
    
    def analyze(self, file_path: Path, file_hash: FileHash) -> Dict[str, Any]:
        """Analyze media file using FFprobe.
        
        Args:
            file_path: Path to media file
            file_hash: SHA-256 hash of file
            
        Returns:
            Dictionary with extracted metadata
            
        Raises:
            MetadataException: If analysis fails
        """
        try:
            # Call FFprobe
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "error",
                    "-show_format",
                    "-show_streams",
                    "-of", "json",
                    str(file_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                raise MetadataException(f"FFprobe failed: {result.stderr}")
            
            # Parse JSON output
            data = json.loads(result.stdout)
            
            # Extract metadata
            metadata = self._extract_metadata(data, file_hash)
            
            logger.debug(f"Metadata extracted for {file_path}")
            return metadata
        
        except subprocess.TimeoutExpired:
            raise MetadataException(f"FFprobe timeout for {file_path}")
        except json.JSONDecodeError:
            raise MetadataException(f"Invalid FFprobe output for {file_path}")
        except Exception as e:
            raise MetadataException(f"Error analyzing {file_path}: {e}")
    
    def _extract_metadata(self, ffprobe_data: Dict[str, Any],
                         file_hash: FileHash) -> Dict[str, Any]:
        """Extract relevant metadata from FFprobe JSON.
        
        Args:
            ffprobe_data: FFprobe JSON output
            file_hash: File hash
            
        Returns:
            Extracted metadata dictionary
        """
        format_info = ffprobe_data.get("format", {})
        streams = ffprobe_data.get("streams", [])
        
        # Find video and audio streams
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        
        metadata = {
            "file_hash": str(file_hash),
            "duration": Duration(float(format_info.get("duration", 0))),
            "bitrate": int(format_info.get("bit_rate", 0)),
            "num_streams": len(streams),
        }
        
        # Video metadata
        if video_stream:
            width = video_stream.get("width")
            height = video_stream.get("height")
            if width and height:
                metadata["resolution"] = Resolution(width, height)
                metadata["aspect_ratio"] = AspectRatio.from_dimensions(width, height)
            
            metadata["fps"] = float(video_stream.get("r_frame_rate", "0/1").split("/")[0])
            metadata["codec_video"] = video_stream.get("codec_name", "")
        
        # Audio metadata
        if audio_stream:
            metadata["codec_audio"] = audio_stream.get("codec_name", "")
            metadata["audio_channels"] = audio_stream.get("channels", 0)
            metadata["language_code"] = audio_stream.get("tags", {}).get("language")
        
        return metadata

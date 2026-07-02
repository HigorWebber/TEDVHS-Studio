"""Media scanning implementation using FFprobe."""

import logging
import json
import subprocess
from pathlib import Path
from typing import Optional

from domain.interfaces import IMediaScanner
from shared.dto import MediaMetadataDTO
from shared.exceptions import MediaProcessingException


logger = logging.getLogger('processing')


class FFprobeMediaScanner(IMediaScanner):
    """Scans media files using FFprobe."""
    
    SUPPORTED_FORMATS = {
        'mp4', 'mkv', 'avi', 'mov', 'flv', 'wmv',
        'webm', 'm4v', 'mpg', 'mpeg', 'ts', 'm2ts'
    }
    
    def __init__(self, ffprobe_path: str = 'ffprobe'):
        """Initialize scanner.
        
        Args:
            ffprobe_path: Path to ffprobe executable
        """
        self.ffprobe_path = ffprobe_path
        logger.info(f"FFprobeMediaScanner initialized with: {ffprobe_path}")
    
    def scan_file(self, file_path: Path) -> MediaMetadataDTO:
        """Scan media file and extract metadata.
        
        Args:
            file_path: Path to media file
            
        Returns:
            Media metadata
            
        Raises:
            MediaProcessingException: If file cannot be scanned
        """
        try:
            logger.debug(f"Scanning: {file_path}")
            
            # Run ffprobe
            cmd = [
                self.ffprobe_path,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                str(file_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise MediaProcessingException(f"FFprobe error: {result.stderr}")
            
            data = json.loads(result.stdout)
            metadata = self._parse_metadata(data)
            
            logger.info(f"Scanned: {file_path} - Duration: {metadata.duration}s")
            return metadata
            
        except json.JSONDecodeError as e:
            raise MediaProcessingException(f"Invalid FFprobe output: {e}")
        except subprocess.TimeoutExpired:
            raise MediaProcessingException("FFprobe timeout")
        except Exception as e:
            raise MediaProcessingException(f"Failed to scan media: {e}")
    
    def is_supported(self, file_path: Path) -> bool:
        """Check if file format is supported.
        
        Args:
            file_path: Path to media file
            
        Returns:
            True if supported
        """
        extension = file_path.suffix.lower().lstrip('.')
        return extension in self.SUPPORTED_FORMATS
    
    @staticmethod
    def _parse_metadata(ffprobe_data: dict) -> MediaMetadataDTO:
        """Parse FFprobe output.
        
        Args:
            ffprobe_data: FFprobe JSON output
            
        Returns:
            Parsed metadata
        """
        format_info = ffprobe_data.get('format', {})
        streams = ffprobe_data.get('streams', [])
        
        # Find video and audio streams
        video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
        audio_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)
        
        if not video_stream:
            raise MediaProcessingException("No video stream found")
        
        return MediaMetadataDTO(
            duration=float(format_info.get('duration', 0)),
            fps=float(video_stream.get('r_frame_rate', '0/1').split('/')[0] or 0) / 
                float(video_stream.get('r_frame_rate', '1/1').split('/')[1] or 1),
            codec=video_stream.get('codec_name', 'unknown'),
            width=int(video_stream.get('width', 0)),
            height=int(video_stream.get('height', 0)),
            bitrate=int(format_info.get('bit_rate', 0)),
            file_size=int(format_info.get('size', 0)),
            has_audio=audio_stream is not None,
            audio_codec=audio_stream.get('codec_name') if audio_stream else None,
        )

"""Media pipeline for orchestrating import workflow.

Coordinates all stages of media import:
Scanning -> Validation -> Hashing -> Analysis -> Persistence -> Events
"""

import logging
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from uuid import uuid4

from domain.media.media_file import MediaFile, FileInfo, VideoInfo, AudioInfo, ProcessingInfo, HashInfo
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileHash, FileSize, Duration, MediaId
from domain.media.events import (
    MediaDiscoveredEvent, MediaValidatedEvent, MetadataExtractedEvent,
    DuplicateDetectedEvent, MediaImportedEvent, StateTransitionEvent,
    ProcessingFailedEvent, ImportStartedEvent, ImportCompletedEvent
)
from domain.media.exceptions import ProcessingException
from domain.media.media_state_machine import MediaStateMachine

from infrastructure.media.media_scanner import MediaScanner, MediaFileCandidate
from infrastructure.media.media_validator import MediaValidator
from infrastructure.media.hash_calculator import HashCalculator
from infrastructure.media.media_analyzer import FFprobeAnalyzer
from infrastructure.media.media_repository import IMediaRepository

from application.shared.event_bus import EventBus
from infrastructure.config.configuration_service import ConfigurationService


logger = logging.getLogger(__name__)


class MediaPipeline:
    """Orchestrates media file import processing.
    
    Coordinates all stages:
    1. Scanner - discovers files
    2. Validator - validates candidates
    3. HashCalculator - computes SHA-256
    4. Analyzer - extracts metadata
    5. Repository - persists data
    6. EventBus - emits events
    """
    
    def __init__(self, 
                 scanner: MediaScanner,
                 validator: MediaValidator,
                 analyzer: FFprobeAnalyzer,
                 repository: IMediaRepository,
                 event_bus: EventBus,
                 config: ConfigurationService):
        """Initialize pipeline.
        
        Args:
            scanner: Media scanner
            validator: Media validator
            analyzer: Metadata analyzer
            repository: Media repository
            event_bus: Event bus for emission
            config: Configuration service
        """
        self._scanner = scanner
        self._validator = validator
        self._analyzer = analyzer
        self._repository = repository
        self._event_bus = event_bus
        self._config = config
        self._state_machine = MediaStateMachine()
        logger.info("MediaPipeline initialized")
    
    def process_directory(self, root_path: str,
                         progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Process entire directory for import.
        
        Args:
            root_path: Root directory to scan
            progress_callback: Optional progress callback
            
        Returns:
            Import summary with statistics
        """
        import_session_id = str(uuid4())
        start_time = datetime.utcnow()
        
        logger.info(f"Starting import session: {import_session_id}")
        self._event_bus.emit(ImportStartedEvent(
            import_session_id=import_session_id,
            folder_path=root_path
        ))
        
        # Statistics
        stats = {
            "import_session_id": import_session_id,
            "folders_scanned": 0,
            "files_found": 0,
            "files_valid": 0,
            "files_imported": 0,
            "files_duplicate": 0,
            "files_failed": 0,
            "total_size_bytes": 0,
            "total_duration_seconds": 0,
        }
        
        try:
            # Stage 1: Scanning
            logger.info("Stage 1: Scanning directory...")
            candidates = self._scanner.scan(root_path)
            stats["files_found"] = len(candidates)
            stats["folders_scanned"] = 1  # Simplified for now
            
            if progress_callback:
                progress_callback("scanning", len(candidates))
            
            # Stage 2: Validation
            logger.info("Stage 2: Validating files...")
            valid_candidates, failed = self._validator.validate_batch(candidates)
            stats["files_valid"] = len(valid_candidates)
            stats["files_failed"] = len(failed)
            
            if progress_callback:
                progress_callback("validating", len(valid_candidates))
            
            # Stage 3-6: Process each valid file
            logger.info(f"Stage 3-6: Processing {len(valid_candidates)} files...")
            for i, candidate in enumerate(valid_candidates):
                try:
                    media = self._process_candidate(candidate)
                    stats["files_imported"] += 1
                    stats["total_size_bytes"] += candidate.file_size
                    if media.video_info.duration:
                        stats["total_duration_seconds"] += media.video_info.duration.seconds
                
                except ProcessingException as e:
                    logger.error(f"Failed to process {candidate.file_path}: {e}")
                    stats["files_failed"] += 1
                
                if progress_callback:
                    progress_callback("processing", i + 1, len(valid_candidates))
            
            # Duration
            duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            
            # Emit completion event
            self._event_bus.emit(ImportCompletedEvent(
                import_session_id=import_session_id,
                total_files=stats["files_found"],
                imported_files=stats["files_imported"],
                duplicate_files=stats["files_duplicate"],
                failed_files=stats["files_failed"],
                total_size_bytes=stats["total_size_bytes"],
                duration_seconds=duration_seconds
            ))
            
            stats["duration_seconds"] = duration_seconds
            
            logger.info(f"Import session complete: {import_session_id}")
            logger.info(f"Summary: {stats['files_imported']} imported, "
                       f"{stats['files_duplicate']} duplicates, "
                       f"{stats['files_failed']} failed")
            
            return stats
        
        except Exception as e:
            logger.error(f"Import session failed: {e}")
            raise
    
    def _process_candidate(self, candidate: MediaFileCandidate) -> MediaFile:
        """Process a single file candidate through pipeline.
        
        Args:
            candidate: File candidate to process
            
        Returns:
            Processed MediaFile
            
        Raises:
            ProcessingException: If processing fails
        """
        try:
            # Emit discovery event
            self._event_bus.emit(MediaDiscoveredEvent(
                file_hash="",  # Will be set after hashing
                file_path=str(candidate.file_path),
                file_name=candidate.file_name,
                file_size=candidate.file_size
            ))
            
            # Calculate hash
            file_hash = HashCalculator.calculate(candidate.file_path)
            
            # Check for duplicates
            existing = self._repository.find_by_hash(file_hash)
            if existing:
                self._event_bus.emit(DuplicateDetectedEvent(
                    file_hash=str(file_hash),
                    original_hash=str(existing.hash_info.file_hash),
                    file_path=str(candidate.file_path)
                ))
                raise ProcessingException(f"Duplicate file: {file_hash}")
            
            # Validate again
            self._event_bus.emit(MediaValidatedEvent(
                file_hash=str(file_hash),
                file_path=str(candidate.file_path)
            ))
            
            # Extract metadata
            metadata = self._analyzer.analyze(candidate.file_path, file_hash)
            self._event_bus.emit(MetadataExtractedEvent(
                file_hash=str(file_hash),
                duration=metadata["duration"].seconds,
                fps=metadata.get("fps", 0),
                resolution=str(metadata.get("resolution", "")),
                codec_video=metadata.get("codec_video", "")
            ))
            
            # Create MediaFile entity
            media = MediaFile(
                file_info=FileInfo(
                    file_path=str(candidate.file_path),
                    file_name=candidate.file_name,
                    file_name_clean=candidate.file_path.stem,
                    file_extension=candidate.file_extension,
                    file_size=FileSize(candidate.file_size),
                    file_modified_at=candidate.file_modified
                ),
                video_info=VideoInfo(
                    duration=metadata["duration"],
                    fps=metadata.get("fps", 0),
                    resolution=metadata.get("resolution"),
                    aspect_ratio=metadata.get("aspect_ratio"),
                    codec_video=metadata.get("codec_video", ""),
                    bitrate=metadata.get("bitrate", 0),
                    num_streams=metadata.get("num_streams", 0)
                ),
                audio_info=AudioInfo(
                    codec_audio=metadata.get("codec_audio"),
                    audio_channels=metadata.get("audio_channels", 0),
                    language_code=metadata.get("language_code")
                ),
                processing_info=ProcessingInfo(
                    status=ProcessingStatus.METADATA_EXTRACTED
                ),
                hash_info=HashInfo(file_hash=file_hash)
            )
            
            # Persist
            media = self._repository.add(media)
            
            # Update status
            media.processing_info.status = ProcessingStatus.READY
            self._repository.update(media)
            
            # Emit import event
            self._event_bus.emit(MediaImportedEvent(
                media_id=media.id.value if media.id else 0,
                file_hash=str(file_hash),
                file_path=str(candidate.file_path)
            ))
            
            logger.info(f"Media imported: {candidate.file_name}")
            return media
        
        except ProcessingException:
            raise
        except Exception as e:
            raise ProcessingException(f"Error processing {candidate.file_path}: {e}")

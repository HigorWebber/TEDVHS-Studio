"""Media processing status enumeration."""

from enum import Enum


class ProcessingStatus(Enum):
    """Represents the processing state of a media file.
    
    Each status represents a specific stage in the media lifecycle.
    Transitions follow a predefined state machine pattern.
    """
    
    # Initial states
    DISCOVERED = "discovered"          # File found during scan
    VALIDATED = "validated"            # File passed validation
    
    # Metadata extraction
    METADATA_PENDING = "metadata_pending"        # Awaiting metadata extraction
    METADATA_EXTRACTED = "metadata_extracted"    # Metadata successfully extracted
    
    # Ready for processing
    READY = "ready"                    # Fully processed, ready for use
    
    # Scene detection
    SCENES_PENDING = "scenes_pending"          # Awaiting scene detection
    SCENES_COMPLETED = "scenes_completed"      # Scene detection finished
    
    # Clip extraction
    CLIPS_PENDING = "clips_pending"            # Awaiting clip extraction
    CLIPS_COMPLETED = "clips_completed"        # Clips extracted
    
    # Thumbnails
    THUMBNAILS_PENDING = "thumbnails_pending"    # Awaiting thumbnail generation
    THUMBNAILS_COMPLETED = "thumbnails_completed" # Thumbnails generated
    
    # Terminal states
    FAILED = "failed"                  # Processing failed
    SKIPPED = "skipped"                # Processing skipped (e.g., duplicate)
    
    # Reprocessing
    REPROCESS_REQUIRED = "reprocess_required"  # File changed, needs reprocessing
    REPROCESSING = "reprocessing"              # Currently reprocessing
    
    @classmethod
    def is_terminal(cls, status: 'ProcessingStatus') -> bool:
        """Check if status is terminal (no further transitions possible).
        
        Args:
            status: Status to check
            
        Returns:
            True if terminal state
        """
        return status in (cls.READY, cls.FAILED, cls.SKIPPED)
    
    @classmethod
    def is_processing(cls, status: 'ProcessingStatus') -> bool:
        """Check if status indicates active processing.
        
        Args:
            status: Status to check
            
        Returns:
            True if currently processing
        """
        return status in (
            cls.METADATA_PENDING,
            cls.SCENES_PENDING,
            cls.CLIPS_PENDING,
            cls.THUMBNAILS_PENDING,
            cls.REPROCESSING
        )
    
    @classmethod
    def is_pending_work(cls, status: 'ProcessingStatus') -> bool:
        """Check if status indicates pending work.
        
        Args:
            status: Status to check
            
        Returns:
            True if has pending work
        """
        return status in (
            cls.DISCOVERED,
            cls.VALIDATED,
            cls.METADATA_PENDING,
            cls.SCENES_PENDING,
            cls.CLIPS_PENDING,
            cls.THUMBNAILS_PENDING,
            cls.REPROCESS_REQUIRED,
            cls.REPROCESSING
        )

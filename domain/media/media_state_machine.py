"""Enhanced State Machine with event emission."""

import logging
from typing import Set, Optional

from domain.media.processing_status import ProcessingStatus
from domain.media.events import StateTransitionEvent
from domain.media.value_objects import FileHash
from shared.exceptions import StateTransitionException


logger = logging.getLogger(__name__)


class MediaStateMachine:
    """Manages valid state transitions for media files.
    
    Ensures that media files can only transition between valid states
    and emits events for state changes.
    """
    
    # Define valid transitions: from_state -> set of valid to_states
    TRANSITIONS = {
        ProcessingStatus.DISCOVERED: {
            ProcessingStatus.VALIDATED,
            ProcessingStatus.SKIPPED,
        },
        ProcessingStatus.VALIDATED: {
            ProcessingStatus.METADATA_PENDING,
            ProcessingStatus.SKIPPED,
        },
        ProcessingStatus.METADATA_PENDING: {
            ProcessingStatus.METADATA_EXTRACTED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.METADATA_EXTRACTED: {
            ProcessingStatus.READY,
            ProcessingStatus.SCENES_PENDING,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.READY: {
            ProcessingStatus.SCENES_PENDING,
            ProcessingStatus.CLIPS_PENDING,
            ProcessingStatus.THUMBNAILS_PENDING,
            ProcessingStatus.REPROCESS_REQUIRED,
        },
        ProcessingStatus.SCENES_PENDING: {
            ProcessingStatus.SCENES_COMPLETED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.SCENES_COMPLETED: {
            ProcessingStatus.READY,
            ProcessingStatus.CLIPS_PENDING,
            ProcessingStatus.THUMBNAILS_PENDING,
        },
        ProcessingStatus.CLIPS_PENDING: {
            ProcessingStatus.CLIPS_COMPLETED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.CLIPS_COMPLETED: {
            ProcessingStatus.READY,
            ProcessingStatus.THUMBNAILS_PENDING,
        },
        ProcessingStatus.THUMBNAILS_PENDING: {
            ProcessingStatus.THUMBNAILS_COMPLETED,
            ProcessingStatus.FAILED,
        },
        ProcessingStatus.THUMBNAILS_COMPLETED: {
            ProcessingStatus.READY,
        },
        ProcessingStatus.FAILED: {
            ProcessingStatus.REPROCESS_REQUIRED,
            ProcessingStatus.SKIPPED,
        },
        ProcessingStatus.SKIPPED: {
            # Terminal state - no transitions
        },
        ProcessingStatus.REPROCESS_REQUIRED: {
            ProcessingStatus.REPROCESSING,
        },
        ProcessingStatus.REPROCESSING: {
            ProcessingStatus.VALIDATED,
            ProcessingStatus.FAILED,
        },
    }
    
    @classmethod
    def can_transition(cls, from_status: ProcessingStatus,
                      to_status: ProcessingStatus) -> bool:
        """Check if transition is valid.
        
        Args:
            from_status: Current status
            to_status: Target status
            
        Returns:
            True if transition is allowed
        """
        valid_targets = cls.TRANSITIONS.get(from_status, set())
        return to_status in valid_targets
    
    @classmethod
    def get_valid_transitions(cls, status: ProcessingStatus) -> Set[ProcessingStatus]:
        """Get all valid transitions from a status.
        
        Args:
            status: Current status
            
        Returns:
            Set of valid target statuses
        """
        return cls.TRANSITIONS.get(status, set()).copy()
    
    @classmethod
    def transition(cls, from_status: ProcessingStatus,
                  to_status: ProcessingStatus,
                  file_hash: Optional[FileHash] = None) -> StateTransitionEvent:
        """Perform state transition with validation.
        
        Args:
            from_status: Current status
            to_status: Target status
            file_hash: Associated file hash for event
            
        Returns:
            StateTransitionEvent for event bus emission
            
        Raises:
            StateTransitionException: If transition not allowed
        """
        if not cls.can_transition(from_status, to_status):
            valid = cls.get_valid_transitions(from_status)
            valid_names = [s.value for s in valid]
            raise StateTransitionException(
                f"Cannot transition from {from_status.value} to {to_status.value}. "
                f"Valid transitions: {valid_names}"
            )
        
        logger.debug(f"State transition: {from_status.value} → {to_status.value}")
        
        # Create and return event
        return StateTransitionEvent(
            file_hash=str(file_hash) if file_hash else "",
            from_status=from_status,
            to_status=to_status
        )

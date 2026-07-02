"""Unit tests for media state machine."""

import pytest
from domain.media.media_state_machine import MediaStateMachine
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileHash
from domain.media.exceptions import StateTransitionException


class TestMediaStateMachine:
    """Tests for MediaStateMachine."""
    
    def test_valid_transition(self):
        """Test valid state transition."""
        assert MediaStateMachine.can_transition(
            ProcessingStatus.DISCOVERED,
            ProcessingStatus.VALIDATED
        )
    
    def test_invalid_transition(self):
        """Test invalid state transition."""
        assert not MediaStateMachine.can_transition(
            ProcessingStatus.DISCOVERED,
            ProcessingStatus.READY  # Invalid from DISCOVERED
        )
    
    def test_transition_raises_exception(self):
        """Test that invalid transition raises exception."""
        with pytest.raises(StateTransitionException):
            MediaStateMachine.transition(
                ProcessingStatus.DISCOVERED,
                ProcessingStatus.READY  # Invalid
            )
    
    def test_valid_transition_emits_event(self):
        """Test that valid transition creates event."""
        event = MediaStateMachine.transition(
            ProcessingStatus.DISCOVERED,
            ProcessingStatus.VALIDATED,
            file_hash=FileHash("a" * 64)
        )
        
        assert event.from_status == ProcessingStatus.DISCOVERED
        assert event.to_status == ProcessingStatus.VALIDATED
        assert event.file_hash == "a" * 64
    
    def test_get_valid_transitions(self):
        """Test getting valid transitions from status."""
        valid = MediaStateMachine.get_valid_transitions(
            ProcessingStatus.DISCOVERED
        )
        
        assert ProcessingStatus.VALIDATED in valid
        assert ProcessingStatus.SKIPPED in valid
        assert ProcessingStatus.READY not in valid
    
    def test_terminal_states(self):
        """Test that terminal states have no transitions."""
        valid = MediaStateMachine.get_valid_transitions(ProcessingStatus.SKIPPED)
        assert len(valid) == 0
        
        valid = MediaStateMachine.get_valid_transitions(ProcessingStatus.READY)
        assert len(valid) > 0  # READY is not truly terminal

"""Event bus for system-wide event broadcasting."""

import logging
from typing import Callable, List, Dict, Optional, Any
from datetime import datetime
import threading
from dataclasses import dataclass

from shared.types import EventType


logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents a system event.
    
    Attributes:
        event_type: Type of event
        timestamp: When event occurred
        source: Module that emitted event
        data: Event-specific data
    """
    event_type: EventType
    timestamp: datetime
    source: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class EventBus:
    """Central event publisher/subscriber system.
    
    Allows decoupled communication between modules through events.
    """
    
    def __init__(self):
        """Initialize event bus."""
        self.subscribers: Dict[EventType, List[Callable]] = {}
        self.lock = threading.RLock()
        logger.info("EventBus initialized")
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """Subscribe to an event type.
        
        Args:
            event_type: Type of event to listen for
            handler: Callable to execute when event is emitted
        """
        with self.lock:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            
            self.subscribers[event_type].append(handler)
            logger.debug(f"Handler subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        """Unsubscribe from an event type.
        
        Args:
            event_type: Type of event
            handler: Handler to remove
        """
        with self.lock:
            if event_type in self.subscribers:
                try:
                    self.subscribers[event_type].remove(handler)
                    logger.debug(f"Handler unsubscribed from {event_type.value}")
                except ValueError:
                    logger.warning(f"Handler not found for {event_type.value}")
    
    def emit(self, event_type: EventType, data: Optional[Dict[str, Any]] = None,
             source: Optional[str] = None) -> None:
        """Emit an event.
        
        Args:
            event_type: Type of event
            data: Event data
            source: Source module name
        """
        event = Event(
            event_type=event_type,
            timestamp=datetime.utcnow(),
            source=source,
            data=data or {}
        )
        
        logger.debug(f"Event emitted: {event_type.value} from {source}")
        
        with self.lock:
            handlers = self.subscribers.get(event_type, [])
        
        # Execute handlers in separate threads to avoid blocking
        for handler in handlers:
            try:
                threading.Thread(target=handler, args=(event,), daemon=True).start()
            except Exception as e:
                logger.error(f"Error executing event handler: {e}", exc_info=True)
    
    def get_subscriber_count(self, event_type: EventType) -> int:
        """Get number of subscribers for an event type.
        
        Args:
            event_type: Type of event
            
        Returns:
            Number of subscribers
        """
        with self.lock:
            return len(self.subscribers.get(event_type, []))
    
    def clear_subscribers(self, event_type: Optional[EventType] = None) -> None:
        """Clear subscribers.
        
        Args:
            event_type: Specific event type or None for all
        """
        with self.lock:
            if event_type:
                self.subscribers.pop(event_type, None)
                logger.debug(f"Cleared subscribers for {event_type.value}")
            else:
                self.subscribers.clear()
                logger.debug("Cleared all subscribers")

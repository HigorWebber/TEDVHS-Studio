"""Event bus tests."""

import unittest
import threading
import time

from application.event_bus import EventBus, Event
from shared.types import EventType


class TestEventBus(unittest.TestCase):
    """Test EventBus class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.bus = EventBus()
        self.received_events = []
    
    def test_subscribe_and_emit(self):
        """Test subscribing to event and emitting."""
        def handler(event: Event):
            self.received_events.append(event)
        
        self.bus.subscribe(EventType.PROJECT_CREATED, handler)
        self.bus.emit(EventType.PROJECT_CREATED, {'project_id': 1})
        
        # Give thread time to process
        time.sleep(0.1)
        
        self.assertEqual(len(self.received_events), 1)
        self.assertEqual(self.received_events[0].event_type, EventType.PROJECT_CREATED)
    
    def test_unsubscribe(self):
        """Test unsubscribing from event."""
        def handler(event: Event):
            self.received_events.append(event)
        
        self.bus.subscribe(EventType.PROJECT_CREATED, handler)
        self.bus.unsubscribe(EventType.PROJECT_CREATED, handler)
        self.bus.emit(EventType.PROJECT_CREATED)
        
        time.sleep(0.1)
        
        self.assertEqual(len(self.received_events), 0)
    
    def test_multiple_subscribers(self):
        """Test multiple subscribers to same event."""
        results = []
        
        def handler1(event: Event):
            results.append('handler1')
        
        def handler2(event: Event):
            results.append('handler2')
        
        self.bus.subscribe(EventType.PROJECT_CREATED, handler1)
        self.bus.subscribe(EventType.PROJECT_CREATED, handler2)
        self.bus.emit(EventType.PROJECT_CREATED)
        
        time.sleep(0.1)
        
        self.assertEqual(len(results), 2)
        self.assertIn('handler1', results)
        self.assertIn('handler2', results)


if __name__ == '__main__':
    unittest.main()

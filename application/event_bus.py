"""Event bus para comunicação entre módulos do sistema."""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from shared.types import EventType


logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Representa um evento do sistema."""

    event_type: Any
    timestamp: datetime
    source: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class EventBus:
    """Barramento central de eventos.

    Aceita eventos nos seguintes formatos:
    - EventType
    - objetos de evento de domínio
    - dict com chave "type"
    """

    def __init__(self):
        """Inicializa o EventBus."""
        self.subscribers: Dict[Any, List[Callable]] = {}
        self.lock = threading.RLock()
        logger.info("EventBus inicializado")

    def _get_event_name(self, event_type: Any) -> str:
        """Retorna um nome seguro para o evento."""
        if isinstance(event_type, dict):
            return str(event_type.get("type", "UNKNOWN_EVENT"))

        if hasattr(event_type, "value"):
            return str(event_type.value)

        if hasattr(event_type, "event_type"):
            return str(getattr(event_type, "event_type"))

        if hasattr(event_type, "type"):
            return str(getattr(event_type, "type"))

        return event_type.__class__.__name__

    def _get_subscriber_key(self, event_type: Any) -> Any:
        """Retorna a chave usada para buscar subscribers."""
        if isinstance(event_type, dict):
            return event_type.get("type", "UNKNOWN_EVENT")

        if hasattr(event_type, "value"):
            return event_type

        return event_type.__class__.__name__

    def subscribe(self, event_type: Any, handler: Callable[[Event], None]) -> None:
        """Inscreve um handler para um tipo de evento."""
        key = self._get_subscriber_key(event_type)

        with self.lock:
            if key not in self.subscribers:
                self.subscribers[key] = []

            self.subscribers[key].append(handler)
            logger.debug(f"Handler inscrito em {self._get_event_name(event_type)}")

    def unsubscribe(self, event_type: Any, handler: Callable[[Event], None]) -> None:
        """Remove inscrição de um handler."""
        key = self._get_subscriber_key(event_type)

        with self.lock:
            if key in self.subscribers:
                try:
                    self.subscribers[key].remove(handler)
                    logger.debug(f"Handler removido de {self._get_event_name(event_type)}")
                except ValueError:
                    logger.warning(f"Handler não encontrado para {self._get_event_name(event_type)}")

    def emit(
        self,
        event_type: Any,
        data: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ) -> None:
        """Emite um evento.

        Suporta:
        - EventType
        - objeto de evento de domínio
        - dict com chave "type"
        """
        key = self._get_subscriber_key(event_type)
        event_name = self._get_event_name(event_type)

        if isinstance(event_type, dict):
            event_data = dict(event_type)
            if source is None:
                source = event_type.get("source")
        elif hasattr(event_type, "value"):
            event_data = data or {}
        else:
            event_data = getattr(event_type, "__dict__", {"event": event_type})

        event = Event(
            event_type=key,
            timestamp=datetime.utcnow(),
            source=source,
            data=event_data or {}
        )

        logger.debug(f"Evento emitido: {event_name} from {source}")

        with self.lock:
            handlers = list(self.subscribers.get(key, []))

        for handler in handlers:
            try:
                threading.Thread(target=handler, args=(event,), daemon=True).start()
            except Exception as e:
                logger.error(f"Erro ao executar handler de evento: {e}", exc_info=True)

    def get_subscriber_count(self, event_type: Any) -> int:
        """Retorna quantidade de subscribers para um evento."""
        key = self._get_subscriber_key(event_type)

        with self.lock:
            return len(self.subscribers.get(key, []))

    def clear_subscribers(self, event_type: Optional[Any] = None) -> None:
        """Limpa subscribers."""
        with self.lock:
            if event_type:
                key = self._get_subscriber_key(event_type)
                self.subscribers.pop(key, None)
                logger.debug(f"Subscribers limpos para {self._get_event_name(event_type)}")
            else:
                self.subscribers.clear()
                logger.debug("Todos os subscribers foram limpos")
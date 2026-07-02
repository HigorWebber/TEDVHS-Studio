"""Service Container for Dependency Injection.

Centralized management of service instantiation and lifecycle.
Enables loose coupling and easy testing.
"""

import logging
from typing import Dict, Any, Type, Optional, Callable
from abc import ABC

from infrastructure.config.configuration_service import ConfigurationService


logger = logging.getLogger(__name__)


class ServiceContainer:
    """Dependency Injection container.
    
    Manages service registration, resolution, and lifecycle.
    Supports:
    - Singleton registration
    - Factory functions
    - Lazy initialization
    - Dependency resolution
    """
    
    def __init__(self):
        """Initialize service container."""
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._singletons: Dict[str, Any] = {}
        self._config = ConfigurationService()
        logger.info("ServiceContainer initialized")
    
    def register_singleton(self, service_name: str, instance: Any) -> None:
        """Register a singleton service.
        
        Args:
            service_name: Service identifier
            instance: Service instance
        """
        self._singletons[service_name] = instance
        logger.debug(f"Registered singleton: {service_name}")
    
    def register_factory(self, service_name: str, factory: Callable) -> None:
        """Register a service factory.
        
        Args:
            service_name: Service identifier
            factory: Callable that creates service instances
        """
        self._factories[service_name] = factory
        logger.debug(f"Registered factory: {service_name}")
    
    def register_service(self, service_name: str, service_class: Type,
                        *args, **kwargs) -> None:
        """Register a service class.
        
        Args:
            service_name: Service identifier
            service_class: Service class
            *args: Positional arguments for instantiation
            **kwargs: Keyword arguments for instantiation
        """
        instance = service_class(*args, **kwargs)
        self.register_singleton(service_name, instance)
    
    def resolve(self, service_name: str) -> Any:
        """Resolve a service.
        
        Args:
            service_name: Service identifier
            
        Returns:
            Service instance
            
        Raises:
            KeyError: If service not found
        """
        # Check singleton cache first
        if service_name in self._singletons:
            return self._singletons[service_name]
        
        # Check factory
        if service_name in self._factories:
            instance = self._factories[service_name](self)
            # Cache as singleton
            self._singletons[service_name] = instance
            return instance
        
        # Check generic services
        if service_name in self._services:
            return self._services[service_name]
        
        raise KeyError(f"Service not found: {service_name}")
    
    def has_service(self, service_name: str) -> bool:
        """Check if service is registered.
        
        Args:
            service_name: Service identifier
            
        Returns:
            True if service exists
        """
        return (service_name in self._singletons or
                service_name in self._factories or
                service_name in self._services)
    
    def get_configuration(self) -> ConfigurationService:
        """Get configuration service.
        
        Returns:
            ConfigurationService instance
        """
        return self._config
    
    def clear(self) -> None:
        """Clear all registered services."""
        self._singletons.clear()
        self._factories.clear()
        self._services.clear()
        logger.info("ServiceContainer cleared")
    
    def shutdown(self) -> None:
        """Shutdown container."""
        logger.info("ServiceContainer shutting down")
        # Attempt to call shutdown on services that support it
        for service in self._singletons.values():
            if hasattr(service, 'shutdown'):
                try:
                    service.shutdown()
                except Exception as e:
                    logger.error(f"Error shutting down service: {e}")
        self.clear()

"""Service Locator pattern implementation for easy service access.

Provides global access to common services.
Complementary to ServiceContainer for convenience.
"""

import logging
from typing import Optional

from infrastructure.container.service_container import ServiceContainer
from infrastructure.config.configuration_service import ConfigurationService


logger = logging.getLogger(__name__)


class ServiceLocator:
    """Service locator for convenient service access.
    
    Use sparingly - prefer dependency injection when possible.
    Useful for accessing services in contexts without DI setup.
    """
    
    _instance: Optional[ServiceContainer] = None
    
    @classmethod
    def set_container(cls, container: ServiceContainer) -> None:
        """Set the service container.
        
        Args:
            container: ServiceContainer instance
        """
        cls._instance = container
        logger.info("ServiceLocator container set")
    
    @classmethod
    def get_container(cls) -> ServiceContainer:
        """Get the service container.
        
        Returns:
            ServiceContainer instance
            
        Raises:
            RuntimeError: If container not initialized
        """
        if cls._instance is None:
            raise RuntimeError("ServiceLocator not initialized. Call set_container first.")
        return cls._instance
    
    @classmethod
    def get_config(cls) -> ConfigurationService:
        """Get configuration service.
        
        Returns:
            ConfigurationService instance
        """
        return cls.get_container().get_configuration()
    
    @classmethod
    def resolve(cls, service_name: str):
        """Resolve a service.
        
        Args:
            service_name: Service identifier
            
        Returns:
            Service instance
        """
        return cls.get_container().resolve(service_name)

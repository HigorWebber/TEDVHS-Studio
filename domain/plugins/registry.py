"""Plugin registry and management."""

import logging
from typing import Dict, List, Set, Optional, Type
from domain.plugins.interfaces import IPlugin, PluginCapability, PluginMetadata
from shared.exceptions import ValidationException


logger = logging.getLogger(__name__)


class PluginRegistry:
    """Manages plugin registration, discovery, and resolution.
    
    Central hub for all plugin operations.
    Ensures plugins are discovered and loaded correctly.
    """
    
    def __init__(self):
        """Initialize plugin registry."""
        self._plugins: Dict[str, IPlugin] = {}
        self._capabilities: Dict[PluginCapability, List[str]] = {}
        logger.info("PluginRegistry initialized")
    
    def register(self, plugin: IPlugin) -> None:
        """Register a plugin.
        
        Args:
            plugin: Plugin instance to register
            
        Raises:
            ValidationException: If plugin already registered
        """
        metadata = plugin.metadata
        if metadata.name in self._plugins:
            raise ValidationException(f"Plugin already registered: {metadata.name}")
        
        self._plugins[metadata.name] = plugin
        
        # Register capabilities
        for capability in metadata.capabilities:
            if capability not in self._capabilities:
                self._capabilities[capability] = []
            self._capabilities[capability].append(metadata.name)
        
        logger.info(f"Plugin registered: {metadata.name} v{metadata.version}")
    
    def get_plugin(self, name: str) -> Optional[IPlugin]:
        """Get plugin by name.
        
        Args:
            name: Plugin name
            
        Returns:
            Plugin instance or None if not found
        """
        return self._plugins.get(name)
    
    def get_plugins_by_capability(self,
                                 capability: PluginCapability) -> List[IPlugin]:
        """Get all plugins supporting a capability.
        
        Args:
            capability: Capability to search for
            
        Returns:
            List of plugins supporting capability
        """
        names = self._capabilities.get(capability, [])
        return [self._plugins[name] for name in names]
    
    def has_capability(self, capability: PluginCapability) -> bool:
        """Check if any plugin supports a capability.
        
        Args:
            capability: Capability to check
            
        Returns:
            True if supported
        """
        return capability in self._capabilities and len(self._capabilities[capability]) > 0
    
    def list_plugins(self) -> List[PluginMetadata]:
        """List all registered plugins.
        
        Returns:
            List of plugin metadata
        """
        return [plugin.metadata for plugin in self._plugins.values()]
    
    def list_capabilities(self) -> Dict[PluginCapability, List[str]]:
        """List all registered capabilities.
        
        Returns:
            Map of capabilities to plugin names
        """
        return self._capabilities.copy()
    
    def unregister(self, name: str) -> bool:
        """Unregister a plugin.
        
        Args:
            name: Plugin name
            
        Returns:
            True if unregistered
        """
        if name not in self._plugins:
            return False
        
        plugin = self._plugins.pop(name)
        
        # Remove capabilities
        for capability in plugin.metadata.capabilities:
            if capability in self._capabilities:
                self._capabilities[capability].remove(name)
                if not self._capabilities[capability]:
                    del self._capabilities[capability]
        
        logger.info(f"Plugin unregistered: {name}")
        return True

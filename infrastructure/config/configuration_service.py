"""Configuration service for centralized settings management."""

import logging
from typing import Any, Dict, Optional
from pathlib import Path
import json


logger = logging.getLogger(__name__)


class ConfigurationService:
    """Centralized configuration management.
    
    Provides access to all application settings.
    Supports multiple configuration profiles.
    """
    
    # Default configuration
    DEFAULT_CONFIG = {
        # Processing
        "processing": {
            "max_workers": 4,
            "timeout_seconds": 300,
            "retry_attempts": 3,
            "retry_delay_seconds": 5,
        },
        # Media formats
        "media": {
            "supported_formats": [
                "mp4", "mkv", "avi", "mov", "webm", "flv", "m4v", "ts"
            ],
            "hash_algorithm": "sha256",
        },
        # FFmpeg/FFprobe
        "ffmpeg": {
            "ffmpeg_path": "ffmpeg",
            "ffprobe_path": "ffprobe",
            "use_hardware_acceleration": False,
        },
        # Caching
        "cache": {
            "enabled": True,
            "max_size_mb": 1000,
            "ttl_hours": 24,
        },
        # Logging
        "logging": {
            "level": "INFO",
            "file_path": "logs/",
            "max_file_size_mb": 10,
            "backup_count": 5,
        },
        # Paths
        "paths": {
            "database_path": "data/library.db",
            "cache_path": "cache/",
            "temp_path": "temp/",
            "logs_path": "logs/",
        },
        # Plugins
        "plugins": {
            "enabled": True,
            "plugin_dirs": ["plugins/"],
            "auto_load": True,
        },
    }
    
    def __init__(self, profile: str = "default"):
        """Initialize configuration service.
        
        Args:
            profile: Configuration profile name
        """
        self._profile = profile
        self._config: Dict[str, Any] = self.DEFAULT_CONFIG.copy()
        self._overrides: Dict[str, Any] = {}
        logger.info(f"ConfigurationService initialized with profile: {profile}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.
        
        Supports dot notation for nested values: "section.subsection.key"
        
        Args:
            key: Configuration key
            default: Default value if not found
            
        Returns:
            Configuration value
        """
        parts = key.split(".")
        value = self._config
        
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value.
        
        Supports dot notation for nested values.
        
        Args:
            key: Configuration key
            value: Configuration value
        """
        parts = key.split(".")
        config = self._config
        
        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            config = config[part]
        
        config[parts[-1]] = value
        self._overrides[key] = value
    
    def load_from_file(self, config_path: Path) -> None:
        """Load configuration from JSON file.
        
        Args:
            config_path: Path to configuration file
        """
        try:
            with open(config_path, 'r') as f:
                file_config = json.load(f)
                self._config.update(file_config)
            logger.info(f"Configuration loaded from {config_path}")
        except FileNotFoundError:
            logger.warning(f"Configuration file not found: {config_path}")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in configuration file: {config_path}")
    
    def save_to_file(self, config_path: Path) -> None:
        """Save configuration to JSON file.
        
        Args:
            config_path: Path to save configuration
        """
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(self._config, f, indent=2)
            logger.info(f"Configuration saved to {config_path}")
        except IOError as e:
            logger.error(f"Failed to save configuration: {e}")
    
    def get_all(self) -> Dict[str, Any]:
        """Get complete configuration.
        
        Returns:
            Complete configuration dictionary
        """
        return self._config.copy()
    
    def get_profile(self) -> str:
        """Get current configuration profile.
        
        Returns:
            Profile name
        """
        return self._profile

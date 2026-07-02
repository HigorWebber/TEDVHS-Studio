"""Plugin architecture foundation.

Defines interfaces for extensible plugin system.
Plugins can add new capabilities without modifying core.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Set, Dict, Any, Optional
from dataclasses import dataclass, field


class PluginCapability(Enum):
    """Capabilities that plugins can provide."""
    
    # Analysis capabilities
    METADATA_EXTRACTION = "metadata_extraction"
    SCENE_DETECTION = "scene_detection"
    OCR = "ocr"
    SPEECH_TO_TEXT = "speech_to_text"
    CHARACTER_RECOGNITION = "character_recognition"
    OBJECT_DETECTION = "object_detection"
    ACTION_DETECTION = "action_detection"
    EMOTION_DETECTION = "emotion_detection"
    
    # Processing capabilities
    CLIP_EXTRACTION = "clip_extraction"
    THUMBNAIL_GENERATION = "thumbnail_generation"
    VIDEO_ENCODING = "video_encoding"
    AUDIO_EXTRACTION = "audio_extraction"
    
    # Search capabilities
    SEMANTIC_SEARCH = "semantic_search"
    VISUAL_SEARCH = "visual_search"
    TEXT_SEARCH = "text_search"
    
    # Export capabilities
    EXPORT_TO_DAVINCI = "export_to_davinci"
    EXPORT_TO_PREMIERE = "export_to_premiere"
    EXPORT_TO_AFTER_EFFECTS = "export_to_after_effects"
    
    # AI capabilities
    LLAMA_INTEGRATION = "llama_integration"
    OPENAI_INTEGRATION = "openai_integration"
    GEMINI_INTEGRATION = "gemini_integration"
    EMBEDDING_GENERATION = "embedding_generation"


@dataclass
class PluginMetadata:
    """Metadata describing a plugin."""
    
    name: str
    version: str
    author: str
    description: str
    capabilities: Set[PluginCapability]
    required_dependencies: Dict[str, str] = field(default_factory=dict)
    optional_dependencies: Dict[str, str] = field(default_factory=dict)


class IPlugin(ABC):
    """Base interface for all plugins."""
    
    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Get plugin metadata.
        
        Returns:
            Plugin metadata including name, version, capabilities
        """
        pass
    
    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """Initialize plugin with configuration.
        
        Args:
            config: Plugin-specific configuration
        """
        pass
    
    @abstractmethod
    def shutdown(self) -> None:
        """Clean up plugin resources."""
        pass
    
    @abstractmethod
    def has_capability(self, capability: PluginCapability) -> bool:
        """Check if plugin supports a capability.
        
        Args:
            capability: Capability to check
            
        Returns:
            True if capability is supported
        """
        pass


class IAnalyzerPlugin(IPlugin):
    """Plugin interface for media analysis."""
    
    @abstractmethod
    def analyze(self, file_path: str) -> Dict[str, Any]:
        """Analyze media file.
        
        Args:
            file_path: Path to media file
            
        Returns:
            Analysis results
        """
        pass


class IExporterPlugin(IPlugin):
    """Plugin interface for media export."""
    
    @abstractmethod
    def export(self, media_id: int, output_path: str,
              options: Dict[str, Any]) -> bool:
        """Export media to target format.
        
        Args:
            media_id: ID of media to export
            output_path: Export destination
            options: Export options
            
        Returns:
            True if successful
        """
        pass


class IImporterPlugin(IPlugin):
    """Plugin interface for media import."""
    
    @abstractmethod
    def can_import(self, file_path: str) -> bool:
        """Check if plugin can import file.
        
        Args:
            file_path: File to check
            
        Returns:
            True if can import
        """
        pass
    
    @abstractmethod
    def import_media(self, file_path: str) -> Dict[str, Any]:
        """Import media file.
        
        Args:
            file_path: File to import
            
        Returns:
            Import results
        """
        pass


class ISearchPlugin(IPlugin):
    """Plugin interface for media search."""
    
    @abstractmethod
    def index(self, media_id: int, data: Dict[str, Any]) -> None:
        """Index media for search.
        
        Args:
            media_id: ID to index
            data: Data to index
        """
        pass
    
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list:
        """Search indexed media.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching media IDs
        """
        pass


class IAIPlugin(IPlugin):
    """Plugin interface for AI capabilities."""
    
    @abstractmethod
    def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process data using AI model.
        
        Args:
            input_data: Input for AI processing
            
        Returns:
            AI processing results
        """
        pass

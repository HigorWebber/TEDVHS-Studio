"""AI service interfaces and placeholder implementations.

This module defines contracts for AI/ML features.
Actual implementations will be added in future versions.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional
from pathlib import Path


logger = logging.getLogger(__name__)


class IOpenCLIPProvider(ABC):
    """Interface for OpenCLIP image encoding.
    
    Prepared for: Image similarity search, visual feature extraction.
    """
    
    @abstractmethod
    def encode_image(self, image_path: Path) -> List[float]:
        """Encode image to embedding.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Image embedding vector
        """
        pass
    
    @abstractmethod
    def encode_text(self, text: str) -> List[float]:
        """Encode text to embedding.
        
        Args:
            text: Text to encode
            
        Returns:
            Text embedding vector
        """
        pass


class IFAISSProvider(ABC):
    """Interface for FAISS vector index.
    
    Prepared for: Fast similarity search, indexing embeddings.
    """
    
    @abstractmethod
    def index_vector(self, vector_id: int, vector: List[float]) -> None:
        """Add vector to index.
        
        Args:
            vector_id: Unique vector ID
            vector: Vector to index
        """
        pass
    
    @abstractmethod
    def search_similar(self, query_vector: List[float], top_k: int = 5) -> List[int]:
        """Search for similar vectors.
        
        Args:
            query_vector: Query vector
            top_k: Number of results
            
        Returns:
            List of similar vector IDs
        """
        pass


class IWhisperProvider(ABC):
    """Interface for Whisper speech-to-text.
    
    Prepared for: Audio transcription, dialogue extraction.
    """
    
    @abstractmethod
    def transcribe(self, audio_path: Path, language: Optional[str] = None) -> str:
        """Transcribe audio file.
        
        Args:
            audio_path: Path to audio file
            language: Language code (optional)
            
        Returns:
            Transcribed text
        """
        pass


class ILlamaProvider(ABC):
    """Interface for Llama language model.
    
    Prepared for: Text generation, scene analysis, tagging.
    """
    
    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 500) -> str:
        """Generate text from prompt.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text
        """
        pass
    
    @abstractmethod
    def analyze_scene(self, description: str) -> dict:
        """Analyze scene description.
        
        Args:
            description: Scene description
            
        Returns:
            Analysis results
        """
        pass


class IOpenAIProvider(ABC):
    """Interface for OpenAI API.
    
    Prepared for: GPT models, advanced text processing.
    """
    
    @abstractmethod
    def complete(self, prompt: str, model: str = "gpt-3.5-turbo") -> str:
        """Get completion from OpenAI.
        
        Args:
            prompt: Input prompt
            model: Model name
            
        Returns:
            Completion text
        """
        pass


class IGeminiProvider(ABC):
    """Interface for Google Gemini API.
    
    Prepared for: Multimodal AI, image understanding.
    """
    
    @abstractmethod
    def analyze_image(self, image_path: Path, prompt: str) -> str:
        """Analyze image with prompt.
        
        Args:
            image_path: Path to image
            prompt: Analysis prompt
            
        Returns:
            Analysis result
        """
        pass


class PlaceholderAIProvider:
    """Placeholder implementation for AI features.
    
    Returns dummy data. Replace with actual implementations.
    """
    
    @staticmethod
    def placeholder_encode() -> List[float]:
        """Placeholder embedding."""
        return [0.0] * 512
    
    @staticmethod
    def placeholder_search() -> List[int]:
        """Placeholder search results."""
        return []
    
    @staticmethod
    def placeholder_text() -> str:
        """Placeholder text."""
        return "AI feature not yet implemented"


logger.info("AI provider interfaces prepared for future implementation")

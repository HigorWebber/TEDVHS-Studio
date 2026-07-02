# Plugin Architecture

## Visão Geral

O TEDVHS Studio é projetado para ser **extensível via plugins**. O core permanece pequeno e focado, enquanto novas funcionalidades são adicionadas através de uma arquitetura de plugins.

## Design Principles

1. **Sem Modificações ao Core**
   - Plugins adicionam capacidades
   - Não modificam código existente
   - Ligação dinâmica em tempo de execução

2. **Descoberta Automática**
   - Plugins descobertos automaticamente
   - Registrados na PluginRegistry
   - Capabilities anunciadas

3. **Desacoplamento Total**
   - Core não conhece plugins específicos
   - Plugins comunicam via interfaces
   - EventBus para publicação

## Arquitetura

### Plugin Registry

```python
registry = PluginRegistry()
registry.register(openai_plugin)
registry.register(clip_plugin)
registry.register(scene_plugin)

# Descobrir plugins com capacidade específica
plugins = registry.get_plugins_by_capability(
    PluginCapability.METADATA_EXTRACTION
)
```

### Hierarquia de Interfaces

```
IPlugin (base)
├── IAnalyzerPlugin
│   └─ Metadata, Scene Detection, OCR, Speech-to-Text
├── IExporterPlugin
│   └─ Clip Export, Encode, Format Conversion
├── IImporterPlugin
│   └─ Media Discovery, Format Support
├── ISearchPlugin
│   └─ Semantic Search, Visual Search, Text Search
└── IAIPlugin
    └─ LLM, Embeddings, Multimodal
```

## Capabilities

### Analysis

```python
PluginCapability.METADATA_EXTRACTION
PluginCapability.SCENE_DETECTION
PluginCapability.OCR
PluginCapability.SPEECH_TO_TEXT
PluginCapability.CHARACTER_RECOGNITION
PluginCapability.OBJECT_DETECTION
PluginCapability.ACTION_DETECTION
PluginCapability.EMOTION_DETECTION
```

### Processing

```python
PluginCapability.CLIP_EXTRACTION
PluginCapability.THUMBNAIL_GENERATION
PluginCapability.VIDEO_ENCODING
PluginCapability.AUDIO_EXTRACTION
```

### Search

```python
PluginCapability.SEMANTIC_SEARCH
PluginCapability.VISUAL_SEARCH
PluginCapability.TEXT_SEARCH
```

### Export

```python
PluginCapability.EXPORT_TO_DAVINCI
PluginCapability.EXPORT_TO_PREMIERE
PluginCapability.EXPORT_TO_AFTER_EFFECTS
```

### AI

```python
PluginCapability.LLAMA_INTEGRATION
PluginCapability.OPENAI_INTEGRATION
PluginCapability.GEMINI_INTEGRATION
PluginCapability.EMBEDDING_GENERATION
```

## Implementação de Plugin

### Exemplo: Plugin de Scene Detection

```python
from domain.plugins.interfaces import IAnalyzerPlugin, PluginCapability, PluginMetadata

class SceneDetectionPlugin(IAnalyzerPlugin):
    """Detecção de cenas usando OpenCV."""
    
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="scene-detection",
            version="1.0.0",
            author="TEDVHS Team",
            description="Detects scene changes using OpenCV",
            capabilities={PluginCapability.SCENE_DETECTION},
            required_dependencies={"opencv-python": ">=4.5.0"}
        )
    
    def initialize(self, config: Dict[str, Any]) -> None:
        """Inicializar plugin."""
        self.threshold = config.get("scene_threshold", 0.3)
        self.import cv2
    
    def shutdown(self) -> None:
        """Limpar recursos."""
        pass
    
    def has_capability(self, capability: PluginCapability) -> bool:
        """Verificar capacidade."""
        return capability == PluginCapability.SCENE_DETECTION
    
    def analyze(self, file_path: str) -> Dict[str, Any]:
        """Detectar cenas."""
        scenes = []
        cap = cv2.VideoCapture(file_path)
        
        prev_frame = None
        frame_count = 0
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if prev_frame is not None:
                diff = cv2.absdiff(
                    cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY),
                    cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                ).mean()
                
                if diff > self.threshold:
                    timestamp = frame_count / fps
                    scenes.append({
                        "timestamp": timestamp,
                        "frame": frame_count,
                        "intensity": float(diff)
                    })
            
            prev_frame = frame
            frame_count += 1
        
        cap.release()
        return {"scenes": scenes, "count": len(scenes)}
```

## Carregamento de Plugins

### Automático

```python
registry = PluginRegistry()

# Carregar da pasta plugins/
for plugin_file in Path("plugins").glob("*.py"):
    module = importlib.import_module(f"plugins.{plugin_file.stem}")
    if hasattr(module, "PLUGIN"):
        registry.register(module.PLUGIN)
```

### Manual

```python
scene_plugin = SceneDetectionPlugin()
scene_plugin.initialize({"scene_threshold": 0.3})
registry.register(scene_plugin)
```

## Uso de Plugins

### Descobrir Plugins

```python
# Todos os plugins
all_plugins = registry.list_plugins()

# Por capacidade específica
analyzers = registry.get_plugins_by_capability(
    PluginCapability.SCENE_DETECTION
)

# Verificar disponibilidade
if registry.has_capability(PluginCapability.SEMANTIC_SEARCH):
    search_plugin = registry.get_plugins_by_capability(
        PluginCapability.SEMANTIC_SEARCH
    )[0]
```

### Executar Plugin

```python
# Processar média
media_path = "/path/to/video.mp4"
result = scene_plugin.analyze(media_path)

# Emitir evento
event_bus.emit(ScenesDetectedEvent(
    media_hash=media.hash_info.file_hash,
    scenes=result["scenes"]
))
```

## Fluxo com Plugins

```
MediaFile Importado
    ↓
Publica: MediaImportedEvent
    ↓
┌─────────────────────────────────────┐
│ Plugins escutam evento               │
├─────────────────────────────────────┤
│ SceneDetectionPlugin                │
│  └─ Detecta cenas                   │
│  └─ Publica: ScenesDetectedEvent    │
│                                     │
│ OpenCLIPPlugin                      │
│  └─ Gera embeddings visuais         │
│  └─ Publica: EmbeddingsGeneratedEv  │
│                                     │
│ WhisperPlugin                       │
│  └─ Transcreve áudio                │
│  └─ Publica: TranscriptionCompleted │
└─────────────────────────────────────┘
    ↓
Repository atualiza versões
    ├─ scenes_version++
    ├─ clips_version++
    └─ thumbnails_version++
    ↓
Media status: READY
```

## Ciclo de Vida

```python
# 1. Criação
plugin = MyPlugin()

# 2. Registro
registry.register(plugin)

# 3. Inicialização
plugin.initialize({"config": "values"})

# 4. Uso
result = plugin.analyze(media_path)

# 5. Shutdown (quando aplicável)
plugin.shutdown()

# 6. Unregister (opcional)
registry.unregister(plugin.metadata.name)
```

## Tratamento de Erros

```python
try:
    result = plugin.analyze(media_path)
    registry.emit(AnalysisCompletedEvent(result))
except Exception as e:
    logger.error(f"Plugin {plugin.name} failed: {e}")
    registry.emit(AnalysisFailedEvent(
        plugin_name=plugin.name,
        error=str(e)
    ))
```

## Planned Plugins (v1.0+)

### Scene Detection (v1.5)
- OpenCV-based detector
- Threshold configurável
- Saída em timestamps

### AI (v2.0)
- **OpenCLIP**: Visual embeddings
- **FAISS**: Vector indexing
- **Whisper**: Speech-to-text
- **Llama**: Text analysis

### Export (v3.0)
- **DaVinci Resolve**: XML export
- **Adobe Premiere**: EDL export
- **After Effects**: AEP export

### Search (v3.0)
- **Semantic Search**: Text-based
- **Visual Search**: Image-based
- **CLIP Search**: Multimodal

## Best Practices

1. **Isolamento**
   - Plugin não modifica core
   - Plugin pode ser removido sem quebrar sistema

2. **Resiliência**
   - Plugin falha isoladamente
   - Sistema continua operando

3. **Logging**
   - Log de inicialização
   - Log de execução
   - Log de erros

4. **Configuração**
   - Parâmetros via config
   - Nenhum hardcoding
   - Valores padrão sensatos

5. **Performance**
   - Processar em background
   - Usar Task Manager
   - Callback de progresso

## Estrutura de Diretórios

```
plugins/
├── __init__.py
├── analyzers/
│   ├── scene_detection.py
│   ├── ocr.py
│   └── speech_to_text.py
├── ai/
│   ├── clip.py
│   ├── openai.py
│   └── gemini.py
├── exporters/
│   ├── davinci_resolve.py
│   ├── adobe_premiere.py
│   └── after_effects.py
├── search/
│   ├── semantic.py
│   ├── visual.py
│   └── text.py
└── base_plugin.py
```

---

**Status**: ✅ Architecture Ready (implementação de plugins específicos em futuras sprints)

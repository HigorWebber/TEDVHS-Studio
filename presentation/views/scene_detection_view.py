"""Aba de detecção e catalogação visual de cenas."""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from infrastructure.media.scene_detector import SceneDetector
from infrastructure.ai.gemini_scene_ai_service import GeminiSceneAIService, GeminiSceneAIError
from infrastructure.media.clip_exporter import ClipExporter
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from infrastructure.settings.api_settings import ApiSettingsStore


logger = logging.getLogger(__name__)


class _SceneDetectionWorker(QObject):
    """Worker em QThread para detectar cenas sem travar a interface."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, detector: SceneDetector, file_path: str, duration_seconds: float, threshold: float, min_scene_seconds: float):
        super().__init__()
        self.detector = detector
        self.file_path = file_path
        self.duration_seconds = duration_seconds
        self.threshold = threshold
        self.min_scene_seconds = min_scene_seconds
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def _is_cancelled(self) -> bool:
        return bool(self._cancel_requested)

    def run(self) -> None:
        try:
            scenes = self.detector.detect_scenes(
                file_path=self.file_path,
                duration_seconds=self.duration_seconds,
                threshold=self.threshold,
                min_scene_seconds=self.min_scene_seconds,
                progress_callback=self.progress.emit,
                cancel_callback=self._is_cancelled,
            )
            self.finished.emit(scenes)
        except Exception as exc:
            self.failed.emit(str(exc))


class _SceneCatalogWorker(QObject):
    """Worker em QThread para gerar miniaturas e descrição sem travar a interface."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, detector: SceneDetector, file_path: str, media_id: object, scenes: list[Dict[str, Any]], frames_per_scene: int = 1):
        super().__init__()
        self.detector = detector
        self.file_path = file_path
        self.media_id = media_id
        self.scenes = scenes
        self.frames_per_scene = max(1, min(int(frames_per_scene or 1), 3))
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def _is_cancelled(self) -> bool:
        return bool(self._cancel_requested)

    def run(self) -> None:
        try:
            enriched = self.detector.enrich_scenes_with_visual_catalog(
                file_path=self.file_path,
                media_id=self.media_id,
                scenes=self.scenes,
                output_root=Path("data") / "scene_assets",
                frames_per_scene=self.frames_per_scene,
                progress_callback=self.progress.emit,
                cancel_callback=self._is_cancelled,
            )
            self.finished.emit(enriched)
        except Exception as exc:
            self.failed.emit(str(exc))


class _SceneAIWorker(QObject):
    """Worker em QThread para descrição de cenas com Gemini API em modo seguro."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        detector: SceneDetector,
        ai_service: GeminiSceneAIService,
        file_path: str,
        media_id: object,
        media_context: Dict[str, Any],
        scenes: list[Dict[str, Any]],
        api_key: str,
        model: str = "gemini-3.1-flash-lite",
        max_frames: int = 1,
    ):
        super().__init__()
        self.detector = detector
        self.ai_service = ai_service
        self.file_path = file_path
        self.media_id = media_id
        self.media_context = media_context
        self.scenes = scenes
        self.api_key = str(api_key or "").strip()
        self.model = (model or "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
        self.max_frames = max(1, min(int(max_frames or 1), 2))
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def _is_cancelled(self) -> bool:
        return bool(self._cancel_requested)

    def run(self) -> None:
        try:
            results: list[Dict[str, Any]] = []
            total = len(self.scenes)
            for index, scene in enumerate(self.scenes, start=1):
                if self._is_cancelled():
                    raise RuntimeError("Análise por IA cancelada pelo usuário.")

                scene_number = int(scene.get("scene_number") or index)
                display_name = scene.get("display_name") or f"Cena {scene_number:03d}"
                self.progress.emit(f"IA online segura: preparando {display_name} ({index}/{total})...")

                frames = self.detector.extract_scene_frames_for_ai(
                    file_path=self.file_path,
                    media_id=self.media_id,
                    scene=scene,
                    output_root=Path("data") / "scene_ai_frames",
                    max_frames=self.max_frames,
                    width=448,
                    progress_callback=self.progress.emit,
                    cancel_callback=self._is_cancelled,
                )

                if self._is_cancelled():
                    raise RuntimeError("Análise por IA cancelada pelo usuário.")

                context = dict(self.media_context)
                context.update({
                    "scene_number": scene_number,
                    "display_name": display_name,
                    "start": self._format_seconds(scene.get("custom_start_seconds") if scene.get("custom_start_seconds") is not None else scene.get("start_seconds")),
                    "end": self._format_seconds(scene.get("custom_end_seconds") if scene.get("custom_end_seconds") is not None else scene.get("end_seconds")),
                    "duration": self._format_seconds(self._scene_duration(scene)),
                })

                self.progress.emit(f"IA online segura: analisando {display_name} com modelo {self.model} ({index}/{total})...")
                ai_result = self.ai_service.describe_scene(frames, context=context, api_key=self.api_key, model=self.model)
                description = self.ai_service.format_description(ai_result)
                tags = self.ai_service.normalize_tags(ai_result)
                scene_type = self.ai_service.normalize_scene_type(ai_result)

                analysis_payload = {
                    "method": "gemini_api_vision_safe",
                    "model": self.model,
                    "frames": frames,
                    "ai_result": ai_result,
                }
                results.append({
                    "id": scene.get("id"),
                    "description": description,
                    "tags": tags,
                    "scene_type": scene_type,
                    "analysis_frames_json": json.dumps(analysis_payload, ensure_ascii=False),
                    "ai_status": "gemini_api",
                })
                self.progress.emit(f"IA online segura: {display_name} concluída ({index}/{total}).")

            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _scene_duration(self, scene: Dict[str, Any]) -> float:
        start = scene.get("custom_start_seconds") if scene.get("custom_start_seconds") is not None else scene.get("start_seconds")
        end = scene.get("custom_end_seconds") if scene.get("custom_end_seconds") is not None else scene.get("end_seconds")
        return max(float(end or 0.0) - float(start or 0.0), 0.0)

    def _format_seconds(self, value: object) -> str:
        seconds = max(float(value or 0.0), 0.0)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


class SceneDetectionView(QWidget):
    """Interface para detectar, visualizar e catalogar cenas de episódios."""

    SCENE_TYPES = [
        "Geral",
        "Ação/Movimento",
        "Luta",
        "Diálogo/Construção",
        "Comédia",
        "Drama/Suspense",
        "Transformação",
        "Poder/Habilidade",
        "Revelação",
        "Romance",
        "Transição",
        "Outro",
    ]

    def __init__(self, repository: SQLiteMediaRepository, scene_detector: SceneDetector, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.scene_detector = scene_detector
        self.clip_exporter = ClipExporter()
        self.ai_service = GeminiSceneAIService(timeout_seconds=120)
        self.api_settings = ApiSettingsStore()
        self._all_media_files: list[object] = []
        self._media_by_combo_index: dict[int, object] = {}
        self._scenes_by_row: dict[int, Dict[str, Any]] = {}
        self._active_thread: Optional[QThread] = None
        self._active_worker: Optional[QObject] = None
        self._active_operation: Optional[str] = None
        self._selected_scene: Optional[Dict[str, Any]] = None
        self._selected_media: Optional[object] = None
        self._preview_scene_id: Optional[int] = None
        self._scene_start_ms: Optional[int] = None
        self._scene_end_ms: Optional[int] = None
        self._active_segment_start_ms: Optional[int] = None
        self._active_segment_end_ms: Optional[int] = None
        self._preview_segments: list[tuple[int, int]] = []
        self._current_segment_index: int = 0
        self._segment_offsets: list[int] = []
        self._total_preview_duration_ms: int = 0
        self._updating_slider = False
        self._ignore_field_changes = False
        self._applying_detection_preset = False

        self._setup_ui()
        self._setup_player()
        self._load_media_options()

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(10, 8, 10, 8)
        root_layout.setSpacing(6)

        title = QLabel("Detecção e Catálogo de Cenas")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root_layout.addWidget(title)

        subtitle = QLabel(
            "Detecte cenas com presets claros, visualize o trecho, ajuste cortes e use IA nas cenas selecionadas. "
            "Arraste as divisórias para aumentar lista, player ou catálogo."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #cccccc;")
        root_layout.addWidget(subtitle)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        top_layout.addWidget(QLabel("Anime/Pasta:"))
        self.folder_combo = QComboBox()
        self.folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        top_layout.addWidget(self.folder_combo, stretch=1)

        top_layout.addWidget(QLabel("Temporada:"))
        self.season_combo = QComboBox()
        self.season_combo.currentIndexChanged.connect(self._on_season_changed)
        top_layout.addWidget(self.season_combo, stretch=1)

        top_layout.addWidget(QLabel("Episódio:"))
        self.media_combo = QComboBox()
        self.media_combo.currentIndexChanged.connect(self._on_media_changed)
        top_layout.addWidget(self.media_combo, stretch=2)

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self._load_media_options)
        top_layout.addWidget(self.refresh_btn)
        root_layout.addLayout(top_layout)

        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(8)

        settings_layout.addWidget(QLabel("Quantidade de cortes:"))
        self.detection_preset_combo = QComboBox()
        self.detection_preset_combo.addItems([
            "Mais cortes",
            "Anime equilibrado",
            "Menos cortes",
            "Cenas longas",
            "Personalizado",
        ])
        self.detection_preset_combo.setCurrentText("Anime equilibrado")
        self.detection_preset_combo.setToolTip(
            "Use presets para evitar configurações confusas. Mais cortes divide mais; menos cortes junta mais."
        )
        self.detection_preset_combo.currentTextChanged.connect(self._on_detection_preset_changed)
        settings_layout.addWidget(self.detection_preset_combo)

        settings_layout.addWidget(QLabel("Limiar técnico:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.05, 0.50)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(0.15)
        self.threshold_spin.setToolTip(
            "Ajuste avançado: número menor = mais cortes. Número maior = menos cortes."
        )
        self.threshold_spin.valueChanged.connect(self._mark_detection_preset_custom)
        settings_layout.addWidget(self.threshold_spin)

        settings_layout.addWidget(QLabel("Cena mínima (s):"))
        self.min_scene_spin = QDoubleSpinBox()
        self.min_scene_spin.setRange(1.0, 30.0)
        self.min_scene_spin.setSingleStep(0.5)
        self.min_scene_spin.setDecimals(1)
        self.min_scene_spin.setValue(4.0)
        self.min_scene_spin.setToolTip(
            "Cortes menores que este valor são juntados. Em anime, use normalmente entre 2s e 6s."
        )
        self.min_scene_spin.valueChanged.connect(self._mark_detection_preset_custom)
        settings_layout.addWidget(self.min_scene_spin)

        self.detect_btn = QPushButton("Detectar rápido")
        self.detect_btn.setToolTip("Detecta intervalos com FFmpeg otimizado, progresso em tempo real e cancelamento seguro.")
        self.detect_btn.clicked.connect(self._on_detect_clicked)
        settings_layout.addWidget(self.detect_btn)

        self.catalog_selected_btn = QPushButton("Catalogar básico")
        self.catalog_selected_btn.setToolTip(
            "Catalogação local e leve: gera miniatura/descrição simples sem usar API. "
            "Use antes da IA apenas quando quiser uma base rápida."
        )
        self.catalog_selected_btn.clicked.connect(self._on_catalog_selected_clicked)
        settings_layout.addWidget(self.catalog_selected_btn)

        self.ai_selected_top_btn = QPushButton("IA nas selecionadas")
        self.ai_selected_top_btn.setToolTip(
            "Usa Gemini API nas cenas selecionadas para gerar descrição, tags, tipo e potencial. "
            "Não roda em todas sem confirmação."
        )
        self.ai_selected_top_btn.clicked.connect(self._on_generate_ai_selected_clicked)
        settings_layout.addWidget(self.ai_selected_top_btn)

        self.catalog_all_btn = QPushButton("Básico todas")
        self.catalog_all_btn.setToolTip(
            "Ação avançada/local: cataloga todas sem API. Fica fora da barra principal para evitar cliques acidentais."
        )
        self.catalog_all_btn.clicked.connect(self._on_catalog_all_clicked)
        self.catalog_all_btn.setVisible(False)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_active_operation)
        settings_layout.addWidget(self.cancel_btn)

        self.clear_btn = QPushButton("Limpar cenas")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        settings_layout.addWidget(self.clear_btn)

        settings_layout.addStretch()
        root_layout.addLayout(settings_layout)

        self.status_label = QLabel("Selecione um episódio para começar.")
        self.status_label.setStyleSheet("color: #cccccc;")
        self.status_label.setWordWrap(True)
        root_layout.addWidget(self.status_label)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self._create_scene_list_panel())
        self.main_splitter.addWidget(self._create_preview_panel())
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([660, 660])
        root_layout.addWidget(self.main_splitter, stretch=1)

        self.setLayout(root_layout)
    def _create_scene_list_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(540)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(4)

        header_label = QLabel("Lista de cenas e clipes")
        header_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(header_label)

        hint = QLabel("Selecione uma cena/clipe para prévia. Use Ctrl/Shift para selecionar várias cenas e criar um clipe rascunho.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Miniatura", "Cena", "Início", "Fim", "Duração", "Tipo", "Tags", "Descrição", "★",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_scene_selected)
        self.table.doubleClicked.connect(lambda *_: self._play_selected_scene())
        self.table.setIconSize(QPixmap(96, 54).size())
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        header = self.table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 86)
        self.table.setColumnWidth(1, 78)
        self.table.setColumnWidth(2, 92)
        self.table.setColumnWidth(3, 92)
        self.table.setColumnWidth(4, 92)
        self.table.setColumnWidth(5, 150)
        self.table.setColumnWidth(6, 220)
        self.table.setColumnWidth(7, 420)
        self.table.setColumnWidth(8, 36)
        layout.addWidget(self.table, stretch=1)
        return panel
    def _create_preview_panel(self) -> QWidget:
        """Criar painel de preview/catálogo em abas para evitar campos apertados.

        Decisão de UX:
        - o player fica sozinho na aba Preview, com espaço suficiente e controles visíveis;
        - descrição/tags, corte e miniatura ficam em abas próprias, com campos grandes;
        - isso evita que vídeo, descrição e botões disputem a mesma altura da janela.
        """
        panel = QWidget()
        panel.setMinimumWidth(560)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)

        hint = QLabel(
            "Dica: arraste a divisória central para dar mais espaço à lista ou ao painel da direita. "
            "Use as abas abaixo para alternar entre preview, descrição, corte e miniatura."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(hint)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.detail_tabs.addTab(self._create_player_tab(), "Preview")
        self.detail_tabs.addTab(self._create_catalog_tab(), "Descrição e Tags")
        self.detail_tabs.addTab(self._create_trim_tab(), "Corte")
        self.detail_tabs.addTab(self._create_info_tab(), "Miniatura / IA")
        layout.addWidget(self.detail_tabs, stretch=1)

        return panel

    def _create_player_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(300)
        self.video_widget.setMaximumHeight(460)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("background: #050505; border: 1px solid #444444;")
        try:
            self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)
        except Exception:
            pass
        layout.addWidget(self.video_widget, stretch=1)

        # Linha do tempo do trecho/clipe. Visual mais discreto, integrado ao tema.
        timeline_frame = QFrame()
        timeline_frame.setObjectName("timelineFrame")
        timeline_frame.setMinimumHeight(48)
        timeline_frame.setMaximumHeight(56)
        timeline_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        timeline_frame.setStyleSheet(
            "QFrame#timelineFrame {"
            "  background: transparent;"
            "  border: none;"
            "}"
        )
        timeline_outer = QVBoxLayout(timeline_frame)
        timeline_outer.setContentsMargins(0, 2, 0, 2)
        timeline_outer.setSpacing(2)

        timeline_layout = QHBoxLayout()
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(8)

        self.current_time_label = QLabel("00:00:00.000")
        self.current_time_label.setMinimumWidth(100)
        self.current_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.current_time_label.setStyleSheet("color: #d0d0d0; font-size: 11px;")
        timeline_layout.addWidget(self.current_time_label)

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setObjectName("sceneTimelineSlider")
        self.position_slider.setRange(0, 1000)
        self.position_slider.setEnabled(False)
        self.position_slider.setMinimumHeight(24)
        self.position_slider.setMaximumHeight(28)
        self.position_slider.setTickPosition(QSlider.NoTicks)
        self.position_slider.setToolTip("Arraste para avançar ou voltar dentro do trecho/clipe atual.")
        self.position_slider.sliderMoved.connect(self._on_seek_slider_moved)
        self.position_slider.sliderPressed.connect(lambda: setattr(self, "_updating_slider", True))
        self.position_slider.sliderReleased.connect(self._on_seek_slider_released)
        self.position_slider.setStyleSheet(
            "QSlider#sceneTimelineSlider { min-height: 24px; max-height: 28px; }"
            "QSlider#sceneTimelineSlider::groove:horizontal {"
            "  height: 5px; background: #343434; border: 1px solid #555555; border-radius: 3px;"
            "}"
            "QSlider#sceneTimelineSlider::sub-page:horizontal {"
            "  background: #5a8dee; border: 1px solid #5a8dee; border-radius: 3px;"
            "}"
            "QSlider#sceneTimelineSlider::add-page:horizontal {"
            "  background: #2b2b2b; border: 1px solid #444444; border-radius: 3px;"
            "}"
            "QSlider#sceneTimelineSlider::handle:horizontal {"
            "  background: #e6e6e6; border: 1px solid #5a8dee; width: 12px; height: 12px;"
            "  margin: -5px 0; border-radius: 6px;"
            "}"
            "QSlider#sceneTimelineSlider::handle:horizontal:disabled {"
            "  background: #777777; border: 1px solid #555555;"
            "}"
        )
        timeline_layout.addWidget(self.position_slider, stretch=1)

        self.scene_time_label = QLabel("00:00:00.000")
        self.scene_time_label.setMinimumWidth(100)
        self.scene_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.scene_time_label.setStyleSheet("color: #d0d0d0; font-size: 11px;")
        timeline_layout.addWidget(self.scene_time_label)
        timeline_outer.addLayout(timeline_layout)

        timeline_help = QLabel("Arraste a barra para avançar ou voltar no trecho selecionado.")
        timeline_help.setStyleSheet("color: #888888; font-size: 10px;")
        timeline_help.setAlignment(Qt.AlignCenter)
        timeline_outer.addWidget(timeline_help)

        layout.addWidget(timeline_frame, stretch=0)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setToolTip("Play/Pause: continua de onde parou quando o trecho estiver pausado")
        self.play_btn.clicked.connect(self._toggle_play_pause)
        controls_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("⏹ Parar")
        self.stop_btn.setToolTip("Parar")
        self.stop_btn.clicked.connect(self._stop_preview)
        controls_layout.addWidget(self.stop_btn)

        self.back_btn = QPushButton("-5s")
        self.back_btn.clicked.connect(lambda: self._seek_relative(-5000))
        controls_layout.addWidget(self.back_btn)

        self.forward_btn = QPushButton("+5s")
        self.forward_btn.clicked.connect(lambda: self._seek_relative(5000))
        controls_layout.addWidget(self.forward_btn)

        self.join_preview_btn = QPushButton("Juntar em clipe rascunho")
        self.join_preview_btn.setToolTip("Cria um único item rascunho na lista, juntando as cenas selecionadas antes de exportar.")
        self.join_preview_btn.clicked.connect(self._play_selected_scenes_joined)
        controls_layout.addWidget(self.join_preview_btn)

        self.export_selected_btn = QPushButton("Exportar MP4")
        self.export_selected_btn.setToolTip("Exporta a cena/clipe selecionado com corte preciso em MP4.")
        self.export_selected_btn.clicked.connect(self._export_selected_scenes)
        controls_layout.addWidget(self.export_selected_btn)

        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        help_label = QLabel(
            "Selecione uma cena e use Play/Pause. O Play continua de onde parou; Parar volta ao início do trecho."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(help_label)

        return tab

    def _create_catalog_tab(self) -> QWidget:
        tab = QWidget()
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)

        self.scene_info_label = QLabel("Nenhuma cena selecionada")
        self.scene_info_label.setWordWrap(True)
        self.scene_info_label.setMaximumHeight(46)
        self.scene_info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scene_info_label.setStyleSheet("font-weight: bold;")
        outer_layout.addWidget(self.scene_info_label)

        self.catalog_splitter = QSplitter(Qt.Vertical)
        self.catalog_splitter.setChildrenCollapsible(False)
        self.catalog_splitter.setMinimumHeight(300)

        meta_panel = QWidget()
        meta_layout = QVBoxLayout(meta_panel)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(8)

        row_layout = QHBoxLayout()
        row_layout.addWidget(QLabel("Tipo:"))
        self.scene_type_combo = QComboBox()
        self.scene_type_combo.addItems(self.SCENE_TYPES)
        row_layout.addWidget(self.scene_type_combo, stretch=1)
        self.favorite_check = QCheckBox("Destaque")
        row_layout.addWidget(self.favorite_check)
        meta_layout.addLayout(row_layout)

        meta_layout.addWidget(QLabel("Tags:"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Ex.: luta, tensão, transformação")
        meta_layout.addWidget(self.tags_edit)

        meta_hint = QLabel("Arraste a divisória abaixo para aumentar ou diminuir o campo de descrição.")
        meta_hint.setWordWrap(True)
        meta_hint.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        meta_layout.addWidget(meta_hint)
        self.catalog_splitter.addWidget(meta_panel)

        description_panel = QWidget()
        description_layout = QVBoxLayout(description_panel)
        description_layout.setContentsMargins(0, 0, 0, 0)
        description_layout.setSpacing(6)
        description_layout.addWidget(QLabel("Descrição:"))

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Descrição automática da cena. Edite se estiver errado.")
        self.description_edit.setAcceptRichText(False)
        self.description_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.description_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.description_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.description_edit.setMinimumHeight(260)
        self.description_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.description_edit.setStyleSheet(
            "QTextEdit { padding: 8px; border: 1px solid #3c3c3c; background: #1f1f1f; }"
            "QTextEdit:focus { border: 1px solid #5a7ec8; }"
        )
        description_layout.addWidget(self.description_edit, stretch=1)

        description_scroll_hint = QLabel("Use a barra de rolagem dentro do campo para revisar textos longos da IA.")
        description_scroll_hint.setWordWrap(True)
        description_scroll_hint.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        description_layout.addWidget(description_scroll_hint)
        self.catalog_splitter.addWidget(description_panel)

        self.catalog_splitter.setStretchFactor(0, 0)
        self.catalog_splitter.setStretchFactor(1, 1)
        self.catalog_splitter.setSizes([105, 520])
        outer_layout.addWidget(self.catalog_splitter, stretch=1)

        actions_group = QGroupBox("Ações e IA online")
        actions_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        actions_layout = QGridLayout(actions_group)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setHorizontalSpacing(8)
        actions_layout.setVerticalSpacing(6)

        self.save_catalog_btn = QPushButton("Salvar descrição/tags")
        self.save_catalog_btn.setMinimumWidth(150)
        self.save_catalog_btn.clicked.connect(self._save_scene_catalog)
        actions_layout.addWidget(self.save_catalog_btn, 0, 0)

        self.generate_ai_btn = QPushButton("Analisar cena com IA")
        self.generate_ai_btn.setMinimumWidth(170)
        self.generate_ai_btn.setToolTip("Gera descrição, tags, tipo e potencial usando Gemini API. O PC só envia 1 frame comprimido.")
        self.generate_ai_btn.clicked.connect(self._on_generate_ai_current_clicked)
        actions_layout.addWidget(self.generate_ai_btn, 0, 1)

        self.generate_ai_selected_btn = QPushButton("Analisar selecionadas")
        self.generate_ai_selected_btn.setMinimumWidth(150)
        self.generate_ai_selected_btn.setToolTip("Gera descrição online para as cenas selecionadas, com aviso para evitar gasto de cota.")
        self.generate_ai_selected_btn.clicked.connect(self._on_generate_ai_selected_clicked)
        actions_layout.addWidget(self.generate_ai_selected_btn, 0, 2)

        key_label = QLabel("API Key:")
        actions_layout.addWidget(key_label, 1, 0)
        saved_key = self.api_settings.get_gemini_api_key() if hasattr(self, "api_settings") else ""
        self.gemini_api_key_edit = QLineEdit(saved_key)
        self.gemini_api_key_edit.setMinimumWidth(240)
        self.gemini_api_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_api_key_edit.setPlaceholderText("Cole sua chave do Google AI Studio")
        self.gemini_api_key_edit.setToolTip("Chave gratuita do Google AI Studio. Pode ser salva localmente neste PC.")
        actions_layout.addWidget(self.gemini_api_key_edit, 1, 1, 1, 2)

        self.save_api_key_checkbox = QCheckBox("Salvar chave neste PC")
        self.save_api_key_checkbox.setChecked(bool(saved_key))
        self.save_api_key_checkbox.setToolTip("Salva a chave em data/settings/api_settings.json. É local, mas não criptografado.")
        actions_layout.addWidget(self.save_api_key_checkbox, 2, 1)

        api_key_buttons_layout = QHBoxLayout()
        self.save_api_key_btn = QPushButton("Salvar chave")
        self.save_api_key_btn.setMinimumWidth(110)
        self.save_api_key_btn.clicked.connect(self._save_gemini_settings_from_fields)
        api_key_buttons_layout.addWidget(self.save_api_key_btn)
        self.clear_api_key_btn = QPushButton("Apagar chave")
        self.clear_api_key_btn.setMinimumWidth(110)
        self.clear_api_key_btn.clicked.connect(self._clear_saved_gemini_api_key)
        api_key_buttons_layout.addWidget(self.clear_api_key_btn)
        api_key_buttons_widget = QWidget()
        api_key_buttons_widget.setLayout(api_key_buttons_layout)
        actions_layout.addWidget(api_key_buttons_widget, 2, 2)

        model_label = QLabel("Modelo:")
        actions_layout.addWidget(model_label, 3, 0)
        saved_model = self.api_settings.get_gemini_model("gemini-3.1-flash-lite") if hasattr(self, "api_settings") else "gemini-3.1-flash-lite"
        self.gemini_model_edit = QLineEdit(saved_model or "gemini-3.1-flash-lite")
        self.gemini_model_edit.setMinimumWidth(240)
        self.gemini_model_edit.setToolTip("Modelo Gemini. Sugestão: gemini-3.1-flash-lite. Alternativa leve: gemini-2.5-flash-lite.")
        actions_layout.addWidget(self.gemini_model_edit, 3, 1)

        self.test_ollama_btn = QPushButton("Testar Gemini")
        self.test_ollama_btn.setMinimumWidth(150)
        self.test_ollama_btn.setToolTip("Testa API Key e modelo Gemini com uma chamada pequena.")
        self.test_ollama_btn.clicked.connect(self._test_ollama_connection)
        actions_layout.addWidget(self.test_ollama_btn, 3, 2)

        actions_hint = QLabel("Fluxo recomendado: detecte cenas → selecione as melhores → use IA nas selecionadas. Use Catalogar básico só para miniaturas/descrição local simples.")
        actions_hint.setWordWrap(True)
        actions_hint.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        actions_layout.addWidget(actions_hint, 4, 0, 1, 3)

        actions_layout.setColumnMinimumWidth(0, 150)
        actions_layout.setColumnMinimumWidth(2, 150)
        actions_layout.setColumnStretch(0, 0)
        actions_layout.setColumnStretch(1, 1)
        actions_layout.setColumnStretch(2, 0)
        outer_layout.addWidget(actions_group, stretch=0)

        return tab

    def _create_trim_tab(self) -> QWidget:
        tab = QWidget()
        trim_layout = QVBoxLayout(tab)
        trim_layout.setContentsMargins(8, 8, 8, 8)
        trim_layout.setSpacing(10)

        trim_hint = QLabel(
            "Ajuste início/fim e crie uma nova marcação de corte. "
            "O original não é alterado; o app só salva um novo item rascunho com esse intervalo."
        )
        trim_hint.setWordWrap(True)
        trim_hint.setStyleSheet("color: #aaaaaa;")
        trim_layout.addWidget(trim_hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        start_line = QHBoxLayout()
        self.trim_start_spin = QDoubleSpinBox()
        self.trim_start_spin.setRange(0.0, 999999.0)
        self.trim_start_spin.setDecimals(3)
        self.trim_start_spin.setSingleStep(0.5)
        start_line.addWidget(self.trim_start_spin, stretch=1)
        self.set_start_btn = QPushButton("Usar posição atual")
        self.set_start_btn.clicked.connect(self._set_trim_start_to_current)
        start_line.addWidget(self.set_start_btn)
        form.addRow("Início corte (s):", start_line)

        end_line = QHBoxLayout()
        self.trim_end_spin = QDoubleSpinBox()
        self.trim_end_spin.setRange(0.0, 999999.0)
        self.trim_end_spin.setDecimals(3)
        self.trim_end_spin.setSingleStep(0.5)
        end_line.addWidget(self.trim_end_spin, stretch=1)
        self.set_end_btn = QPushButton("Usar posição atual")
        self.set_end_btn.clicked.connect(self._set_trim_end_to_current)
        end_line.addWidget(self.set_end_btn)
        form.addRow("Fim corte (s):", end_line)

        trim_layout.addLayout(form)

        trim_actions = QHBoxLayout()
        self.preview_trim_btn = QPushButton("Preview do corte")
        self.preview_trim_btn.clicked.connect(self._preview_trimmed_scene)
        trim_actions.addWidget(self.preview_trim_btn)

        self.save_trim_btn = QPushButton("Criar marcação de corte")
        self.save_trim_btn.clicked.connect(self._save_scene_trim)
        trim_actions.addWidget(self.save_trim_btn)

        self.reset_trim_btn = QPushButton("Resetar corte")
        self.reset_trim_btn.clicked.connect(self._reset_scene_trim)
        trim_actions.addWidget(self.reset_trim_btn)

        trim_actions.addStretch()
        trim_layout.addLayout(trim_actions)

        self.create_clip_btn = QPushButton("Exportar corte/clipe em MP4")
        self.create_clip_btn.setEnabled(True)
        self.create_clip_btn.setToolTip("Exporta a marcação selecionada usando FFmpeg com corte preciso.")
        self.create_clip_btn.clicked.connect(self._export_selected_scenes)
        trim_layout.addWidget(self.create_clip_btn)
        trim_layout.addStretch()
        return tab

    def _create_info_tab(self) -> QWidget:
        tab = QWidget()
        info_layout = QHBoxLayout(tab)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(12)

        self.thumbnail_label = QLabel("Sem miniatura")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setMinimumSize(420, 236)
        self.thumbnail_label.setFrameShape(QFrame.Box)
        self.thumbnail_label.setStyleSheet("background: #181818; color: #cccccc;")
        info_layout.addWidget(self.thumbnail_label, stretch=2)

        side_info = QVBoxLayout()
        self.ai_status_label = QLabel("Status: —")
        self.ai_status_label.setWordWrap(True)
        side_info.addWidget(self.ai_status_label)

        ai_note = QLabel(
            "Descrição IA segura: usa Gemini API gratuita/online quando você informar uma API Key. "
            "O app envia apenas 1 frame comprimido da cena selecionada, evitando IA visual pesada no seu PC. "
            "Processe poucas cenas por vez para economizar cota."
        )
        ai_note.setWordWrap(True)
        ai_note.setStyleSheet("color: #aaaaaa;")
        side_info.addWidget(ai_note)
        side_info.addStretch()
        info_layout.addLayout(side_info, stretch=1)

        return tab

    def _setup_player(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.audio_output.setVolume(0.6)

        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(200)
        self.preview_timer.timeout.connect(self._enforce_scene_bounds)

    def _load_media_options(self) -> None:
        """Carregar mídias disponíveis usando filtros Anime/Pasta > Temporada > Episódio."""
        current_folder = self.folder_combo.currentText() if hasattr(self, "folder_combo") else ""
        current_season = self.season_combo.currentText() if hasattr(self, "season_combo") else ""
        current_media_id = self._selected_media_id()

        try:
            self._all_media_files = self.repository.find_all(limit=5000, order_by="name_natural", descending=False)
        except Exception as exc:
            logger.error("Erro ao carregar mídias para detecção: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar episódios: {exc}")
            self._all_media_files = []

        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        folders = sorted({self._media_folder(media) for media in self._all_media_files}, key=str.casefold)
        if not folders:
            self.folder_combo.addItem("Nenhum anime importado")
        else:
            self.folder_combo.addItems(folders)
            index = self.folder_combo.findText(current_folder)
            self.folder_combo.setCurrentIndex(index if index >= 0 else 0)
        self.folder_combo.blockSignals(False)

        self._populate_season_combo(preferred_season=current_season, preferred_media_id=current_media_id)
        self._update_action_buttons()

    def _media_folder(self, media: object) -> str:
        return str(getattr(media, "custom_metadata", {}).get("library_folder") or "Sem pasta")

    def _media_season(self, media: object) -> str:
        return str(getattr(media, "custom_metadata", {}).get("library_season") or "Sem temporada")

    def _on_folder_changed(self, index: int) -> None:
        self._stop_preview()
        self._populate_season_combo()

    def _on_season_changed(self, index: int) -> None:
        self._stop_preview()
        self._populate_episode_combo()

    def _populate_season_combo(self, preferred_season: str = "", preferred_media_id: object = None) -> None:
        folder = self.folder_combo.currentText()
        seasons = sorted(
            {self._media_season(media) for media in self._all_media_files if self._media_folder(media) == folder},
            key=self._natural_key,
        )
        self.season_combo.blockSignals(True)
        self.season_combo.clear()
        if seasons:
            self.season_combo.addItems(seasons)
            index = self.season_combo.findText(preferred_season)
            self.season_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.season_combo.addItem("Nenhuma temporada")
        self.season_combo.blockSignals(False)
        self._populate_episode_combo(preferred_media_id=preferred_media_id)

    def _populate_episode_combo(self, preferred_media_id: object = None) -> None:
        folder = self.folder_combo.currentText()
        season = self.season_combo.currentText()
        media_files = [
            media for media in self._all_media_files
            if self._media_folder(media) == folder and self._media_season(media) == season
        ]
        media_files.sort(key=lambda media: self._natural_key(media.file_info.file_name))

        self.media_combo.blockSignals(True)
        self.media_combo.clear()
        self._media_by_combo_index.clear()

        if not media_files:
            self.media_combo.addItem("Nenhum episódio nesta temporada")
            selected_index = 0
        else:
            selected_index = 0
            for index, media in enumerate(media_files):
                self.media_combo.addItem(media.file_info.file_name)
                self._media_by_combo_index[index] = media
                if preferred_media_id and media.id and str(media.id) == str(preferred_media_id):
                    selected_index = index
            self.media_combo.setCurrentIndex(selected_index)

        self.media_combo.blockSignals(False)
        self._load_scenes_for_selected_media()
        self._update_action_buttons()

    def _selected_media_obj(self):
        return self._media_by_combo_index.get(self.media_combo.currentIndex())

    def _selected_media_id(self) -> Optional[object]:
        media = self._selected_media_obj()
        return media.id if media else None

    def _on_media_changed(self, index: int) -> None:
        self._stop_preview()
        self._load_scenes_for_selected_media()

    def _on_detection_preset_changed(self, preset: str) -> None:
        """Aplicar presets humanos de detecção para evitar números confusos."""
        if preset == "Personalizado":
            return

        presets = {
            "Mais cortes": (0.10, 2.0),
            "Anime equilibrado": (0.15, 4.0),
            "Menos cortes": (0.20, 5.0),
            "Cenas longas": (0.25, 8.0),
        }
        threshold, min_seconds = presets.get(preset, (0.15, 4.0))
        self._applying_detection_preset = True
        try:
            self.threshold_spin.setValue(threshold)
            self.min_scene_spin.setValue(min_seconds)
        finally:
            self._applying_detection_preset = False

        self.status_label.setText(
            f"Preset aplicado: {preset}. "
            f"Limiar {threshold:.2f}; cena mínima {min_seconds:.1f}s. "
            "Menor limiar cria mais cortes; cena mínima alta junta cortes pequenos."
        )

    def _mark_detection_preset_custom(self) -> None:
        """Quando o usuário altera os números manualmente, marca como Personalizado."""
        if getattr(self, "_applying_detection_preset", False):
            return
        if hasattr(self, "detection_preset_combo"):
            index = self.detection_preset_combo.findText("Personalizado")
            if index >= 0 and self.detection_preset_combo.currentIndex() != index:
                self.detection_preset_combo.blockSignals(True)
                self.detection_preset_combo.setCurrentIndex(index)
                self.detection_preset_combo.blockSignals(False)

    def _validate_detection_settings(self) -> bool:
        """Evitar configurações que parecem travamento ou geram poucas cenas enormes."""
        threshold = float(self.threshold_spin.value())
        min_seconds = float(self.min_scene_spin.value())

        if min_seconds >= 15.0:
            reply = QMessageBox.warning(
                self,
                "Cena mínima muito alta",
                f"Você configurou cena mínima em {min_seconds:.1f}s.\n\n"
                "Em anime, isso costuma juntar muitos cortes e gerar poucas cenas enormes.\n"
                "Recomendado para anime: 2s a 6s.\n\n"
                "Deseja continuar mesmo assim?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False

        if threshold <= 0.08 and min_seconds >= 8.0:
            reply = QMessageBox.warning(
                self,
                "Configuração contraditória",
                "Você escolheu um limiar baixo, que tenta criar mais cortes, mas também uma cena mínima alta, "
                "que junta cortes pequenos.\n\n"
                "Isso pode gerar um resultado estranho. Para anime, tente:\n"
                "• Mais cortes: limiar 0.10 e mínimo 2s\n"
                "• Equilibrado: limiar 0.15 e mínimo 4s\n\n"
                "Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return False

        return True

    def _on_detect_clicked(self) -> None:
        """Detectar apenas os intervalos das cenas, sem catalogar tudo junto."""
        media = self._selected_media_obj()
        if not media:
            QMessageBox.information(self, "Detecção de Cenas", "Selecione Anime/Pasta, Temporada e Episódio válidos.")
            return

        file_path = media.file_info.file_path
        if not Path(file_path).exists():
            QMessageBox.critical(self, "Arquivo não encontrado", f"O arquivo original não foi encontrado:\n{file_path}")
            return

        existing_count = self.repository.get_scene_count(media.id)
        if existing_count > 0:
            reply = QMessageBox.question(
                self,
                "Substituir cenas?",
                f"Este episódio já tem {existing_count} cena(s) detectada(s).\n\n"
                "Detectar novamente vai substituir a lista atual de cenas. Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        if not self._validate_detection_settings():
            return

        duration = media.video_info.duration.seconds if media.video_info.duration else 0.0
        self._set_busy(True, "Preparando detecção otimizada em segundo plano...")
        worker = _SceneDetectionWorker(
            detector=self.scene_detector,
            file_path=file_path,
            duration_seconds=duration,
            threshold=self.threshold_spin.value(),
            min_scene_seconds=self.min_scene_spin.value(),
        )
        self._start_worker(worker, self._on_detection_worker_finished, operation="detect")

    def _on_detection_worker_finished(self, scenes: list[Dict[str, Any]]) -> None:
        media = self._selected_media_obj()
        try:
            if not media:
                return
            saved = self.repository.save_detected_scenes(media.id, scenes, self.threshold_spin.value())
            self.status_label.setText(
                f"Detecção rápida concluída: {saved} cena(s) salva(s). "
                f"Configuração: {self.detection_preset_combo.currentText()} | "
                f"limiar {self.threshold_spin.value():.2f} | mínimo {self.min_scene_spin.value():.1f}s. "
                "Agora use 'Catalogar básico' para miniatura local ou 'IA nas selecionadas' para descrição inteligente."
            )
            self._load_scenes_for_selected_media(select_first=True)
            if saved >= 80:
                QMessageBox.information(
                    self,
                    "Muitas cenas detectadas",
                    f"Foram detectadas {saved} cenas. Isso é normal em anime.\n\n"
                    "Recomendação: selecione apenas as cenas que interessam e clique em 'IA nas selecionadas' ou 'Catalogar básico'. "
                    "Use 'Menos cortes' se quiser uma lista mais curta.",
                )
        finally:
            self._set_busy(False)

    def _on_catalog_selected_clicked(self) -> None:
        scenes = [self._scenes_by_row[row] for row in self._selected_rows() if row in self._scenes_by_row]
        if not scenes and self._selected_scene:
            scenes = [self._selected_scene]
        if not scenes:
            QMessageBox.information(
                self,
                "Catalogar básico",
                "Selecione uma cena na lista. Essa ação gera apenas miniatura/descrição simples local, sem API.",
            )
            return
        self._start_catalog_worker(scenes)

    def _on_catalog_all_clicked(self) -> None:
        scenes = list(self._scenes_by_row.values())
        if not scenes:
            QMessageBox.information(self, "Catalogar básico", "Detecte as cenas deste episódio antes de catalogar.")
            return
        if len(scenes) > 50:
            reply = QMessageBox.question(
                self,
                "Catalogação básica em todas?",
                f"Você está prestes a gerar miniaturas/descrições locais simples para {len(scenes)} cenas.\n\n"
                "Isso não usa API, mas pode demorar em arquivos grandes. O programa continuará responsivo.\n\n"
                "Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self._start_catalog_worker(scenes)

    def _start_catalog_worker(self, scenes: list[Dict[str, Any]]) -> None:
        media = self._selected_media_obj()
        if not media:
            return
        file_path = media.file_info.file_path
        if not Path(file_path).exists():
            QMessageBox.critical(self, "Arquivo não encontrado", f"O arquivo original não foi encontrado:\n{file_path}")
            return
        self._set_busy(True, f"Catalogação básica local: processando {len(scenes)} cena(s) em segundo plano...")
        worker = _SceneCatalogWorker(
            detector=self.scene_detector,
            file_path=file_path,
            media_id=media.id,
            scenes=scenes,
            frames_per_scene=1,
        )
        self._start_worker(worker, self._on_catalog_worker_finished, operation="catalog")

    def _on_catalog_worker_finished(self, scenes: list[Dict[str, Any]]) -> None:
        updated = 0
        current_scene_id = self._selected_scene.get("id") if self._selected_scene else None
        try:
            for scene in scenes:
                scene_id = scene.get("id")
                if not scene_id:
                    continue
                if self.repository.update_scene_visual_catalog(
                    scene_id=scene_id,
                    description=scene.get("description"),
                    tags=scene.get("tags"),
                    scene_type=scene.get("scene_type"),
                    thumbnail_path=scene.get("thumbnail_path"),
                    analysis_frames_json=scene.get("analysis_frames_json"),
                    ai_status=scene.get("ai_status") or "auto_local",
                ):
                    updated += 1
            self.status_label.setText(f"Catalogação básica concluída: {updated} cena(s) atualizada(s). Use IA nas selecionadas para descrição inteligente.")
            self._load_scenes_for_selected_media(select_scene_id=current_scene_id, select_first=False)
        finally:
            self._set_busy(False)

    def _start_worker(self, worker: QObject, finished_handler, operation: str) -> None:
        if self._active_thread is not None:
            QMessageBox.information(self, "Operação em andamento", "Aguarde a operação atual terminar ou clique em Cancelar.")
            return
        thread = QThread(self)
        self._active_thread = thread
        self._active_worker = worker
        self._active_operation = operation
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(finished_handler)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_active_worker)
        thread.start()

    def _cancel_active_operation(self) -> None:
        if self._active_worker and hasattr(self._active_worker, "cancel"):
            self._active_worker.cancel()
            self.status_label.setText("Cancelamento solicitado. Aguarde o processo atual encerrar com segurança...")
            self.cancel_btn.setEnabled(False)

    def _on_worker_failed(self, message: str) -> None:
        logger.error("Operação de cenas falhou: %s", message)
        self.status_label.setText(f"Operação interrompida: {message}")
        if "cancelada" not in str(message).lower():
            QMessageBox.critical(self, "Erro", str(message))
        self._set_busy(False)

    def _clear_active_worker(self) -> None:
        self._active_thread = None
        self._active_worker = None
        self._active_operation = None

    def _set_busy(self, busy: bool, status: str = "") -> None:
        self.detect_btn.setEnabled(not busy and self._selected_media_obj() is not None)
        self.catalog_selected_btn.setEnabled(not busy)
        self.catalog_all_btn.setEnabled(not busy)
        if hasattr(self, "generate_ai_btn"):
            self.generate_ai_btn.setEnabled(not busy)
        if hasattr(self, "generate_ai_selected_btn"):
            self.generate_ai_selected_btn.setEnabled(not busy)
        if hasattr(self, "ai_selected_top_btn"):
            self.ai_selected_top_btn.setEnabled(not busy)
        if hasattr(self, "test_ollama_btn"):
            self.test_ollama_btn.setEnabled(not busy)
        self.clear_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.folder_combo.setEnabled(not busy)
        self.season_combo.setEnabled(not busy)
        self.media_combo.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        if hasattr(self, "generate_ai_btn"):
            self.generate_ai_btn.setEnabled(not busy)
        if hasattr(self, "generate_ai_selected_btn"):
            self.generate_ai_selected_btn.setEnabled(not busy)
        if hasattr(self, "ai_selected_top_btn"):
            self.ai_selected_top_btn.setEnabled(not busy)
        if hasattr(self, "test_ollama_btn"):
            self.test_ollama_btn.setEnabled(not busy)
        if hasattr(self, "gemini_model_edit"):
            self.gemini_model_edit.setEnabled(not busy)
        if hasattr(self, "gemini_api_key_edit"):
            self.gemini_api_key_edit.setEnabled(not busy)
        for attr in ("save_api_key_checkbox", "save_api_key_btn", "clear_api_key_btn"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setEnabled(not busy)
        if status:
            self.status_label.setText(status)

    def _update_action_buttons(self) -> None:
        has_media = self._selected_media_obj() is not None
        busy = self._active_thread is not None
        self.detect_btn.setEnabled(has_media and not busy)
        self.clear_btn.setEnabled(has_media and not busy)
        self.catalog_selected_btn.setEnabled(not busy)
        self.catalog_all_btn.setEnabled(not busy)
        if hasattr(self, "generate_ai_btn"):
            self.generate_ai_btn.setEnabled(not busy)
        if hasattr(self, "generate_ai_selected_btn"):
            self.generate_ai_selected_btn.setEnabled(not busy)
        if hasattr(self, "ai_selected_top_btn"):
            self.ai_selected_top_btn.setEnabled(not busy)
        if hasattr(self, "test_ollama_btn"):
            self.test_ollama_btn.setEnabled(not busy)

    def _on_clear_clicked(self) -> None:
        media = self._selected_media_obj()
        if not media:
            return

        count = self.repository.get_scene_count(media.id)
        if count <= 0:
            QMessageBox.information(self, "Limpar cenas", "Este episódio não tem cenas salvas.")
            return

        reply = QMessageBox.question(
            self,
            "Limpar cenas",
            f"Deseja remover as {count} cena(s) detectada(s) deste episódio?\n\n"
            "Isso não apaga o vídeo original nem as futuras exportações.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        removed = self.repository.clear_scenes_for_media(media.id)
        self._selected_scene = None
        self._clear_detail_panel()
        self.status_label.setText(f"{removed} cena(s) removida(s).")
        self._load_scenes_for_selected_media()

    def _load_scenes_for_selected_media(self, select_scene_id: object = None, select_first: bool = True) -> None:
        media = self._selected_media_obj()
        self._selected_media = media
        self._selected_scene = None
        self._scenes_by_row.clear()
        self.table.setRowCount(0)
        self._clear_detail_panel()

        if not media:
            self.status_label.setText("Nenhum episódio selecionado.")
            return

        try:
            scenes = self.repository.get_scenes_by_media(media.id)
        except Exception as exc:
            logger.error("Erro ao carregar cenas: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar cenas: {exc}")
            return

        if not scenes:
            self.status_label.setText("Nenhuma cena detectada para este episódio.")
            return

        self.table.setRowCount(len(scenes))
        for row, scene in enumerate(scenes):
            self._scenes_by_row[row] = scene
            self.table.setRowHeight(row, 64)

            thumb_item = QTableWidgetItem()
            thumbnail_path = scene.get("thumbnail_path")
            if thumbnail_path and Path(str(thumbnail_path)).exists():
                pixmap = QPixmap(str(thumbnail_path)).scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb_item.setData(Qt.DecorationRole, pixmap)
            else:
                thumb_item.setText("—")
            self.table.setItem(row, 0, thumb_item)

            display_name = scene.get("display_name") or f"Cena {int(scene['scene_number']):03d}"
            self.table.setItem(row, 1, QTableWidgetItem(str(display_name)))
            self.table.setItem(row, 2, QTableWidgetItem(self._format_time(scene["start_seconds"])))
            self.table.setItem(row, 3, QTableWidgetItem(self._format_time(scene["end_seconds"])))
            duration_label = self._format_time(self._clip_duration_seconds(scene))
            if scene.get("custom_start_seconds") is not None or scene.get("custom_end_seconds") is not None:
                duration_label += " ✂"
            if int(scene.get("is_merged") or 0):
                duration_label += " 🔗"
            self.table.setItem(row, 4, QTableWidgetItem(duration_label))
            self.table.setItem(row, 5, QTableWidgetItem(str(scene.get("scene_type") or "Geral")))
            self.table.setItem(row, 6, QTableWidgetItem(str(scene.get("tags") or "")))
            self.table.setItem(row, 7, QTableWidgetItem(str(scene.get("description") or "")))
            self.table.setItem(row, 8, QTableWidgetItem("★" if int(scene.get("is_favorite") or 0) else ""))

        self.status_label.setText(f"{len(scenes)} cena(s) carregada(s) para {media.file_info.file_name}.")
        if select_scene_id is not None:
            self._select_scene_by_id(select_scene_id)
        elif select_first:
            self.table.selectRow(0)

    def _on_scene_selected(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not selected_rows:
            self._selected_scene = None
            self._clear_detail_panel()
            return

        row = selected_rows[0].row()
        scene = self._scenes_by_row.get(row)
        if not scene:
            return

        self._selected_scene = scene
        self._populate_detail_panel(scene)

        # Não reproduzir automaticamente ao selecionar/carregar cena.
        # O preview só começa quando o usuário clica em Reproduzir, dá duplo clique
        # na cena ou usa Preview do corte / Juntar selecionadas.
        self._prepare_preview_for_scene(scene)
        display_name = scene.get("display_name") or f"Cena {int(scene.get('scene_number') or 0):03d}"
        self.status_label.setText(
            f"{display_name} selecionado. "
            "Clique em Reproduzir ou arraste a linha do tempo para navegar no trecho."
        )

    def _populate_detail_panel(self, scene: Dict[str, Any]) -> None:
        self._ignore_field_changes = True
        try:
            number = int(scene.get("scene_number") or 0)
            display_name = scene.get("display_name") or f"Cena {number:03d}"
            self.scene_info_label.setText(
                f"{display_name} | {self._format_time(scene.get('start_seconds'))} → "
                f"{self._format_time(scene.get('end_seconds'))} | "
                f"Duração do clipe: {self._format_time(self._clip_duration_seconds(scene))}"
            )
            trim_start, trim_end = self._effective_scene_bounds(scene)
            self.trim_start_spin.setValue(float(trim_start))
            self.trim_end_spin.setValue(float(trim_end))
            self.description_edit.setPlainText(str(scene.get("description") or ""))
            self.tags_edit.setText(str(scene.get("tags") or ""))

            scene_type = str(scene.get("scene_type") or "Geral")
            index = self.scene_type_combo.findText(scene_type)
            if index < 0:
                self.scene_type_combo.addItem(scene_type)
                index = self.scene_type_combo.findText(scene_type)
            self.scene_type_combo.setCurrentIndex(max(index, 0))
            self.favorite_check.setChecked(bool(int(scene.get("is_favorite") or 0)))
            self.ai_status_label.setText(f"Status descrição: {self._human_ai_status(scene.get('ai_status'))}")

            thumbnail_path = scene.get("thumbnail_path")
            if thumbnail_path and Path(str(thumbnail_path)).exists():
                pixmap = QPixmap(str(thumbnail_path)).scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.thumbnail_label.setPixmap(pixmap)
                self.thumbnail_label.setText("")
            else:
                self.thumbnail_label.setPixmap(QPixmap())
                self.thumbnail_label.setText("Sem miniatura")
        finally:
            self._ignore_field_changes = False

    def _clear_detail_panel(self) -> None:
        self.scene_info_label.setText("Nenhuma cena selecionada")
        self.thumbnail_label.setPixmap(QPixmap())
        self.thumbnail_label.setText("Sem miniatura")
        self.description_edit.clear()
        self.tags_edit.clear()
        self.scene_type_combo.setCurrentIndex(0)
        self.favorite_check.setChecked(False)
        self.trim_start_spin.setValue(0.0)
        self.trim_end_spin.setValue(0.0)
        self.ai_status_label.setText("Status: —")

    def _save_scene_catalog(self) -> None:
        if not self._selected_scene:
            QMessageBox.information(self, "Catálogo", "Selecione uma cena para salvar.")
            return

        try:
            scene_id = self._selected_scene["id"]
            elapsed_ms = self._current_preview_elapsed_ms()
            tab_index = self.detail_tabs.currentIndex()
            ok = self.repository.update_scene_catalog(
                scene_id=scene_id,
                description=self.description_edit.toPlainText(),
                tags=self.tags_edit.text(),
                scene_type=self.scene_type_combo.currentText(),
                is_favorite=self.favorite_check.isChecked(),
            )
            if ok:
                self.status_label.setText("Descrição/tags da cena salvas.")
                self._reload_scenes_preserving_context(scene_id=scene_id, elapsed_ms=elapsed_ms, tab_index=tab_index)
            else:
                QMessageBox.warning(self, "Catálogo", "Não foi possível salvar a cena selecionada.")
        except Exception as exc:
            logger.error("Erro ao salvar catálogo da cena: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro ao salvar", str(exc))


    def _on_generate_ai_current_clicked(self) -> None:
        if not self._selected_scene:
            QMessageBox.information(self, "Descrição IA", "Selecione uma cena para gerar descrição com IA.")
            return
        self._start_ai_worker([self._selected_scene])

    def _on_generate_ai_selected_clicked(self) -> None:
        scenes = [self._scenes_by_row[row] for row in self._selected_rows() if row in self._scenes_by_row]
        if not scenes and self._selected_scene:
            scenes = [self._selected_scene]
        if not scenes:
            QMessageBox.information(self, "Descrição IA", "Selecione uma ou mais cenas na lista.")
            return

        if len(scenes) > 1:
            reply = QMessageBox.question(
                self,
                "Usar IA nas selecionadas?",
                f"Você selecionou {len(scenes)} cena(s).\n\n"
                "Cada cena usa uma chamada da Gemini API e consome cota gratuita. "
                "O app enviará apenas 1 frame comprimido por cena.\n\n"
                "Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No if len(scenes) > 10 else QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return
        self._start_ai_worker(scenes)

    def _start_ai_worker(self, scenes: list[Dict[str, Any]]) -> None:
        media = self._selected_media_obj()
        if not media:
            QMessageBox.information(self, "Descrição IA", "Selecione um episódio válido.")
            return
        file_path = media.file_info.file_path
        if not Path(file_path).exists():
            QMessageBox.critical(self, "Arquivo não encontrado", f"O arquivo original não foi encontrado:\n{file_path}")
            return

        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        if not api_key:
            QMessageBox.warning(
                self,
                "API Key necessária",
                "Cole sua API Key gratuita do Gemini antes de gerar a descrição online.\n\n"
                "A chave não é salva pelo app nesta sprint. Você também pode definir a variável de ambiente GEMINI_API_KEY."
            )
            return

        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else "gemini-3.1-flash-lite"
        if not model:
            model = "gemini-3.1-flash-lite"
            if hasattr(self, "gemini_model_edit"):
                self.gemini_model_edit.setText(model)
        self._maybe_save_gemini_settings(api_key, model)

        media_context = {
            "anime": self.folder_combo.currentText(),
            "season": self.season_combo.currentText(),
            "episode": media.file_info.file_name,
        }
        self._set_busy(True, f"Preparando descrição online segura para {len(scenes)} cena(s). Enviando 1 frame comprimido por cena...")
        worker = _SceneAIWorker(
            detector=self.scene_detector,
            ai_service=self.ai_service,
            file_path=file_path,
            media_id=media.id,
            media_context=media_context,
            scenes=scenes,
            api_key=api_key,
            model=model,
            max_frames=1,
        )
        self._start_worker(worker, self._on_ai_worker_finished, operation="ai_description")

    def _on_ai_worker_finished(self, results: list[Dict[str, Any]]) -> None:
        updated = 0
        current_scene_id = self._selected_scene.get("id") if self._selected_scene else None
        try:
            for result in results:
                scene_id = result.get("id")
                if not scene_id:
                    continue
                if self.repository.update_scene_visual_catalog(
                    scene_id=scene_id,
                    description=result.get("description"),
                    tags=result.get("tags"),
                    scene_type=result.get("scene_type"),
                    thumbnail_path=None,
                    analysis_frames_json=result.get("analysis_frames_json"),
                    ai_status=result.get("ai_status") or "gemini_api",
                ):
                    updated += 1
            self.status_label.setText(f"Descrição IA concluída: {updated} cena(s) atualizada(s).")
            self._load_scenes_for_selected_media(select_scene_id=current_scene_id, select_first=False)
        finally:
            self._set_busy(False)

    def _maybe_save_gemini_settings(self, api_key: str, model: str) -> None:
        checkbox = getattr(self, "save_api_key_checkbox", None)
        if checkbox is not None and checkbox.isChecked():
            try:
                self.api_settings.save_gemini(api_key=api_key, model=model)
            except Exception as exc:
                logger.warning("Não foi possível salvar a chave Gemini: %s", exc)

    def _save_gemini_settings_from_fields(self) -> None:
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else "gemini-3.1-flash-lite"
        if not api_key:
            QMessageBox.warning(self, "API Key vazia", "Cole uma API Key do Gemini antes de salvar.")
            return
        try:
            self.api_settings.save_gemini(api_key=api_key, model=model)
            if hasattr(self, "save_api_key_checkbox"):
                self.save_api_key_checkbox.setChecked(True)
            QMessageBox.information(self, "Chave salva", "API Key do Gemini salva localmente neste PC.")
            self.status_label.setText("API Key do Gemini salva localmente.")
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao salvar", f"Não foi possível salvar a API Key:\n{exc}")

    def _clear_saved_gemini_api_key(self) -> None:
        try:
            self.api_settings.clear_gemini_api_key()
            if hasattr(self, "gemini_api_key_edit"):
                self.gemini_api_key_edit.clear()
            if hasattr(self, "save_api_key_checkbox"):
                self.save_api_key_checkbox.setChecked(False)
            QMessageBox.information(self, "Chave apagada", "API Key salva foi apagada deste PC.")
            self.status_label.setText("API Key do Gemini apagada.")
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao apagar", f"Não foi possível apagar a API Key:\n{exc}")

    def _test_ollama_connection(self) -> None:
        """Testar Gemini API. Mantive o nome interno para reduzir alterações na tela."""
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else "gemini-3.1-flash-lite"
        if not api_key:
            QMessageBox.warning(
                self,
                "API Key necessária",
                "Cole sua API Key gratuita do Gemini no campo API Key.\n\n"
                "Nesta sprint, o app não salva a chave; ela fica apenas no campo da tela."
            )
            return
        if not model:
            model = "gemini-3.1-flash-lite"
            if hasattr(self, "gemini_model_edit"):
                self.gemini_model_edit.setText(model)

        try:
            self.status_label.setText("Testando Gemini API...")
            result = self.ai_service.test_connection(api_key=api_key, model=model)
            QMessageBox.information(
                self,
                "Gemini conectado",
                "Gemini API respondeu corretamente.\n\n"
                f"Modelo: {result.get('model') or model}\n"
                f"Resposta: {result.get('response') or 'OK'}\n\n"
                "Agora teste em uma cena curta com Analisar cena com IA."
            )
            self.status_label.setText(f"Gemini OK. Modelo selecionado: {result.get('model') or model}")
            self._maybe_save_gemini_settings(api_key, result.get('model') or model)
        except GeminiSceneAIError as exc:
            QMessageBox.warning(self, "Gemini não disponível", str(exc))
            self.status_label.setText(f"Gemini não disponível: {exc}")
        except Exception as exc:
            QMessageBox.warning(self, "Gemini não disponível", f"Não foi possível conectar à Gemini API: {exc}")
            self.status_label.setText(f"Gemini não disponível: {exc}")

    def _toggle_play_pause(self) -> None:
        """Alternar entre reproduzir e pausar sem reiniciar o trecho.

        Comportamento esperado:
        - Se estiver tocando, pausa e mantém a posição.
        - Se estiver pausado, continua exatamente de onde parou.
        - Se ainda não houver preview carregado, carrega a cena selecionada e toca.
        """
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.preview_timer.stop()
            self._update_play_button_state()
            return

        if self._preview_segments:
            self.player.play()
            self.preview_timer.start()
            self._update_play_button_state()
            return

        self._play_selected_scene()

    def _play_selected_scene(self) -> None:
        """Reproduzir a cena selecionada sem resetar quando já existe preview pausado."""
        media = self._selected_media
        scene = self._selected_scene
        if not media or not scene:
            return

        scene_id = scene.get("id")
        segments = self._segments_for_scene(scene)
        if not segments:
            return

        # Se a cena já está carregada no preview, apenas continue de onde parou.
        if self._preview_segments and self._preview_scene_id == scene_id:
            self.player.play()
            self.preview_timer.start()
            self._update_play_button_state()
        else:
            self._preview_scene_id = scene_id
            self._play_segments(segments, autoplay=True)

        display_name = scene.get("display_name") or f"Cena {int(scene.get('scene_number') or 0):03d}"
        self.status_label.setText(
            f"Reproduzindo {display_name}: duração {self._format_time(self._clip_duration_seconds(scene))}"
        )

    def _play_selected_scenes_joined(self) -> None:
        """Criar um item único de clipe rascunho a partir das cenas selecionadas."""
        media = self._selected_media
        if not media:
            return

        selected_rows = self._selected_rows()
        if len(selected_rows) < 2:
            QMessageBox.information(
                self,
                "Juntar em clipe rascunho",
                "Selecione duas ou mais cenas na tabela para criar um clipe rascunho.",
            )
            return

        scenes = [self._scenes_by_row[row] for row in selected_rows if row in self._scenes_by_row]
        scenes.sort(key=lambda item: float(item.get("start_seconds") or 0.0))

        default_name = f"Clipe juntado {len(scenes)} cenas"
        clip_name, ok_name = QInputDialog.getText(
            self,
            "Nome do clipe rascunho",
            "Digite o nome desta marcação/clipe rascunho:\n\n"
            "O MP4 final ainda não será gerado; isso cria apenas a marcação na lista.",
            text=default_name,
        )
        if not ok_name:
            return
        clip_name = (clip_name or default_name).strip()
        if not clip_name:
            clip_name = default_name

        reply = QMessageBox.question(
            self,
            "Criar clipe rascunho?",
            f"Criar '{clip_name}' juntando {len(scenes)} cena(s) selecionada(s)?\n\n"
            "Isso ainda não gera o MP4 final. O novo item aparece na lista como um clipe único "
            "e pode ser pré-visualizado, catalogado e ajustado antes da exportação.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            merged_scene = self.repository.create_merged_scene(media.id, scenes, display_name=clip_name)
            self.status_label.setText(
                f"Clipe rascunho criado: {merged_scene.get('display_name') or clip_name} "
                f"com duração {self._format_time(self._clip_duration_seconds(merged_scene))}."
            )
            self._reload_scenes_preserving_context(
                scene_id=merged_scene.get("id"),
                elapsed_ms=0,
                tab_index=0,
                select_first=False,
            )
        except Exception as exc:
            logger.error("Erro ao criar clipe rascunho: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro ao juntar cenas", str(exc))

    def _play_segments(self, segments: list[tuple[int, int]], autoplay: bool = True) -> None:
        """Carregar um ou mais trechos no player.

        A barra de timeline representa o clipe inteiro. Em clipes compostos,
        ela soma os trechos selecionados e permite avançar/voltar no conjunto.
        """
        media = self._selected_media
        if not media or not segments:
            return

        file_path = Path(media.file_info.file_path)
        if not file_path.exists():
            self.status_label.setText("Arquivo original não encontrado para preview.")
            return

        clean_segments: list[tuple[int, int]] = []
        for start_ms, end_ms in segments:
            start_ms = max(int(start_ms), 0)
            end_ms = max(int(end_ms), start_ms + 250)
            clean_segments.append((start_ms, end_ms))

        self._preview_segments = clean_segments
        self._current_segment_index = 0
        self.player.setSource(QUrl.fromLocalFile(str(file_path)))
        self._configure_slider_for_segments(clean_segments)
        self._activate_segment(0, autoplay=autoplay)

    def _prepare_preview_for_scene(self, scene: Dict[str, Any]) -> None:
        """Carregar o trecho no player sem tocar automaticamente."""
        segments = self._segments_for_scene(scene)
        if not segments:
            return
        self._preview_scene_id = scene.get("id")
        self._play_segments(segments, autoplay=False)

    def _activate_segment(self, index: int, autoplay: bool = True) -> None:
        if not self._preview_segments:
            return
        index = max(0, min(index, len(self._preview_segments) - 1))
        self._current_segment_index = index
        start_ms, end_ms = self._preview_segments[index]
        self._scene_start_ms = start_ms
        self._scene_end_ms = end_ms
        self._active_segment_start_ms = start_ms
        self._active_segment_end_ms = end_ms
        self.player.setPosition(start_ms)
        if autoplay:
            self.player.play()
            self.preview_timer.start()
        else:
            self.player.pause()
            self.preview_timer.stop()
            self._update_slider_for_position(start_ms)
        self._update_play_button_state()

    def _stop_preview(self) -> None:
        self.preview_timer.stop()
        self.player.stop()
        self._scene_start_ms = None
        self._scene_end_ms = None
        self._active_segment_start_ms = None
        self._active_segment_end_ms = None
        self._preview_segments = []
        self._preview_scene_id = None
        self._segment_offsets = []
        self._total_preview_duration_ms = 0
        self._current_segment_index = 0
        self.position_slider.setEnabled(False)
        self.current_time_label.setText("00:00:00.000")
        self.scene_time_label.setText("00:00:00.000")
        self._update_play_button_state()

    def _enforce_scene_bounds(self) -> None:
        if self._active_segment_end_ms is None:
            return
        if self.player.position() >= self._active_segment_end_ms:
            if self._preview_segments and self._current_segment_index + 1 < len(self._preview_segments):
                self._activate_segment(self._current_segment_index + 1, autoplay=True)
                return
            self.player.pause()
            self.preview_timer.stop()
            self._update_slider_for_position(self._active_segment_end_ms)
            self._update_play_button_state()

    def _configure_slider_for_segments(self, segments: list[tuple[int, int]]) -> None:
        offsets: list[int] = []
        total = 0
        for start_ms, end_ms in segments:
            offsets.append(total)
            total += max(int(end_ms) - int(start_ms), 1)
        self._segment_offsets = offsets
        self._total_preview_duration_ms = max(total, 1)
        self._updating_slider = True
        try:
            self.position_slider.setRange(0, self._total_preview_duration_ms)
            self.position_slider.setValue(0)
            self.position_slider.setEnabled(True)
            self.current_time_label.setText("00:00:00.000")
            self.scene_time_label.setText(self._format_time(self._total_preview_duration_ms / 1000.0))
        finally:
            self._updating_slider = False

    def _elapsed_from_absolute_position(self, position_ms: int) -> int:
        if not self._preview_segments or not self._segment_offsets:
            return 0
        idx = max(0, min(self._current_segment_index, len(self._preview_segments) - 1))
        start_ms, end_ms = self._preview_segments[idx]
        inside = max(0, min(int(position_ms) - int(start_ms), int(end_ms) - int(start_ms)))
        return int(self._segment_offsets[idx] + inside)

    def _update_slider_for_position(self, position_ms: int) -> None:
        elapsed = max(0, min(self._elapsed_from_absolute_position(position_ms), self._total_preview_duration_ms))
        self._updating_slider = True
        try:
            self.position_slider.setValue(int(elapsed))
            self.current_time_label.setText(self._format_time(elapsed / 1000.0))
            self.scene_time_label.setText(self._format_time(self._total_preview_duration_ms / 1000.0))
        finally:
            self._updating_slider = False

    def _on_playback_state_changed(self, *_args) -> None:
        """Atualizar texto do botão único Play/Pause conforme o estado real do player."""
        self._update_play_button_state()

    def _update_play_button_state(self) -> None:
        """Manter um único botão Play/Pause visualmente consistente."""
        if not hasattr(self, "play_btn"):
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.play_btn.setText("⏸ Pausar")
            self.play_btn.setToolTip("Pausar e manter a posição atual")
        else:
            self.play_btn.setText("▶ Play")
            self.play_btn.setToolTip("Continuar de onde parou ou iniciar o trecho selecionado")

    def _on_player_position_changed(self, position_ms: int) -> None:
        if self._active_segment_start_ms is None or self._active_segment_end_ms is None:
            return
        if self._updating_slider:
            return
        self._update_slider_for_position(position_ms)

    def _on_seek_slider_moved(self, value: int) -> None:
        value = max(0, min(int(value), self._total_preview_duration_ms or 0))
        self.current_time_label.setText(self._format_time(value / 1000.0))

    def _on_seek_slider_released(self) -> None:
        target_elapsed = int(self.position_slider.value())
        self._updating_slider = False
        self._seek_preview_to_elapsed(target_elapsed)

    def _seek_preview_to_elapsed(self, elapsed_ms: int) -> None:
        if not self._preview_segments:
            return
        elapsed_ms = max(0, min(int(elapsed_ms), self._total_preview_duration_ms))
        target_index = 0
        for i, offset in enumerate(self._segment_offsets):
            start_ms, end_ms = self._preview_segments[i]
            segment_duration = max(int(end_ms) - int(start_ms), 1)
            if elapsed_ms < offset + segment_duration or i == len(self._segment_offsets) - 1:
                target_index = i
                break
        offset = self._segment_offsets[target_index]
        segment_start, segment_end = self._preview_segments[target_index]
        target_position = int(segment_start + max(0, elapsed_ms - offset))
        target_position = max(segment_start, min(target_position, segment_end - 100))
        was_playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self._activate_segment(target_index, autoplay=False)
        self.player.setPosition(target_position)
        self._update_slider_for_position(target_position)
        if was_playing:
            self.player.play()
            self.preview_timer.start()
        self._update_play_button_state()

    def _seek_relative(self, delta_ms: int) -> None:
        if not self._preview_segments:
            return
        current_elapsed = int(self.position_slider.value())
        self._seek_preview_to_elapsed(current_elapsed + int(delta_ms))

    def _selected_rows(self) -> list[int]:
        selection = self.table.selectionModel()
        if not selection:
            return []
        return sorted(index.row() for index in selection.selectedRows())

    def _current_preview_elapsed_ms(self) -> Optional[int]:
        """Retornar a posição atual relativa ao trecho/clipe em preview."""
        try:
            if self._preview_segments and self.position_slider.isEnabled():
                return int(self.position_slider.value())
        except Exception:
            pass
        return None

    def _reload_scenes_preserving_context(
        self,
        scene_id: object = None,
        elapsed_ms: Optional[int] = None,
        tab_index: Optional[int] = None,
        select_first: bool = False,
    ) -> None:
        """Recarregar a lista sem jogar o usuário de volta para a primeira cena.

        Usado depois de salvar descrição, criar corte ou criar clipe rascunho.
        Mantém a cena/clipe selecionado e, quando possível, restaura a posição
        da barra de preview para continuar do ponto em que o usuário estava.
        """
        if tab_index is None and hasattr(self, "detail_tabs"):
            tab_index = self.detail_tabs.currentIndex()

        self._load_scenes_for_selected_media(select_scene_id=scene_id, select_first=select_first)

        if tab_index is not None and hasattr(self, "detail_tabs"):
            self.detail_tabs.setCurrentIndex(tab_index)

        if elapsed_ms is not None and self._preview_segments:
            self._seek_preview_to_elapsed(int(elapsed_ms))

    def _select_scene_by_id(self, scene_id: object) -> None:
        if scene_id is None:
            return
        for row, scene in self._scenes_by_row.items():
            if str(scene.get("id")) == str(scene_id):
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 1))
                return

    def _segments_for_scene(self, scene: Dict[str, Any]) -> list[tuple[int, int]]:
        """Retornar os segmentos em milissegundos para uma cena ou clipe rascunho."""
        import json
        if int(scene.get("is_merged") or 0) and scene.get("segments_json"):
            try:
                raw_segments = json.loads(str(scene.get("segments_json") or "[]"))
                segments = []
                for segment in raw_segments:
                    start = float(segment.get("start_seconds") or 0.0)
                    end = float(segment.get("end_seconds") or start)
                    if end > start:
                        segments.append((int(start * 1000), int(end * 1000)))
                if segments:
                    return segments
            except Exception:
                logger.warning("Não foi possível ler segments_json do clipe juntado", exc_info=True)
        start_seconds, end_seconds = self._effective_scene_bounds(scene)
        if end_seconds <= start_seconds:
            return []
        return [(int(start_seconds * 1000), int(end_seconds * 1000))]

    def _clip_duration_seconds(self, scene: Dict[str, Any]) -> float:
        """Duração efetiva de cena/clipe, somando segmentos se for clipe juntado."""
        if int(scene.get("is_merged") or 0):
            segments = self._segments_for_scene(scene)
            if segments:
                return sum(max(end - start, 0) for start, end in segments) / 1000.0
        custom_duration = scene.get("custom_duration_seconds")
        if custom_duration is not None:
            return float(custom_duration or 0.0)
        start, end = self._effective_scene_bounds(scene)
        return max(end - start, 0.0)

    def _effective_scene_bounds(self, scene: Dict[str, Any]) -> tuple[float, float]:
        start = scene.get("custom_start_seconds")
        end = scene.get("custom_end_seconds")
        if start is None:
            start = scene.get("start_seconds") or 0.0
        if end is None:
            end = scene.get("end_seconds") or start
        start = float(start or 0.0)
        end = float(end or start)
        if end <= start:
            end = start + 0.25
        return start, end

    def _set_trim_start_to_current(self) -> None:
        if not self._selected_scene:
            return
        current = self.player.position() / 1000.0
        scene_start = float(self._selected_scene.get("start_seconds") or 0.0)
        scene_end = float(self._selected_scene.get("end_seconds") or current)
        current = max(scene_start, min(current, scene_end - 0.25))
        self.trim_start_spin.setValue(current)

    def _set_trim_end_to_current(self) -> None:
        if not self._selected_scene:
            return
        current = self.player.position() / 1000.0
        scene_start = float(self._selected_scene.get("start_seconds") or 0.0)
        scene_end = float(self._selected_scene.get("end_seconds") or current)
        current = max(scene_start + 0.25, min(current, scene_end))
        self.trim_end_spin.setValue(current)

    def _preview_trimmed_scene(self) -> None:
        if not self._selected_scene:
            return
        start = float(self.trim_start_spin.value())
        end = float(self.trim_end_spin.value())
        if end <= start:
            QMessageBox.warning(self, "Corte inválido", "O fim do corte precisa ser maior que o início.")
            return
        self._play_segments([(int(start * 1000), int(end * 1000))])
        self.status_label.setText(f"Prévia do corte: {self._format_time(start)} → {self._format_time(end)}")

    def _save_scene_trim(self) -> None:
        """Criar uma nova marcação de corte, sem alterar a cena original."""
        if not self._selected_scene or not self._selected_media:
            QMessageBox.information(self, "Corte", "Selecione uma cena para criar a marcação de corte.")
            return

        start = float(self.trim_start_spin.value())
        end = float(self.trim_end_spin.value())
        original_start = float(self._selected_scene.get("start_seconds") or 0.0)
        original_end = float(self._selected_scene.get("end_seconds") or original_start)
        if start < original_start or end > original_end or end <= start:
            QMessageBox.warning(
                self,
                "Corte inválido",
                "O corte precisa ficar dentro do intervalo original da cena e o fim precisa ser maior que o início.",
            )
            return

        source_name = self._selected_scene.get("display_name") or f"Cena {int(self._selected_scene.get('scene_number') or 0):03d}"
        default_name = f"{source_name} - corte"
        cut_name, ok_name = QInputDialog.getText(
            self,
            "Nome da marcação de corte",
            "Digite o nome para esta nova marcação de corte:\n\n"
            "O arquivo .mp4 ainda não será criado; isso salva apenas o intervalo para exportar depois.",
            text=default_name,
        )
        if not ok_name:
            return
        cut_name = (cut_name or default_name).strip()
        if not cut_name:
            cut_name = default_name

        reply = QMessageBox.question(
            self,
            "Criar marcação de corte?",
            f"Criar a marcação '{cut_name}' com o intervalo:\n\n"
            f"{self._format_time(start)} → {self._format_time(end)}\n"
            f"Duração: {self._format_time(end - start)}\n\n"
            "A cena original continuará intacta.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            new_scene = self.repository.create_cut_scene(
                media_id=self._selected_media.id,
                source_scene=self._selected_scene,
                start_seconds=start,
                end_seconds=end,
                display_name=cut_name,
            )
            self.status_label.setText(
                f"Marcação de corte criada: {new_scene.get('display_name') or cut_name} "
                f"({self._format_time(end - start)})."
            )
            self._reload_scenes_preserving_context(
                scene_id=new_scene.get("id"),
                elapsed_ms=0,
                tab_index=self.detail_tabs.currentIndex(),
                select_first=False,
            )
        except Exception as exc:
            logger.error("Erro ao criar marcação de corte: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro ao criar corte", str(exc))

    def _reset_scene_trim(self) -> None:
        if not self._selected_scene:
            return
        start = float(self._selected_scene.get("start_seconds") or 0.0)
        end = float(self._selected_scene.get("end_seconds") or start)
        self.trim_start_spin.setValue(start)
        self.trim_end_spin.setValue(end)
        try:
            scene_id = self._selected_scene["id"]
            elapsed_ms = self._current_preview_elapsed_ms()
            tab_index = self.detail_tabs.currentIndex()
            self.repository.update_scene_trim(scene_id, None, None)
            self.status_label.setText("Corte resetado para o intervalo original da cena.")
            self._reload_scenes_preserving_context(scene_id=scene_id, elapsed_ms=elapsed_ms, tab_index=tab_index)
        except Exception as exc:
            logger.error("Erro ao resetar corte da cena: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro ao resetar corte", str(exc))

    def _selected_scene_items_for_export(self) -> list[Dict[str, Any]]:
        """Retornar cenas selecionadas para exportação.

        Se nada estiver selecionado além do item atual, usa a cena ativa.
        """
        selected_rows = self._selected_rows()
        scenes = [self._scenes_by_row[row] for row in selected_rows if row in self._scenes_by_row]
        if not scenes and self._selected_scene:
            scenes = [self._selected_scene]
        return scenes

    def _default_export_name(self, scenes: list[Dict[str, Any]]) -> str:
        if len(scenes) == 1:
            scene = scenes[0]
            return str(scene.get("display_name") or f"Cena {int(scene.get('scene_number') or 0):03d}").strip()
        return f"clipe_compilado_{len(scenes)}_cenas"

    def _segments_for_export(self, scenes: list[Dict[str, Any]]) -> list[tuple[float, float]]:
        """Converter cenas selecionadas em segmentos de segundos para FFmpeg."""
        if not scenes:
            return []
        # Quando o item selecionado é um clipe rascunho/juntado, seus segmentos internos já definem a ordem.
        if len(scenes) == 1:
            segments_ms = self._segments_for_scene(scenes[0])
        else:
            scenes = sorted(scenes, key=lambda item: float(item.get("start_seconds") or 0.0))
            segments_ms = []
            for scene in scenes:
                segments_ms.extend(self._segments_for_scene(scene))
        return [(start / 1000.0, end / 1000.0) for start, end in segments_ms if end > start]

    def _export_selected_scenes(self) -> None:
        """Exportar cena, corte ou clipe rascunho selecionado para MP4.

        A exportação é precisa e cria o arquivo somente agora. Antes disso, tudo
        continua sendo apenas marcação no banco.
        """
        media = self._selected_media
        if not media:
            QMessageBox.information(self, "Exportar clipe", "Selecione um episódio primeiro.")
            return

        scenes = self._selected_scene_items_for_export()
        if not scenes:
            QMessageBox.information(self, "Exportar clipe", "Selecione uma cena, corte ou clipe rascunho.")
            return

        segments = self._segments_for_export(scenes)
        if not segments:
            QMessageBox.warning(self, "Exportar clipe", "Não há trechos válidos para exportar.")
            return

        source_path = Path(str(media.file_info.file_path))
        if not source_path.exists():
            QMessageBox.critical(self, "Arquivo não encontrado", f"O episódio original não foi encontrado:\n{source_path}")
            return

        default_name = self._default_export_name(scenes)
        library_folder = str(media.custom_metadata.get("library_folder") or "Sem pasta")
        safe_folder = self.clip_exporter.sanitize_component(library_folder, "Sem pasta")
        destination_dir = self.clip_exporter.export_root / safe_folder / "Clipes"
        destination_preview = f"{safe_folder} > Clipes"

        clip_name, ok_name = QInputDialog.getText(
            self,
            "Nome do clipe final",
            "Digite o nome do clipe que será exportado em MP4:\n\n"
            f"Destino na biblioteca de exportação:\n{destination_preview}\n\n"
            f"Caminho completo:\n{destination_dir}\n\n"
            "Se já existir um arquivo com esse nome, o TEDVHS Studio salvará como nome (1).mp4.",
            text=default_name,
        )
        if not ok_name:
            return
        clip_name = (clip_name or default_name).strip() or default_name

        total_duration = sum(end - start for start, end in segments)
        reply = QMessageBox.question(
            self,
            "Exportar clipe em MP4?",
            f"Exportar '{clip_name}' com corte preciso?\n\n"
            f"Trechos: {len(segments)}\n"
            f"Duração final aproximada: {self._format_time(total_duration)}\n\n"
            "O vídeo original não será alterado.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        first_scene = scenes[0]
        output_path = self.clip_exporter.build_output_path(media, first_scene, clip_name)
        folder = str(media.custom_metadata.get("library_folder") or "Sem pasta")
        source_season = str(media.custom_metadata.get("library_season") or "Sem temporada")
        clips_season = "Clipes"
        episode_name = str(media.file_info.file_name)
        source_scene_ids = [scene.get("id") for scene in scenes if scene.get("id") is not None]
        description_parts = [str(scene.get("description") or "").strip() for scene in scenes if str(scene.get("description") or "").strip()]
        tag_values: list[str] = []
        for scene in scenes:
            for raw_tag in str(scene.get("tags") or "").replace(";", ",").split(","):
                tag = raw_tag.strip()
                if tag and tag.lower() not in {existing.lower() for existing in tag_values}:
                    tag_values.append(tag)
        scene_type = str(first_scene.get("scene_type") or "Geral")
        metadata = {
            "clip_name": clip_name,
            "source_media_id": str(media.id),
            "source_file": str(source_path),
            "library_folder": folder,
            "library_season": clips_season,
            "source_library_season": source_season,
            "source_episode_name": episode_name,
            "episode_name": episode_name,
            "source_scene_ids": source_scene_ids,
            "scene_type": scene_type,
            "tags": tag_values,
            "description": "\n".join(description_parts),
            "export_note": "Exportado pelo TEDVHS Studio com corte preciso via FFmpeg.",
        }

        self.export_selected_btn.setEnabled(False)
        self.create_clip_btn.setEnabled(False)
        self.status_label.setText(f"Exportando clipe: {clip_name}... aguarde.")
        try:
            result = self.clip_exporter.export_scene(
                source_file=source_path,
                segments=segments,
                output_path=output_path,
                metadata=metadata,
            )
            record_id = self.repository.save_exported_clip(
                media_id=media.id,
                scene_id=first_scene.get("id") if len(scenes) == 1 else None,
                clip_name=clip_name,
                output_path=result["output_path"],
                metadata_path=result.get("metadata_path"),
                library_folder=folder,
                library_season=clips_season,
                episode_name=episode_name,
                duration_seconds=float(result.get("duration_seconds") or total_duration),
                segments_json=json.dumps(result.get("segments") or [], ensure_ascii=False),
                description="\n".join(description_parts),
                tags=", ".join(tag_values),
                scene_type=scene_type,
                export_mode=str(result.get("export_mode") or "precise_ffmpeg_reencode"),
            )
            self.status_label.setText(f"Clipe exportado: {result['output_path']}")
            message = (
                f"Clipe exportado com sucesso!\n\n"
                f"Arquivo:\n{result['output_path']}\n\n"
                f"Metadados:\n{result.get('metadata_path')}\n\n"
                f"Registro no banco: #{record_id}\n\n"
                "Deseja abrir a pasta do clipe?"
            )
            open_reply = QMessageBox.question(self, "Exportação concluída", message, QMessageBox.Yes | QMessageBox.No)
            if open_reply == QMessageBox.Yes:
                self._open_path_in_explorer(Path(result["output_path"]).parent)
        except Exception as exc:
            logger.error("Erro ao exportar clipe: %s", exc, exc_info=True)
            self.status_label.setText(f"Erro ao exportar clipe: {exc}")
            QMessageBox.critical(self, "Erro ao exportar clipe", str(exc))
        finally:
            self.export_selected_btn.setEnabled(True)
            self.create_clip_btn.setEnabled(True)

    def _open_path_in_explorer(self, path: Path) -> None:
        """Abrir pasta no explorador do sistema."""
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            logger.warning("Não foi possível abrir a pasta exportada: %s", exc)

    def hideEvent(self, event) -> None:
        """Pausar o preview ao sair da aba/tela de cenas."""
        try:
            if hasattr(self, "player"):
                self.player.pause()
            if hasattr(self, "preview_timer"):
                self.preview_timer.stop()
        except Exception:
            pass
        super().hideEvent(event)

    def _human_ai_status(self, status: object) -> str:
        value = str(status or "pending")
        mapping = {
            "auto_local": "gerada automaticamente por análise local de frames",
            "ollama_local": "gerada por IA local via Ollama (antigo/desativado)",
            "gemini_api": "gerada por Gemini API em modo seguro",
            "manual_edit": "editada manualmente",
            "pending": "pendente",
            "error": "erro",
        }
        return mapping.get(value, value)

    def _natural_key(self, value: object):
        import re
        text = str(value or "").lower()
        return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]

    def _format_time(self, seconds: object) -> str:
        seconds = float(seconds or 0.0)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

"""Editor de montagem em camadas do TEDVHS Studio.

Primeira versão estilo Vegas simplificado: o usuário envia um clipe da Biblioteca,
ativa/desativa camadas e exporta uma versão final.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QInputDialog,
    QApplication,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QTextEdit,
    QFileDialog,
    QVBoxLayout,
    QWidget,
)

from infrastructure.editing.layered_editor_service import (
    EditorExportOptions,
    LayeredEditorError,
    LayeredEditorService,
)

from infrastructure.ai.gemini_scene_ai_service import (
    DEFAULT_GEMINI_MODEL,
    GeminiSceneAIError,
    GeminiSceneAIService,
)
from infrastructure.ai.gemini_narration_service import (
    DEFAULT_NARRATION_MODEL,
    GeminiNarrationService,
)
from infrastructure.settings.api_settings import ApiSettingsStore
from infrastructure.subtitles.hybrid_subtitle_service import HybridSubtitleService
from infrastructure.tts.narration_audio_service import (
    DEFAULT_TTS_RATE,
    DEFAULT_TTS_VOICE,
    NarrationAudioService,
)
from presentation.views.clip_library_view import (
    _ClipSubtitleWorker,
    _ClipNarrationWorker,
    _ClipNarrationAudioWorker,
    _friendly_gemini_error,
)

logger = logging.getLogger(__name__)


class _EditorExportWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, service: LayeredEditorService, options: EditorExportOptions, metadata: Dict[str, Any]):
        super().__init__()
        self.service = service
        self.options = options
        self.metadata = dict(metadata or {})

    def run(self) -> None:
        try:
            self.progress.emit("Exportando vídeo final com camadas...")
            result = self.service.export_final_video(self.options)
            result["metadata"] = self.metadata
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))




class _EditorPreviewWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, service: LayeredEditorService, options: EditorExportOptions):
        super().__init__()
        self.service = service
        self.options = options

    def run(self) -> None:
        try:
            self.progress.emit("Renderizando prévia aplicada...")
            result = self.service.export_preview_video(self.options)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

class MontageEditorView(QWidget):
    """Aba de montagem/finalização em camadas."""

    final_video_exported = Signal(object)

    def __init__(self, repository: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.service = LayeredEditorService(timeout_seconds=1200)
        self.subtitle_service = HybridSubtitleService(timeout_seconds=180)
        self.narration_service = GeminiNarrationService(timeout_seconds=120)
        self.narration_audio_service = NarrationAudioService(timeout_seconds=180)
        self.ai_test_service = GeminiSceneAIService(timeout_seconds=60)
        self.api_settings = ApiSettingsStore()
        self._clip: Optional[Dict[str, Any]] = None
        self._export_thread: Optional[QThread] = None
        self._export_worker: Optional[_EditorExportWorker] = None
        self._preview_thread: Optional[QThread] = None
        self._preview_worker: Optional[_EditorPreviewWorker] = None
        self._subtitle_thread: Optional[QThread] = None
        self._subtitle_worker: Optional[_ClipSubtitleWorker] = None
        self._narration_thread: Optional[QThread] = None
        self._narration_worker: Optional[_ClipNarrationWorker] = None
        self._narration_audio_thread: Optional[QThread] = None
        self._narration_audio_worker: Optional[_ClipNarrationAudioWorker] = None
        self._preview_path: Optional[Path] = None
        self._preview_dirty: bool = True
        self._loading_clip: bool = False
        self._extra_caption_rows: List[Dict[str, Any]] = []
        self._watermark_logo_path: str = ""
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        title = QLabel("🎬 Montagem / Editor em Camadas")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        left_layout.addWidget(title)

        help_label = QLabel(
            "Envie um clipe da Biblioteca para cá. Ative as camadas desejadas, atualize a prévia aplicada "
            "e exporte o vídeo final. O editor é simplificado, focado em TikTok/Reels/Shorts."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #b8c0cc;")
        left_layout.addWidget(help_label)

        self.preview_layers_label = QLabel("Prévia: vídeo base. Clique em Atualizar prévia para ver as camadas aplicadas antes de exportar.")
        self.preview_layers_label.setWordWrap(True)
        self.preview_layers_label.setStyleSheet("color: #82d6ff; background: #101722; border: 1px solid #26313f; border-radius: 6px; padding: 6px;")
        left_layout.addWidget(self.preview_layers_label)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(260)
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setStyleSheet("background: #05070a; border: 1px solid #26313f; border-radius: 8px;")
        left_layout.addWidget(self.video_widget, 4)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

        self.narration_audio_output = QAudioOutput(self)
        self.narration_audio_player = QMediaPlayer(self)
        self.narration_audio_player.setAudioOutput(self.narration_audio_output)
        self.narration_audio_player.playbackStateChanged.connect(self._on_narration_audio_state_changed)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play_pause)
        controls.addWidget(self.play_btn)
        self.stop_btn = QPushButton("■ Parar")
        self.stop_btn.clicked.connect(self._stop_preview)
        controls.addWidget(self.stop_btn)
        self.current_time_label = QLabel("00:00")
        controls.addWidget(self.current_time_label)
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setRange(0, 1000)
        self.timeline_slider.sliderMoved.connect(self._seek_preview)
        controls.addWidget(self.timeline_slider, 1)
        self.total_time_label = QLabel("00:00")
        controls.addWidget(self.total_time_label)
        left_layout.addLayout(controls)

        timeline_group = QGroupBox("Linha do tempo simplificada")
        timeline_layout = QVBoxLayout(timeline_group)
        timeline_layout.setSpacing(6)
        self.track_video = self._make_track("Vídeo base", "#4666ff")
        self.track_anime_sub = self._make_track("Legenda anime", "#30c281")
        self.track_narrator_sub = self._make_track("Legenda narrador", "#ffb84d")
        self.track_narration_audio = self._make_track("Áudio narração", "#c267ff")
        self.track_extra_text = self._make_track("Texto extra", "#ff5c8a")
        self.track_watermark = self._make_track("Marca d'água", "#7bdff2")
        for row in (
            self.track_video,
            self.track_anime_sub,
            self.track_narrator_sub,
            self.track_narration_audio,
            self.track_extra_text,
            self.track_watermark,
        ):
            timeline_layout.addWidget(row)
        left_layout.addWidget(timeline_group, 1)

        self.status_label = QLabel("Nenhum clipe carregado. Vá na Biblioteca de Clipes e use Enviar para montagem.")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_label.setStyleSheet("color: #9fb2c7;")
        left_layout.addWidget(self.status_label)

        root.addWidget(left_panel, 3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(410)
        scroll.setFrameShape(QFrame.NoFrame)
        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(10)

        clip_group = QGroupBox("Clipe carregado")
        clip_layout = QVBoxLayout(clip_group)
        self.clip_info_label = QLabel("Nenhum clipe carregado.")
        self.clip_info_label.setWordWrap(True)
        self.clip_info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        clip_layout.addWidget(self.clip_info_label)
        self.clear_montage_btn = QPushButton("Limpar montagem")
        self.clear_montage_btn.clicked.connect(self._clear_montage_confirmed)
        clip_layout.addWidget(self.clear_montage_btn)
        right_layout.addWidget(clip_group)

        layer_group = QGroupBox("Camadas ativas / visual da timeline")
        layer_layout = QVBoxLayout(layer_group)
        layer_layout.setSpacing(8)

        self.base_video_check = QCheckBox("Vídeo base")
        self.base_video_check.setChecked(True)
        self.base_video_check.setEnabled(False)
        layer_layout.addWidget(self.base_video_check)

        original_volume_row = QHBoxLayout()
        original_volume_row.addWidget(QLabel("Volume original:"))
        self.original_volume_spin = QDoubleSpinBox()
        self.original_volume_spin.setRange(0.0, 2.0)
        self.original_volume_spin.setSingleStep(0.05)
        self.original_volume_spin.setValue(0.30)
        self.original_volume_spin.setSuffix("x")
        self.original_volume_spin.valueChanged.connect(self._sync_preview_audio)
        self.original_volume_spin.valueChanged.connect(lambda _=None: self._update_tracks())
        original_volume_row.addWidget(self.original_volume_spin, 1)
        layer_layout.addLayout(original_volume_row)

        self.anime_subtitle_check = QCheckBox("Legenda do anime PT-BR")
        self.anime_subtitle_check.setChecked(True)
        self.anime_subtitle_check.toggled.connect(self._update_tracks)
        self.anime_subtitle_status = QLabel("Legenda do anime: aguardando clipe.")
        self.anime_subtitle_status.setWordWrap(True)
        self.anime_subtitle_status.setStyleSheet("color: #a7b2c2;")
        anime_position = QHBoxLayout()
        anime_position.addWidget(QLabel("Posição anime:"))
        self.anime_subtitle_position_combo = QComboBox()
        self.anime_subtitle_position_combo.addItems(["inferior", "centro-baixo", "superior"])
        self.anime_subtitle_position_combo.currentTextChanged.connect(lambda _=None: self._update_tracks())
        anime_position.addWidget(self.anime_subtitle_position_combo, 1)

        self.narrator_subtitle_check = QCheckBox("Legenda do narrador")
        self.narrator_subtitle_check.setChecked(True)
        self.narrator_subtitle_check.toggled.connect(self._update_tracks)
        narrator_position = QHBoxLayout()
        narrator_position.addWidget(QLabel("Posição narrador:"))
        self.narrator_subtitle_position_combo = QComboBox()
        self.narrator_subtitle_position_combo.addItems(["superior", "centro", "inferior"])
        self.narrator_subtitle_position_combo.currentTextChanged.connect(lambda _=None: self._update_tracks())
        narrator_position.addWidget(self.narrator_subtitle_position_combo, 1)
        self.dynamic_narrator_subtitle_check = QCheckBox("Narração dinâmica: destacar a palavra falada")
        self.dynamic_narrator_subtitle_check.setChecked(True)
        self.dynamic_narrator_subtitle_check.setToolTip("Liga/desliga a legenda dinâmica da narração. Ligado: exige sync do áudio e destaca a palavra falada. Desligado: usa legenda estável por frases.")
        self.dynamic_narrator_subtitle_check.toggled.connect(self._update_tracks)

        self.narration_audio_check = QCheckBox("Áudio da narração")
        self.narration_audio_check.setChecked(True)
        self.narration_audio_check.toggled.connect(self._update_tracks)
        self.narration_audio_status = QLabel("Áudio da narração: aguardando clipe.")
        self.narration_audio_status.setWordWrap(True)
        self.narration_audio_status.setStyleSheet("color: #a7b2c2;")
        narration_volume_row = QHBoxLayout()
        narration_volume_row.addWidget(QLabel("Volume narração:"))
        self.narration_volume_spin = QDoubleSpinBox()
        self.narration_volume_spin.setRange(0.0, 2.0)
        self.narration_volume_spin.setSingleStep(0.05)
        self.narration_volume_spin.setValue(1.00)
        self.narration_volume_spin.setSuffix("x")
        self.narration_volume_spin.valueChanged.connect(lambda _=None: self._update_tracks())
        narration_volume_row.addWidget(self.narration_volume_spin, 1)

        self.extra_text_check = QCheckBox("Legendas extras na tela")
        self.extra_text_check.setChecked(False)
        self.extra_text_check.toggled.connect(self._update_tracks)
        layer_layout.addWidget(self.extra_text_check)
        self.extra_text_status = QLabel("Nenhuma legenda extra adicionada.")
        self.extra_text_status.setWordWrap(True)
        self.extra_text_status.setStyleSheet("color: #a7b2c2;")
        layer_layout.addWidget(self.extra_text_status)

        self.watermark_check = QCheckBox("Marca d'água TEDVHS")
        self.watermark_check.setChecked(True)
        self.watermark_check.toggled.connect(self._update_tracks)
        layer_layout.addWidget(self.watermark_check)
        self.watermark_text_edit = QLineEdit("@tedvhs")
        self.watermark_text_edit.setPlaceholderText("Ex.: @tedvhs. Deixe vazio se quiser usar só a logo.")
        self.watermark_text_edit.textChanged.connect(lambda _=None: self._update_tracks())
        layer_layout.addWidget(self.watermark_text_edit)
        logo_row = QHBoxLayout()
        self.watermark_logo_label = QLabel("Logo: nenhuma")
        self.watermark_logo_label.setWordWrap(True)
        self.watermark_logo_label.setStyleSheet("color: #a7b2c2;")
        logo_row.addWidget(self.watermark_logo_label, 1)
        self.select_watermark_logo_btn = QPushButton("Selecionar logo")
        self.select_watermark_logo_btn.clicked.connect(self._select_watermark_logo)
        logo_row.addWidget(self.select_watermark_logo_btn)
        self.clear_watermark_logo_btn = QPushButton("Limpar logo")
        self.clear_watermark_logo_btn.clicked.connect(self._clear_watermark_logo)
        logo_row.addWidget(self.clear_watermark_logo_btn)
        layer_layout.addLayout(logo_row)
        logo_size_row = QHBoxLayout()
        logo_size_row.addWidget(QLabel("Tamanho logo:"))
        self.watermark_logo_size_spin = QDoubleSpinBox()
        self.watermark_logo_size_spin.setRange(3.0, 40.0)
        self.watermark_logo_size_spin.setSingleStep(1.0)
        self.watermark_logo_size_spin.setValue(14.0)
        self.watermark_logo_size_spin.setSuffix("%")
        self.watermark_logo_size_spin.valueChanged.connect(lambda _=None: self._update_tracks())
        logo_size_row.addWidget(self.watermark_logo_size_spin, 1)
        logo_size_row.addWidget(QLabel("Opacidade:"))
        self.watermark_logo_opacity_spin = QDoubleSpinBox()
        self.watermark_logo_opacity_spin.setRange(0.10, 1.0)
        self.watermark_logo_opacity_spin.setSingleStep(0.05)
        self.watermark_logo_opacity_spin.setValue(0.78)
        self.watermark_logo_opacity_spin.valueChanged.connect(lambda _=None: self._update_tracks())
        logo_size_row.addWidget(self.watermark_logo_opacity_spin, 1)
        layer_layout.addLayout(logo_size_row)
        watermark_position = QHBoxLayout()
        watermark_position.addWidget(QLabel("Posição marca:"))
        self.watermark_position_combo = QComboBox()
        self.watermark_position_combo.addItems(["superior direito", "superior esquerdo", "inferior direito", "inferior esquerdo"])
        self.watermark_position_combo.currentTextChanged.connect(lambda _=None: self._update_tracks())
        watermark_position.addWidget(self.watermark_position_combo, 1)
        layer_layout.addLayout(watermark_position)

        right_layout.addWidget(layer_group)

        extra_group = QGroupBox("Legendas extras cronometradas")
        extra_layout = QVBoxLayout(extra_group)
        extra_help = QLabel(
            "Adicione textos que aparecem em trechos específicos do vídeo. Ex.: ‘assista até o final’ de 00:00:00 até 00:00:15."
        )
        extra_help.setWordWrap(True)
        extra_help.setStyleSheet("color: #a7b2c2;")
        extra_layout.addWidget(extra_help)
        self.extra_captions_container = QWidget()
        self.extra_captions_layout = QVBoxLayout(self.extra_captions_container)
        self.extra_captions_layout.setContentsMargins(0, 0, 0, 0)
        self.extra_captions_layout.setSpacing(8)
        extra_layout.addWidget(self.extra_captions_container)
        extra_actions = QHBoxLayout()
        self.add_extra_caption_btn = QPushButton("Adicionar legenda extra")
        self.add_extra_caption_btn.clicked.connect(self._add_extra_caption_row)
        extra_actions.addWidget(self.add_extra_caption_btn, 1)
        self.clear_extra_captions_btn = QPushButton("Limpar extras")
        self.clear_extra_captions_btn.clicked.connect(self._clear_extra_caption_rows)
        extra_actions.addWidget(self.clear_extra_captions_btn, 1)
        extra_layout.addLayout(extra_actions)
        right_layout.addWidget(extra_group)

        api_group = QGroupBox("IA e complementos da montagem")
        api_layout = QVBoxLayout(api_group)
        api_help = QLabel(
            "Complementos do vídeo base ficam aqui: legenda PT-BR, roteiro, narração, legenda do narrador, post e hashtags. "
            "A Biblioteca agora fica focada em organizar/enviar clipes."
        )
        api_help.setWordWrap(True)
        api_help.setStyleSheet("color: #a7b2c2;")
        api_layout.addWidget(api_help)

        api_row = QHBoxLayout()
        api_row.addWidget(QLabel("API Key:"))
        saved_key = self.api_settings.get_gemini_api_key() if hasattr(self, "api_settings") else ""
        self.gemini_api_key_edit = QLineEdit(saved_key)
        self.gemini_api_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_api_key_edit.setPlaceholderText("Cole sua API Key do Gemini")
        api_row.addWidget(self.gemini_api_key_edit, 1)
        api_layout.addLayout(api_row)

        api_save_row = QHBoxLayout()
        self.save_api_key_checkbox = QCheckBox("Salvar chave neste PC")
        self.save_api_key_checkbox.setChecked(bool(saved_key))
        self.save_api_key_checkbox.setToolTip("Salva em data/settings/api_settings.json. É local, mas não criptografado.")
        api_save_row.addWidget(self.save_api_key_checkbox)
        self.save_api_key_btn = QPushButton("Salvar chave")
        self.save_api_key_btn.clicked.connect(self._save_gemini_settings_from_fields)
        api_save_row.addWidget(self.save_api_key_btn)
        self.clear_api_key_btn = QPushButton("Apagar chave")
        self.clear_api_key_btn.clicked.connect(self._clear_saved_gemini_api_key)
        api_save_row.addWidget(self.clear_api_key_btn)
        api_layout.addLayout(api_save_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Modelo:"))
        saved_model = self.api_settings.get_gemini_model(DEFAULT_GEMINI_MODEL) if hasattr(self, "api_settings") else DEFAULT_GEMINI_MODEL
        self.gemini_model_edit = QLineEdit(saved_model or DEFAULT_GEMINI_MODEL)
        self.gemini_model_edit.setPlaceholderText(DEFAULT_GEMINI_MODEL)
        model_row.addWidget(self.gemini_model_edit, 1)
        self.test_gemini_btn = QPushButton("Testar Gemini")
        self.test_gemini_btn.clicked.connect(self._test_gemini_connection)
        model_row.addWidget(self.test_gemini_btn)
        api_layout.addLayout(model_row)
        right_layout.addWidget(api_group)

        subtitle_group = QGroupBox("Legenda do anime PT-BR")
        subtitle_layout = QVBoxLayout(subtitle_group)
        subtitle_layout.addWidget(self.anime_subtitle_check)
        subtitle_layout.addWidget(self.anime_subtitle_status)
        subtitle_layout.addLayout(anime_position)
        self.subtitle_status_label = QLabel("Envie um clipe para a montagem para ver o status da legenda.")
        self.subtitle_status_label.setWordWrap(True)
        self.subtitle_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        subtitle_layout.addWidget(self.subtitle_status_label)
        subtitle_actions = QHBoxLayout()
        self.generate_subtitle_btn = QPushButton("Gerar legenda PT-BR")
        self.generate_subtitle_btn.clicked.connect(self._on_generate_current_subtitle)
        subtitle_actions.addWidget(self.generate_subtitle_btn, 1)
        self.open_subtitle_btn = QPushButton("Abrir legenda")
        self.open_subtitle_btn.clicked.connect(self._open_current_subtitle)
        subtitle_actions.addWidget(self.open_subtitle_btn, 1)
        subtitle_layout.addLayout(subtitle_actions)
        right_layout.addWidget(subtitle_group)

        narrator_group = QGroupBox("Roteiro, narração, legenda da narração e post")
        narrator_layout = QVBoxLayout(narrator_group)
        narration_help = QLabel(
            "Aqui você prepara tudo que complementa o vídeo base: roteiro, blocos de fala, áudio da narração, legenda do narrador e texto do post."
        )
        narration_help.setWordWrap(True)
        narration_help.setStyleSheet("color: #a7b2c2;")
        narrator_layout.addWidget(narration_help)

        self.narration_status_label = QLabel("Sem roteiro carregado.")
        self.narration_status_label.setWordWrap(True)
        self.narration_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        narrator_layout.addWidget(self.narration_status_label)

        narration_options = QHBoxLayout()
        narration_options.addWidget(QLabel("Estilo:"))
        self.narration_style_combo = QComboBox()
        self.narration_style_combo.addItems([
            "Empolgado", "Misterioso", "Informativo", "Engraçado leve",
            "Dramático", "Review/Indicação", "TEDVHS direto"
        ])
        narration_options.addWidget(self.narration_style_combo, 1)
        narration_options.addWidget(QLabel("Tamanho:"))
        self.narration_length_combo = QComboBox()
        self.narration_length_combo.addItems([
            "Acompanhar clipe inteiro",
            "Curto 20-30s",
            "Médio 45-60s",
            "Longo 75-90s",
        ])
        narration_options.addWidget(self.narration_length_combo, 1)
        narrator_layout.addLayout(narration_options)

        retention_row = QHBoxLayout()
        self.narration_retention_check = QCheckBox("Modo For You: gancho forte + final engajante")
        self.narration_retention_check.setChecked(True)
        self.narration_retention_check.setToolTip(
            "Pede para a IA criar uma narração com abertura forte para parar o feed e fechamento que incentive comentar, salvar ou seguir."
        )
        self.narration_retention_check.stateChanged.connect(lambda _=None: self._mark_preview_dirty("modo For You da narração alterado"))
        retention_row.addWidget(self.narration_retention_check, 1)
        self.narration_retention_goal_edit = QLineEdit()
        self.narration_retention_goal_edit.setPlaceholderText("Pedido extra opcional. Ex.: prender nos 3 primeiros segundos e fechar com CTA natural")
        self.narration_retention_goal_edit.textChanged.connect(lambda _=None: self._mark_preview_dirty("direção de engajamento alterada"))
        retention_row.addWidget(self.narration_retention_goal_edit, 2)
        narrator_layout.addLayout(retention_row)

        narrator_layout.addWidget(QLabel("Roteiro para narrador:"))
        self.narrator_script_edit = QTextEdit()
        self.narrator_script_edit.setPlaceholderText("O roteiro do narrador será carregado do clipe. Você pode editar aqui antes de exportar.")
        self.narrator_script_edit.setMinimumHeight(150)
        self.narrator_script_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.narrator_script_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.narrator_script_edit.textChanged.connect(lambda: self._mark_preview_dirty("roteiro do narrador alterado"))
        narrator_layout.addWidget(self.narrator_script_edit)

        blocks_group = QGroupBox("Blocos de fala")
        blocks_layout = QVBoxLayout(blocks_group)
        self.narration_blocks_edit = QTextEdit()
        self.narration_blocks_edit.setPlaceholderText(
            "Uma fala por linha. Ex.:\nEsse anime começa de um jeito absurdo...\nE é aqui que tudo muda..."
        )
        self.narration_blocks_edit.setMinimumHeight(110)
        self.narration_blocks_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.narration_blocks_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.narration_blocks_edit.textChanged.connect(lambda: self._mark_preview_dirty("blocos de fala alterados"))
        blocks_layout.addWidget(self.narration_blocks_edit)
        blocks_actions = QHBoxLayout()
        self.split_narration_blocks_btn = QPushButton("Dividir roteiro")
        self.split_narration_blocks_btn.clicked.connect(self._split_narration_script_into_blocks)
        blocks_actions.addWidget(self.split_narration_blocks_btn, 1)
        self.add_narration_block_btn = QPushButton("Adicionar fala")
        self.add_narration_block_btn.clicked.connect(self._add_narration_block)
        blocks_actions.addWidget(self.add_narration_block_btn, 1)
        self.apply_narration_blocks_btn = QPushButton("Aplicar no roteiro")
        self.apply_narration_blocks_btn.clicked.connect(self._apply_narration_blocks_to_script)
        blocks_actions.addWidget(self.apply_narration_blocks_btn, 1)
        blocks_layout.addLayout(blocks_actions)
        narrator_layout.addWidget(blocks_group)

        narrator_layout.addWidget(QLabel("Título sugerido:"))
        self.tiktok_title_edit = QLineEdit()
        self.tiktok_title_edit.setPlaceholderText("Título curto para TikTok/Reels/Shorts")
        narrator_layout.addWidget(self.tiktok_title_edit)
        narrator_layout.addWidget(QLabel("Texto para publicação:"))
        self.tiktok_caption_edit = QTextEdit()
        self.tiktok_caption_edit.setPlaceholderText("Texto da publicação para copiar e colar...")
        self.tiktok_caption_edit.setMinimumHeight(110)
        self.tiktok_caption_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.tiktok_caption_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        narrator_layout.addWidget(self.tiktok_caption_edit)
        narrator_layout.addWidget(QLabel("Hashtags:"))
        self.narration_hashtags_edit = QLineEdit()
        self.narration_hashtags_edit.setPlaceholderText("Até 5 hashtags, ex.: #anime #otaku #isekai #tedvhs #animes")
        narrator_layout.addWidget(self.narration_hashtags_edit)

        narration_actions = QHBoxLayout()
        self.generate_narration_btn = QPushButton("Gerar roteiro com IA")
        self.generate_narration_btn.clicked.connect(self._on_generate_current_narration)
        narration_actions.addWidget(self.generate_narration_btn, 1)
        self.save_narration_btn = QPushButton("Salvar roteiro/post")
        self.save_narration_btn.clicked.connect(self._save_narration_metadata)
        narration_actions.addWidget(self.save_narration_btn, 1)
        narrator_layout.addLayout(narration_actions)

        narration_copy_actions = QHBoxLayout()
        self.copy_post_btn = QPushButton("Copiar post + hashtags")
        self.copy_post_btn.clicked.connect(self._copy_tiktok_post_package)
        narration_copy_actions.addWidget(self.copy_post_btn, 1)
        self.copy_narration_btn = QPushButton("Copiar pacote completo")
        self.copy_narration_btn.clicked.connect(self._copy_narration_package)
        narration_copy_actions.addWidget(self.copy_narration_btn, 1)
        narrator_layout.addLayout(narration_copy_actions)

        audio_group = QGroupBox("Narração")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.addWidget(self.narration_audio_check)
        audio_layout.addWidget(self.narration_audio_status)
        audio_layout.addLayout(narration_volume_row)
        self.narration_audio_status_label = QLabel("Status: sem áudio de narração para esta montagem.")
        self.narration_audio_status_label.setWordWrap(True)
        self.narration_audio_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        audio_layout.addWidget(self.narration_audio_status_label)
        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("Voz:"))
        self.narration_voice_combo = QComboBox()
        self.narration_voice_combo.addItems(["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural"])
        voice_row.addWidget(self.narration_voice_combo, 1)
        voice_row.addWidget(QLabel("Velocidade:"))
        self.narration_rate_combo = QComboBox()
        self.narration_rate_combo.addItems(["+0%", "+5%", "+10%", "-5%", "-10%"])
        voice_row.addWidget(self.narration_rate_combo, 1)
        audio_layout.addLayout(voice_row)
        audio_actions = QHBoxLayout()
        self.generate_narration_audio_btn = QPushButton("Gerar áudio da narração")
        self.generate_narration_audio_btn.clicked.connect(self._on_generate_narration_audio)
        audio_actions.addWidget(self.generate_narration_audio_btn, 1)
        self.play_narration_audio_btn = QPushButton("Ouvir narração")
        self.play_narration_audio_btn.clicked.connect(self._play_narration_audio)
        audio_actions.addWidget(self.play_narration_audio_btn, 1)
        self.open_narration_audio_btn = QPushButton("Abrir áudio")
        self.open_narration_audio_btn.clicked.connect(self._open_narration_audio)
        audio_actions.addWidget(self.open_narration_audio_btn, 1)
        audio_layout.addLayout(audio_actions)
        narrator_layout.addWidget(audio_group)

        narrator_subtitle_group = QGroupBox("Legenda da narração")
        narrator_subtitle_layout = QVBoxLayout(narrator_subtitle_group)
        narrator_subtitle_layout.addWidget(self.narrator_subtitle_check)
        narrator_subtitle_layout.addLayout(narrator_position)
        narrator_subtitle_layout.addWidget(self.dynamic_narrator_subtitle_check)
        dynamic_help = QLabel("Com Narração dinâmica ligada, a legenda da narração fica em um único bloco; só a palavra atual deve ficar destacada. Não mexe na legenda do anime.")
        dynamic_help.setWordWrap(True)
        dynamic_help.setStyleSheet("color: #a7b2c2;")
        narrator_subtitle_layout.addWidget(dynamic_help)
        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Legenda narrador cobre:"))
        self.narrator_subtitle_duration_combo = QComboBox()
        self.narrator_subtitle_duration_combo.addItems(["seguir áudio da narração", "vídeo inteiro", "duração da narração"])
        self.narrator_subtitle_duration_combo.setToolTip("Isto controla a duração visual da legenda do narrador. Para destaque palavra por palavra, o ideal é seguir o áudio da narração.")
        self.narrator_subtitle_duration_combo.currentTextChanged.connect(lambda _=None: self._update_tracks())
        duration_row.addWidget(self.narrator_subtitle_duration_combo, 1)
        narrator_subtitle_layout.addLayout(duration_row)
        gen_row = QHBoxLayout()
        self.generate_narrator_sub_btn = QPushButton("Gerar legenda da narração")
        self.generate_narrator_sub_btn.clicked.connect(self._generate_narrator_subtitle_only)
        gen_row.addWidget(self.generate_narrator_sub_btn, 1)
        narrator_subtitle_layout.addLayout(gen_row)
        self.narrator_subtitle_status = QLabel("Legenda da narração será gerada automaticamente na prévia/exportação.")
        self.narrator_subtitle_status.setWordWrap(True)
        self.narrator_subtitle_status.setStyleSheet("color: #a7b2c2;")
        narrator_subtitle_layout.addWidget(self.narrator_subtitle_status)
        narrator_layout.addWidget(narrator_subtitle_group)
        right_layout.addWidget(narrator_group)

        export_group = QGroupBox("Exportação final")
        export_layout = QVBoxLayout(export_group)
        self.output_name_edit = QLineEdit()
        self.output_name_edit.setPlaceholderText("Nome do arquivo final, ex.: anime_parte_1_final")
        export_layout.addWidget(self.output_name_edit)
        self.render_preview_btn = QPushButton("Atualizar prévia aplicada")
        self.render_preview_btn.clicked.connect(self._render_applied_preview)
        export_layout.addWidget(self.render_preview_btn)
        self.export_final_btn = QPushButton("Exportar vídeo final")
        self.export_final_btn.clicked.connect(self._export_final_video)
        export_layout.addWidget(self.export_final_btn)
        self.open_output_folder_btn = QPushButton("Abrir pasta do clipe")
        self.open_output_folder_btn.clicked.connect(self._open_clip_folder)
        export_layout.addWidget(self.open_output_folder_btn)
        right_layout.addWidget(export_group)

        right_layout.addStretch(1)
        scroll.setWidget(right_content)
        root.addWidget(scroll, 2)
        self._update_tracks()

    def _make_track(self, name: str, color: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(name)
        label.setFixedWidth(130)
        label.setStyleSheet("color: #d9e2ef;")
        layout.addWidget(label)
        bar = QLabel("  ativo")
        bar.setMinimumHeight(20)
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bar.setStyleSheet(f"background: {color}; border-radius: 5px; border: 1px solid rgba(255,255,255,0.25);")
        layout.addWidget(bar, 1)
        row._bar = bar  # type: ignore[attr-defined]
        return row

    # ------------------------------------------------------------------
    # Entrada de clipes / estado
    # ------------------------------------------------------------------
    def load_clip(self, clip: Dict[str, Any]) -> None:
        """Carregar clipe vindo da Biblioteca de Clipes."""
        incoming = dict(clip or {})
        incoming_path = Path(str(incoming.get("output_path") or ""))
        if self._clip:
            current_path = Path(str(self._clip.get("output_path") or ""))
            if current_path and incoming_path and str(current_path.resolve()).lower() != str(incoming_path.resolve()).lower():
                answer = QMessageBox.question(
                    self,
                    "Substituir montagem",
                    "Já existe uma montagem aberta. Deseja substituir o vídeo base atual?\n\n"
                    "Os arquivos originais não serão apagados.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if answer != QMessageBox.Yes:
                    return
        self._loading_clip = True
        self._clip = incoming
        output_path = Path(str(self._clip.get("output_path") or ""))
        self._stop_preview()
        self._preview_path = None
        self._preview_dirty = True
        if output_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(output_path)))
            self.player.setVideoOutput(self.video_widget)
            self.player.setPosition(0)
        else:
            self.player.setSource(QUrl())

        clip_name = str(self._clip.get("clip_name") or output_path.stem or "Clipe")
        duration = self._clip_duration(self._clip)
        self.clip_info_label.setText(
            f"Nome: {clip_name}\n"
            f"Anime/Pasta: {self._clip.get('library_folder') or 'Sem pasta'}\n"
            f"Duração: {self._format_time(duration)}\n"
            f"Tipo: {self._clip.get('scene_type') or 'Geral'}\n"
            f"Arquivo: {output_path}"
        )
        self.output_name_edit.setText(self._safe_output_stem(f"{clip_name} FINAL TEDVHS"))
        self.narrator_script_edit.setPlainText(self._narration_script_for_clip(self._clip))
        anime_sub = self._find_anime_subtitle_path(self._clip)
        narration_audio = self._find_narration_audio_path(self._clip)
        self.anime_subtitle_check.setChecked(bool(anime_sub))
        self.narration_audio_check.setChecked(bool(narration_audio))
        self.anime_subtitle_status.setText(
            f"Legenda do anime: {anime_sub}" if anime_sub else "Legenda do anime: nenhuma .ass PT-BR encontrada. Gere a legenda aqui na Montagem ou mantenha esta camada desligada."
        )
        self.narration_audio_status.setText(
            f"Áudio da narração: {narration_audio}" if narration_audio else "Áudio da narração: não encontrado. Gere áudio aqui na Montagem ou mantenha esta camada desligada."
        )
        self._load_complement_fields(self._clip)
        self._refresh_complement_statuses(self._clip)
        self.status_label.setText("Clipe carregado na montagem. Prepare os complementos, ajuste as camadas e clique em Atualizar prévia aplicada.")
        self._sync_preview_audio()
        self._loading_clip = False
        self._update_tracks()
        self._mark_preview_dirty("novo clipe carregado")

    def pause_players(self) -> None:
        try:
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.player.pause()
                self.play_btn.setText("▶ Play")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    def _render_applied_preview(self) -> None:
        clip = self._clip
        if not clip:
            QMessageBox.information(self, "Prévia", "Envie um clipe para montagem primeiro.")
            return
        if self._preview_thread is not None:
            QMessageBox.information(self, "Prévia em andamento", "Aguarde a prévia atual terminar.")
            return
        base_video = Path(str(clip.get("output_path") or ""))
        if not base_video.exists():
            QMessageBox.warning(self, "Arquivo não encontrado", f"Vídeo base não encontrado:\n{base_video}")
            return
        try:
            self._stop_preview()
            # Solta o arquivo anterior no Windows antes de re-renderizar.
            self.player.setSource(QUrl())
            safe_stem = self._safe_output_stem(self.output_name_edit.text() or base_video.stem)
            preview_dir = base_video.parent / "_tedvhs_preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_path = preview_dir / f"{safe_stem}.preview.{int(time.time())}.mp4"
            options = self._build_editor_options(clip, preview_path, safe_stem=f"{safe_stem}.preview")
            self._start_preview_worker(options)
        except Exception as exc:
            QMessageBox.warning(self, "Prévia aplicada", str(exc))

    def _start_preview_worker(self, options: EditorExportOptions) -> None:
        self.render_preview_btn.setEnabled(False)
        self.status_label.setText("Renderizando prévia aplicada com camadas...")
        thread = QThread(self)
        worker = _EditorPreviewWorker(self.service, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(self._on_preview_finished)
        worker.failed.connect(self._on_preview_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_preview_worker)
        self._preview_thread = thread
        self._preview_worker = worker
        thread.start()

    def _on_preview_finished(self, result: Dict[str, Any]) -> None:
        preview_path = Path(str(result.get("output_path") or ""))
        self._preview_path = preview_path
        self._preview_dirty = False
        if preview_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(preview_path)))
            self.player.setVideoOutput(self.video_widget)
            self.player.setPosition(0)
            self.status_label.setText(f"Prévia aplicada pronta: {preview_path}")
            self.preview_layers_label.setText("Prévia aplicada atualizada. O player agora mostra as camadas exatamente como serão exportadas, em qualidade leve.")
            self.play_btn.setText("▶ Play")
        self.render_preview_btn.setEnabled(True)

    def _on_preview_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Prévia aplicada", message)
        self.status_label.setText(f"Falha ao gerar prévia: {message}")
        self.render_preview_btn.setEnabled(True)
        self._set_base_video_as_preview_source()

    def _clear_preview_worker(self) -> None:
        self._preview_thread = None
        self._preview_worker = None
        if hasattr(self, "render_preview_btn"):
            self.render_preview_btn.setEnabled(True)

    def _set_base_video_as_preview_source(self) -> None:
        clip = self._clip
        if not clip:
            return
        base_video = Path(str(clip.get("output_path") or ""))
        if base_video.exists():
            self.player.setSource(QUrl.fromLocalFile(str(base_video)))
            self.player.setVideoOutput(self.video_widget)
            self.player.setPosition(0)

    def _toggle_play_pause(self) -> None:
        if not self._clip:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText("▶ Play")
            self.status_label.setText("Preview pausado.")
        else:
            self.player.play()
            self.play_btn.setText("⏸ Pause")
            self.status_label.setText("Reproduzindo preview...")

    def _stop_preview(self) -> None:
        try:
            self.player.pause()
            self.player.setPosition(0)
            self.play_btn.setText("▶ Play")
        except Exception:
            pass

    def _seek_preview(self, value: int) -> None:
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(int(duration * (value / 1000.0)))

    def _on_position_changed(self, position: int) -> None:
        duration = self.player.duration()
        if duration > 0 and not self.timeline_slider.isSliderDown():
            self.timeline_slider.setValue(int((position / duration) * 1000))
        self.current_time_label.setText(self._format_time(position / 1000.0))

    def _on_duration_changed(self, duration: int) -> None:
        self.total_time_label.setText(self._format_time(duration / 1000.0))

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_btn.setText("⏸ Pause" if state == QMediaPlayer.PlayingState else "▶ Play")

    # ------------------------------------------------------------------
    # Legendas extras / marca d'água
    # ------------------------------------------------------------------
    def _add_extra_caption_row(
        self,
        text: str = "",
        start_time: str = "",
        end_time: str = "",
        position: str = "centro",
    ) -> None:
        duration = self._clip_duration(self._clip or {}) if self._clip else 0.0
        if not start_time:
            if self._extra_caption_rows:
                last_end = self._time_to_seconds(self._extra_caption_rows[-1]["end_edit"].text())
                start_seconds = last_end
            else:
                start_seconds = 0.0
            start_time = self._format_timecode(start_seconds)
        else:
            start_seconds = self._time_to_seconds(start_time)
        if not end_time:
            end_seconds = start_seconds + 15.0
            if duration > 0:
                end_seconds = min(duration, end_seconds)
            end_time = self._format_timecode(end_seconds)

        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("QFrame { border: 1px solid #303b4d; border-radius: 6px; padding: 4px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        header = QHBoxLayout()
        title = QLabel("Legenda extra")
        title.setStyleSheet("font-weight: 700; color: #dce7f5;")
        header.addWidget(title, 1)
        remove_btn = QPushButton("Remover")
        header.addWidget(remove_btn)
        layout.addLayout(header)

        text_edit = QLineEdit(str(text or ""))
        text_edit.setPlaceholderText("Ex.: assista até o final")
        layout.addWidget(text_edit)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Início:"))
        start_edit = QLineEdit(str(start_time or "00:00:00"))
        start_edit.setPlaceholderText("00:00:00")
        time_row.addWidget(start_edit, 1)
        time_row.addWidget(QLabel("Fim:"))
        end_edit = QLineEdit(str(end_time or "00:00:15"))
        end_edit.setPlaceholderText("00:00:15")
        time_row.addWidget(end_edit, 1)
        layout.addLayout(time_row)

        position_row = QHBoxLayout()
        position_row.addWidget(QLabel("Posição:"))
        position_combo = QComboBox()
        position_combo.addItems(["centro", "superior", "inferior"])
        self._set_combo_text(position_combo, str(position or "centro"))
        position_row.addWidget(position_combo, 1)
        layout.addLayout(position_row)

        row = {
            "frame": frame,
            "title": title,
            "text_edit": text_edit,
            "start_edit": start_edit,
            "end_edit": end_edit,
            "position_combo": position_combo,
            "remove_btn": remove_btn,
        }
        remove_btn.clicked.connect(lambda _=None, item=row: self._remove_extra_caption_row(item))
        text_edit.textChanged.connect(lambda _=None: self._update_tracks())
        start_edit.textChanged.connect(lambda _=None: self._update_tracks())
        end_edit.textChanged.connect(lambda _=None: self._update_tracks())
        position_combo.currentTextChanged.connect(lambda _=None: self._update_tracks())

        self._extra_caption_rows.append(row)
        self.extra_captions_layout.addWidget(frame)
        self.extra_text_check.setChecked(True)
        self._refresh_extra_caption_numbers()
        self._update_tracks()
        self._mark_preview_dirty("legenda extra adicionada")

    def _remove_extra_caption_row(self, row: Dict[str, Any]) -> None:
        if row in self._extra_caption_rows:
            self._extra_caption_rows.remove(row)
        frame = row.get("frame")
        if frame is not None:
            frame.setParent(None)
            frame.deleteLater()
        self._refresh_extra_caption_numbers()
        self._update_tracks()
        self._mark_preview_dirty("legenda extra removida")

    def _clear_extra_caption_rows(self) -> None:
        for row in list(self._extra_caption_rows):
            frame = row.get("frame")
            if frame is not None:
                frame.setParent(None)
                frame.deleteLater()
        self._extra_caption_rows.clear()
        if hasattr(self, "extra_text_check"):
            self.extra_text_check.setChecked(False)
        self._refresh_extra_caption_numbers()
        self._update_tracks()
        self._mark_preview_dirty("legendas extras limpas")

    def _clear_extra_caption_rows_silent(self) -> None:
        for row in list(getattr(self, "_extra_caption_rows", [])):
            frame = row.get("frame")
            if frame is not None:
                frame.setParent(None)
                frame.deleteLater()
        self._extra_caption_rows.clear()
        if hasattr(self, "extra_text_check"):
            self.extra_text_check.setChecked(False)
        self._refresh_extra_caption_numbers()

    def _refresh_extra_caption_numbers(self) -> None:
        for index, row in enumerate(self._extra_caption_rows, start=1):
            title = row.get("title")
            if title is not None:
                title.setText(f"Legenda extra {index}")
        if hasattr(self, "extra_text_status"):
            count = len(self._current_extra_caption_entries())
            if count:
                self.extra_text_status.setText(f"{count} legenda(s) extra(s) adicionada(s) na timeline.")
            else:
                self.extra_text_status.setText("Nenhuma legenda extra adicionada.")

    def _current_extra_caption_entries(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for row in getattr(self, "_extra_caption_rows", []):
            text_widget = row.get("text_edit")
            start_widget = row.get("start_edit")
            end_widget = row.get("end_edit")
            position_widget = row.get("position_combo")
            text = text_widget.text().strip() if text_widget is not None else ""
            if not text:
                continue
            start = self._time_to_seconds(start_widget.text() if start_widget is not None else "0")
            end = self._time_to_seconds(end_widget.text() if end_widget is not None else "0")
            if end <= start:
                end = start + 1.0
            entries.append({
                "text": text,
                "start": start,
                "end": end,
                "position": position_widget.currentText() if position_widget is not None else "centro",
                "start_time": self._format_timecode(start),
                "end_time": self._format_timecode(end),
            })
        return entries

    def _select_watermark_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar logo / marca d'água",
            "",
            "Imagens (*.png *.jpg *.jpeg *.webp *.bmp);;Todos os arquivos (*.*)",
        )
        if not path:
            return
        self._watermark_logo_path = path
        if hasattr(self, "watermark_logo_label"):
            self.watermark_logo_label.setText(f"Logo: {path}")
        if hasattr(self, "watermark_check"):
            self.watermark_check.setChecked(True)
        self._update_tracks()
        self._mark_preview_dirty("logo da marca d'água alterada")

    def _clear_watermark_logo(self) -> None:
        self._watermark_logo_path = ""
        if hasattr(self, "watermark_logo_label"):
            self.watermark_logo_label.setText("Logo: nenhuma")
        self._update_tracks()
        self._mark_preview_dirty("logo da marca d'água removida")

    # ------------------------------------------------------------------
    # Legendas / exportação
    # ------------------------------------------------------------------
    def _generate_narrator_subtitle_only(self) -> None:
        clip = self._clip
        if not clip:
            QMessageBox.information(self, "Montagem", "Envie um clipe para montagem primeiro.")
            return
        try:
            path = self._prepare_narrator_subtitle(clip)
            QMessageBox.information(self, "Legenda do narrador", f"Legenda gerada:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Legenda do narrador", str(exc))

    def _build_editor_options(self, clip: Dict[str, Any], output_path: Path, safe_stem: str) -> EditorExportOptions:
        base_video = Path(str(clip.get("output_path") or ""))
        if not base_video.exists():
            raise LayeredEditorError(f"Vídeo base não encontrado:\n{base_video}")
        duration = self._clip_duration(clip)
        working_dir = base_video.parent / "_tedvhs_layers"
        working_dir.mkdir(parents=True, exist_ok=True)

        anime_ass: Optional[Path] = None
        if self.anime_subtitle_check.isChecked():
            original_anime_ass = self._find_anime_subtitle_path(clip)
            if original_anime_ass:
                anime_ass = self.service.create_positioned_subtitle_copy(
                    original_anime_ass,
                    working_dir / f"{safe_stem}.anime.ass",
                    self.anime_subtitle_position_combo.currentText(),
                )

        narrator_ass: Optional[Path] = None
        if self.narrator_subtitle_check.isChecked():
            narrator_ass = self._prepare_narrator_subtitle(clip, output_stem=safe_stem)

        extra_ass: Optional[Path] = None
        extra_entries = self._current_extra_caption_entries()
        if self.extra_text_check.isChecked() and extra_entries:
            extra_ass = self.service.generate_extra_texts_ass(
                extra_entries,
                working_dir / f"{safe_stem}.legendas_extras.ass",
                duration_seconds=duration,
                title="Legendas extras TEDVHS",
            )

        watermark_ass: Optional[Path] = None
        watermark_logo: Optional[Path] = None
        if hasattr(self, "watermark_check") and self.watermark_check.isChecked():
            watermark_ass = self.service.generate_watermark_ass(
                self.watermark_text_edit.text(),
                working_dir / f"{safe_stem}.watermark.ass",
                duration_seconds=duration,
                position=self.watermark_position_combo.currentText(),
                title="Marca d'água TEDVHS",
            )
            logo_value = str(getattr(self, "_watermark_logo_path", "") or "").strip()
            if logo_value:
                candidate = Path(logo_value)
                if candidate.exists():
                    watermark_logo = candidate

        narration_audio = self._find_narration_audio_path(clip) if self.narration_audio_check.isChecked() else None
        return EditorExportOptions(
            base_video_path=base_video,
            output_path=output_path,
            original_volume=float(self.original_volume_spin.value()),
            narration_audio_path=narration_audio,
            narration_volume=float(self.narration_volume_spin.value()),
            anime_subtitle_path=anime_ass,
            narrator_subtitle_path=narrator_ass,
            extra_text_subtitle_path=extra_ass,
            watermark_subtitle_path=watermark_ass,
            watermark_image_path=watermark_logo,
            watermark_image_position=self.watermark_position_combo.currentText() if hasattr(self, "watermark_position_combo") else "superior direito",
            watermark_image_scale_percent=float(self.watermark_logo_size_spin.value()) if hasattr(self, "watermark_logo_size_spin") else 14.0,
            watermark_image_opacity=float(self.watermark_logo_opacity_spin.value()) if hasattr(self, "watermark_logo_opacity_spin") else 0.78,
            duration_seconds=duration,
        )

    def _export_final_video(self) -> None:
        clip = self._clip
        if not clip:
            QMessageBox.information(self, "Montagem", "Envie um clipe para montagem primeiro.")
            return
        if self._export_thread is not None:
            QMessageBox.information(self, "Exportação em andamento", "Aguarde a exportação atual terminar.")
            return
        base_video = Path(str(clip.get("output_path") or ""))
        if not base_video.exists():
            QMessageBox.warning(self, "Arquivo não encontrado", f"Vídeo base não encontrado:\n{base_video}")
            return

        try:
            self._persist_montage_complements_silent(clip)
            duration = self._clip_duration(clip)
            safe_stem = self._safe_output_stem(self.output_name_edit.text() or f"{base_video.stem} FINAL TEDVHS")
            output_path = base_video.with_name(f"{safe_stem}.mp4")
            options = self._build_editor_options(clip, output_path, safe_stem=safe_stem)

            anime_ass = options.anime_subtitle_path
            narrator_ass = options.narrator_subtitle_path
            extra_ass = options.extra_text_subtitle_path
            watermark_ass = options.watermark_subtitle_path
            narration_audio = options.narration_audio_path
            metadata = {
                "source_clip_id": clip.get("id"),
                "source_clip_name": clip.get("clip_name"),
                "source_output_path": str(base_video),
                "editor_layers": {
                    "anime_subtitle": bool(anime_ass),
                    "anime_subtitle_path": str(anime_ass) if anime_ass else "",
                    "narrator_subtitle": bool(narrator_ass),
                    "narrator_subtitle_path": str(narrator_ass) if narrator_ass else "",
                    "extra_text_items": self._current_extra_caption_entries() if self.extra_text_check.isChecked() else [],
                    "narration_audio": str(narration_audio) if narration_audio else "",
                    "narration_sync_path": str(self._find_narration_sync_path(clip) or ""),
                    "watermark": self.watermark_text_edit.text().strip() if hasattr(self, "watermark_text_edit") and self.watermark_check.isChecked() else "",
                    "watermark_path": str(watermark_ass) if watermark_ass else "",
                    "watermark_logo_path": str(getattr(self, "_watermark_logo_path", "") or ""),
                    "watermark_logo_size_percent": float(self.watermark_logo_size_spin.value()) if hasattr(self, "watermark_logo_size_spin") else 14.0,
                    "watermark_logo_opacity": float(self.watermark_logo_opacity_spin.value()) if hasattr(self, "watermark_logo_opacity_spin") else 0.78,
                    "original_volume": float(self.original_volume_spin.value()),
                    "narration_volume": float(self.narration_volume_spin.value()),
                    "narrator_subtitle_duration_mode": self.narrator_subtitle_duration_combo.currentText() if hasattr(self, "narrator_subtitle_duration_combo") else "vídeo inteiro",
                },
            }
            self._start_export_worker(options, metadata)
        except Exception as exc:
            QMessageBox.warning(self, "Exportação final", str(exc))

    def _start_export_worker(self, options: EditorExportOptions, metadata: Dict[str, Any]) -> None:
        self.export_final_btn.setEnabled(False)
        self.status_label.setText("Iniciando exportação final...")
        thread = QThread(self)
        worker = _EditorExportWorker(self.service, options, metadata)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(self._on_export_finished)
        worker.failed.connect(self._on_export_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_export_worker)
        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    def _on_export_finished(self, result: Dict[str, Any]) -> None:
        output_path = Path(str(result.get("output_path") or ""))
        registered_id = self._register_final_clip(output_path, result.get("metadata") or {})
        self.status_label.setText(f"Vídeo final exportado: {output_path}")
        message = f"Vídeo final exportado com sucesso:\n{output_path}"
        if registered_id:
            message += "\n\nEle também foi adicionado à Biblioteca de Clipes."
        QMessageBox.information(self, "Vídeo final pronto", message)
        self.final_video_exported.emit({"output_path": str(output_path), "id": registered_id})
        self.export_final_btn.setEnabled(True)

    def _on_export_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Exportação final", message)
        self.status_label.setText(f"Exportação falhou: {message}")
        self.export_final_btn.setEnabled(True)

    def _clear_export_worker(self) -> None:
        self._export_thread = None
        self._export_worker = None
        self.export_final_btn.setEnabled(True)

    def _prepare_narrator_subtitle(self, clip: Dict[str, Any], output_stem: str = "") -> Path:
        base_video = Path(str(clip.get("output_path") or ""))
        duration = self._duration_for_narrator_subtitle(clip)
        safe_stem = self._safe_output_stem(output_stem or base_video.stem)
        position = self.narrator_subtitle_position_combo.currentText()
        dynamic_enabled = bool(
            getattr(self, "dynamic_narrator_subtitle_check", None)
            and self.dynamic_narrator_subtitle_check.isChecked()
        )
        # Nomes separados evitam o player/FFmpeg reaproveitar uma legenda antiga
        # gerada em versões anteriores, especialmente no teste da prévia aplicada.
        suffix = "narrador_dinamico_tiktok_v16" if dynamic_enabled else "narrador_estavel"
        output_path = base_video.parent / "_tedvhs_layers" / f"{safe_stem}.{suffix}.ass"

        if dynamic_enabled:
            sync_path = self._find_narration_sync_path(clip)
            if not sync_path:
                raise LayeredEditorError(
                    "Narração dinâmica está ligada, mas não existe sync do áudio.\n\n"
                    "Faça assim:\n"
                    "1. Vá no grupo Narração;\n"
                    "2. Clique em Gerar áudio da narração novamente;\n"
                    "3. Quando o status mostrar sync dinâmico OK, atualize a prévia.\n\n"
                    "Ou desmarque Narração dinâmica para usar legenda estável por frases."
                )
            path = self.service.generate_narrator_ass_from_sync(
                self._current_narration_script_text(),
                sync_path,
                output_path,
                duration_seconds=duration,
                position=position,
                title="Legenda da narração TEDVHS dinâmica TikTok",
            )
            self.narrator_subtitle_status.setText(f"Legenda da narração dinâmica TikTok recriada sem destaque total: {path}")
            return path

        path = self.service.generate_narrator_stable_blocks_ass(
            self._current_narration_script_text(),
            output_path,
            duration_seconds=duration,
            position=position,
            title="Legenda do narrador TEDVHS",
        )
        self.narrator_subtitle_status.setText(f"Legenda da narração estável: {path}")
        return path


    # ------------------------------------------------------------------
    # Complementos da montagem: legenda, roteiro, narração e post
    # ------------------------------------------------------------------
    def _load_complement_fields(self, clip: Dict[str, Any]) -> None:
        metadata = self._read_clip_metadata(clip)
        package = metadata.get("narration_package") if isinstance(metadata.get("narration_package"), dict) else {}
        if not package and isinstance(clip.get("narration_package"), dict):
            package = clip.get("narration_package") or {}
        script = str(package.get("roteiro_narracao") or clip.get("narration_script") or metadata.get("narration_script") or "")
        blocks = package.get("narration_blocks") or metadata.get("narration_blocks") or []
        if isinstance(blocks, str):
            blocks = [line.strip() for line in blocks.splitlines() if line.strip()]
        if not blocks and script:
            blocks = self._split_text_into_narration_blocks(script)
        if hasattr(self, "narrator_script_edit"):
            self.narrator_script_edit.setPlainText(script)
        if hasattr(self, "narration_blocks_edit"):
            self.narration_blocks_edit.setPlainText("\n".join(str(block) for block in blocks if str(block).strip()))
        if hasattr(self, "tiktok_title_edit"):
            self.tiktok_title_edit.setText(str(package.get("titulo_tiktok") or clip.get("tiktok_title") or metadata.get("tiktok_title") or ""))
        if hasattr(self, "tiktok_caption_edit"):
            self.tiktok_caption_edit.setPlainText(str(package.get("texto_tiktok") or clip.get("tiktok_caption") or metadata.get("tiktok_caption") or ""))
        hashtags = package.get("hashtags") or clip.get("hashtags") or metadata.get("hashtags") or ""
        if isinstance(hashtags, list):
            hashtags = " ".join(str(tag) for tag in hashtags)
        if hasattr(self, "narration_hashtags_edit"):
            self.narration_hashtags_edit.setText(str(hashtags or ""))
        if hasattr(self, "narration_style_combo"):
            self._set_combo_text(self.narration_style_combo, str(package.get("estilo") or clip.get("narration_style") or metadata.get("narration_style") or "Empolgado"))
        if hasattr(self, "narration_length_combo"):
            self._set_combo_text(self.narration_length_combo, str(package.get("tamanho") or clip.get("narration_length") or metadata.get("narration_length") or "Acompanhar clipe inteiro"))
        if hasattr(self, "narration_retention_check"):
            retention_value = package.get("engagement_mode")
            if retention_value is None:
                retention_value = metadata.get("narration_engagement_mode")
            if retention_value is None:
                retention_value = True
            self.narration_retention_check.setChecked(bool(retention_value))
        if hasattr(self, "narration_retention_goal_edit"):
            self.narration_retention_goal_edit.setText(str(package.get("engagement_goal") or metadata.get("narration_engagement_goal") or ""))
        if hasattr(self, "dynamic_narrator_subtitle_check"):
            dynamic_value = metadata.get("narration_dynamic_enabled")
            if dynamic_value is None:
                dynamic_value = True
            self.dynamic_narrator_subtitle_check.setChecked(bool(dynamic_value))
        # Carrega legendas extras e marca d'água da montagem, quando existirem no JSON do clipe.
        extra_items = metadata.get("extra_text_items") or metadata.get("extra_captions") or []
        self._clear_extra_caption_rows_silent()
        if isinstance(extra_items, list):
            for item in extra_items:
                if not isinstance(item, dict):
                    continue
                self._add_extra_caption_row(
                    text=str(item.get("text") or ""),
                    start_time=str(item.get("start_time") or self._format_timecode(float(item.get("start") or 0.0))),
                    end_time=str(item.get("end_time") or self._format_timecode(float(item.get("end") or 15.0))),
                    position=str(item.get("position") or "centro"),
                )
        watermark_text = str(metadata.get("watermark_text") or metadata.get("watermark") or "")
        if watermark_text and hasattr(self, "watermark_text_edit"):
            self.watermark_text_edit.setText(watermark_text)
        logo_path = str(metadata.get("watermark_logo_path") or "")
        self._watermark_logo_path = logo_path
        if hasattr(self, "watermark_logo_label"):
            self.watermark_logo_label.setText(f"Logo: {logo_path}" if logo_path else "Logo: nenhuma")
        if hasattr(self, "watermark_logo_size_spin") and metadata.get("watermark_logo_size_percent") is not None:
            try:
                self.watermark_logo_size_spin.setValue(float(metadata.get("watermark_logo_size_percent")))
            except Exception:
                pass
        if hasattr(self, "watermark_logo_opacity_spin") and metadata.get("watermark_logo_opacity") is not None:
            try:
                self.watermark_logo_opacity_spin.setValue(float(metadata.get("watermark_logo_opacity")))
            except Exception:
                pass
        audio_data = self._narration_audio_data_for_clip(clip)
        if hasattr(self, "narration_voice_combo"):
            self._set_combo_text(self.narration_voice_combo, str(audio_data.get("voice") or DEFAULT_TTS_VOICE))
        if hasattr(self, "narration_rate_combo"):
            self._set_combo_text(self.narration_rate_combo, str(audio_data.get("rate") or DEFAULT_TTS_RATE))

    def _refresh_complement_statuses(self, clip: Optional[Dict[str, Any]] = None) -> None:
        clip = clip or self._clip
        if not clip:
            return
        self._update_subtitle_status_label(clip)
        self._update_narration_status_label(clip)
        self._update_narration_audio_status_label(clip)
        anime_sub = self._find_anime_subtitle_path(clip)
        narration_audio = self._find_narration_audio_path(clip)
        if hasattr(self, "anime_subtitle_status"):
            self.anime_subtitle_status.setText(
                f"Legenda do anime: {anime_sub}" if anime_sub else "Legenda do anime: nenhuma .ass PT-BR encontrada. Gere a legenda aqui na Montagem ou mantenha esta camada desligada."
            )
        if hasattr(self, "narration_audio_status"):
            self.narration_audio_status.setText(
                f"Áudio da narração: {narration_audio}" if narration_audio else "Áudio da narração: não encontrado. Gere áudio aqui na Montagem ou mantenha esta camada desligada."
            )
        if hasattr(self, "anime_subtitle_check") and anime_sub:
            self.anime_subtitle_check.setChecked(True)
        if hasattr(self, "narration_audio_check") and narration_audio:
            self.narration_audio_check.setChecked(True)
        self._update_tracks()

    def _subtitle_data_for_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = self._read_clip_metadata(clip)
        subtitles = metadata.get("subtitles_ptbr") if isinstance(metadata.get("subtitles_ptbr"), dict) else {}
        if subtitles:
            return dict(subtitles)
        return {
            "srt_path": clip.get("subtitle_srt_path") or metadata.get("subtitle_srt_path"),
            "ass_path": clip.get("subtitle_ass_path") or metadata.get("subtitle_ass_path"),
            "source": metadata.get("subtitle_source") or "",
            "cue_count": metadata.get("subtitle_cue_count") or "",
        }

    def _update_subtitle_status_label(self, clip: Dict[str, Any]) -> None:
        label = getattr(self, "subtitle_status_label", None)
        if label is None:
            return
        data = self._subtitle_data_for_clip(clip)
        srt = Path(str(data.get("srt_path") or ""))
        ass = Path(str(data.get("ass_path") or ""))
        if srt.exists() or ass.exists():
            label.setText(
                "Status: legenda PT-BR pronta para usar como camada.\n"
                f"Fonte: {data.get('source') or 'arquivo/API'} | Falas: {data.get('cue_count') or '-'}\n"
                f"SRT: {srt if srt.exists() else '-'}\nASS: {ass if ass.exists() else '-'}"
            )
        else:
            label.setText(
                "Status: sem legenda PT-BR para esta montagem.\n"
                "Clique em ‘Gerar legenda PT-BR’. Depois ative a camada ‘Legenda do anime PT-BR’."
            )

    def _on_generate_current_subtitle(self) -> None:
        if not self._clip:
            QMessageBox.information(self, "Legenda PT-BR", "Envie um clipe para montagem primeiro.")
            return
        self._start_subtitle_worker(self._clip)

    def _start_subtitle_worker(self, clip: Dict[str, Any]) -> None:
        if self._subtitle_thread is not None:
            QMessageBox.information(self, "Legenda em andamento", "Aguarde a operação de legenda terminar.")
            return
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_GEMINI_MODEL
        if not model:
            model = DEFAULT_GEMINI_MODEL
            self.gemini_model_edit.setText(model)
        self._maybe_save_gemini_settings(api_key, model)
        reply = QMessageBox.question(
            self,
            "Gerar legenda PT-BR?",
            "O app tentará usar legenda PT-BR do arquivo original, traduzir se necessário ou transcrever/traduzir pelo áudio.\n\n"
            "Quando precisar de Gemini, isso consome cota gratuita. Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self._set_complement_buttons_enabled(False)
        self.status_label.setText("Gerando legenda PT-BR da montagem...")
        thread = QThread(self)
        worker = _ClipSubtitleWorker(self.subtitle_service, clip, api_key, model, action="generate")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(self._on_subtitle_finished)
        worker.failed.connect(self._on_subtitle_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_subtitle_worker)
        self._subtitle_thread = thread
        self._subtitle_worker = worker
        thread.start()

    def _on_subtitle_finished(self, result: Dict[str, Any]) -> None:
        clip = self._clip
        subtitle_payload = {
            "srt_path": result.get("srt_path"),
            "ass_path": result.get("ass_path"),
            "cue_count": result.get("cue_count"),
            "source": result.get("source"),
            "source_language": result.get("source_language"),
            "source_codec": result.get("source_codec"),
            "translated_to_ptbr": result.get("translated_to_ptbr"),
            "transcribed_from_audio": result.get("transcribed_from_audio"),
            "model": result.get("model"),
            "status": result.get("status"),
        }
        if clip:
            self._update_metadata_json(clip, {
                "subtitles_ptbr": subtitle_payload,
                "subtitle_srt_path": result.get("srt_path"),
                "subtitle_ass_path": result.get("ass_path"),
            })
        self.status_label.setText("Legenda PT-BR criada e vinculada à montagem.")
        QMessageBox.information(
            self,
            "Legenda PT-BR criada",
            f"Legenda criada com sucesso.\n\nSRT: {result.get('srt_path')}\nASS: {result.get('ass_path')}"
        )
        if clip:
            self._reload_current_clip_metadata()
            self._refresh_complement_statuses(self._clip)
        self._set_complement_buttons_enabled(True)
        self._mark_preview_dirty("legenda PT-BR gerada")

    def _on_subtitle_failed(self, message: str) -> None:
        friendly = _friendly_gemini_error(message)
        QMessageBox.warning(self, "Legenda PT-BR", friendly)
        self.status_label.setText(f"Legenda falhou: {friendly}")
        self._set_complement_buttons_enabled(True)

    def _clear_subtitle_worker(self) -> None:
        self._subtitle_thread = None
        self._subtitle_worker = None
        self._set_complement_buttons_enabled(True)

    def _open_current_subtitle(self) -> None:
        clip = self._clip
        if not clip:
            return
        data = self._subtitle_data_for_clip(clip)
        for value in (data.get("ass_path"), data.get("srt_path")):
            path = Path(str(value or ""))
            if path.exists():
                self._open_path(path)
                return
        QMessageBox.information(self, "Legenda PT-BR", "Nenhuma legenda PT-BR foi encontrada para esta montagem.")

    def _on_generate_current_narration(self) -> None:
        if not self._clip:
            QMessageBox.information(self, "Roteiro de narração", "Envie um clipe para montagem primeiro.")
            return
        self._start_narration_worker(self._clip)

    def _start_narration_worker(self, clip: Dict[str, Any]) -> None:
        if self._narration_thread is not None:
            QMessageBox.information(self, "Roteiro em andamento", "Aguarde o roteiro atual terminar.")
            return
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        if not api_key:
            QMessageBox.warning(self, "API Key necessária", "Cole sua API Key do Gemini antes de gerar o roteiro.")
            return
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_NARRATION_MODEL
        if not model:
            model = DEFAULT_NARRATION_MODEL
            self.gemini_model_edit.setText(model)
        self._maybe_save_gemini_settings(api_key, model)
        has_description = bool(str(clip.get("description") or self._read_clip_metadata(clip).get("description") or "").strip())
        subtitle_data = self._subtitle_data_for_clip(clip)
        has_subtitle = Path(str(subtitle_data.get("srt_path") or "")).exists()
        if not has_description and not has_subtitle:
            reply = QMessageBox.question(
                self,
                "Gerar mesmo assim?",
                "Este clipe ainda não tem descrição IA nem legenda PT-BR. O roteiro pode ficar genérico.\n\nDeseja continuar mesmo assim?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        style = self.narration_style_combo.currentText().strip() if hasattr(self, "narration_style_combo") else "Empolgado"
        length = self.narration_length_combo.currentText().strip() if hasattr(self, "narration_length_combo") else "Acompanhar clipe inteiro"
        engagement_mode = bool(getattr(self, "narration_retention_check", None) and self.narration_retention_check.isChecked())
        engagement_goal = self.narration_retention_goal_edit.text().strip() if hasattr(self, "narration_retention_goal_edit") else ""
        self._set_complement_buttons_enabled(False)
        self.status_label.setText("Gerando roteiro de narração da montagem...")
        thread = QThread(self)
        worker = _ClipNarrationWorker(self.narration_service, clip, api_key, model, style, length, engagement_mode=engagement_mode, engagement_goal=engagement_goal)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(self._on_narration_finished)
        worker.failed.connect(self._on_narration_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_narration_worker)
        self._narration_thread = thread
        self._narration_worker = worker
        thread.start()

    def _on_narration_finished(self, payload: Dict[str, Any]) -> None:
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        if not result:
            QMessageBox.warning(self, "Roteiro de narração", "A API respondeu, mas o roteiro veio vazio.")
            self._set_complement_buttons_enabled(True)
            return
        script = str(result.get("roteiro_narracao") or "")
        blocks = self._split_text_into_narration_blocks(script)
        self.narrator_script_edit.setPlainText(script)
        self.narration_blocks_edit.setPlainText("\n".join(blocks))
        self.tiktok_title_edit.setText(str(result.get("titulo_tiktok") or ""))
        self.tiktok_caption_edit.setPlainText(str(result.get("texto_tiktok") or ""))
        hashtags = result.get("hashtags") or []
        hashtags_text = " ".join(str(tag) for tag in hashtags) if isinstance(hashtags, list) else str(hashtags or "")
        self.narration_hashtags_edit.setText(hashtags_text)
        clip = self._clip
        if clip:
            package = dict(result)
            package.update({
                "modelo": payload.get("model"),
                "estilo": payload.get("style"),
                "tamanho": payload.get("length"),
                "engagement_mode": payload.get("engagement_mode"),
                "engagement_goal": payload.get("engagement_goal"),
                "abertura_for_you": result.get("abertura_for_you"),
                "fechamento_retencao": result.get("fechamento_retencao"),
                "narration_blocks": blocks,
            })
            self._update_metadata_json(clip, {
                "narration_package": package,
                "narration_script": script,
                "narration_blocks": blocks,
                "narration_hook": result.get("gancho"),
                "tiktok_title": result.get("titulo_tiktok"),
                "tiktok_caption": result.get("texto_tiktok"),
                "hashtags": hashtags_text,
                "narration_style": payload.get("style"),
                "narration_length": payload.get("length"),
                "narration_engagement_mode": payload.get("engagement_mode"),
                "narration_engagement_goal": payload.get("engagement_goal"),
                "narration_opening_for_you": result.get("abertura_for_you"),
                "narration_retention_ending": result.get("fechamento_retencao"),
                "narration_target_seconds": payload.get("target_seconds"),
                "narration_model": payload.get("model"),
            })
            self._reload_current_clip_metadata()
            self._refresh_complement_statuses(self._clip)
        self.status_label.setText("Roteiro gerado e salvo na montagem.")
        QMessageBox.information(self, "Roteiro pronto", "Roteiro de narração gerado com sucesso.")
        self._set_complement_buttons_enabled(True)
        self._mark_preview_dirty("roteiro de narração gerado")

    def _on_narration_failed(self, message: str) -> None:
        friendly = _friendly_gemini_error(message)
        QMessageBox.warning(self, "Roteiro de narração", friendly)
        self.status_label.setText(f"Roteiro falhou: {friendly}")
        self._set_complement_buttons_enabled(True)

    def _clear_narration_worker(self) -> None:
        self._narration_thread = None
        self._narration_worker = None
        self._set_complement_buttons_enabled(True)

    def _persist_montage_complements_silent(self, clip: Dict[str, Any]) -> None:
        """Salvar campos editáveis da montagem sem abrir pop-up.

        Isso garante que a exportação final herde o roteiro, post, hashtags e
        blocos exatamente como estão na tela, mesmo se o usuário esquecer de
        clicar em Salvar roteiro/post antes de exportar.
        """
        if not clip:
            return
        blocks = self._current_narration_blocks()
        script = self._current_narration_script_text()
        title = self.tiktok_title_edit.text().strip() if hasattr(self, "tiktok_title_edit") else ""
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        style = self.narration_style_combo.currentText().strip() if hasattr(self, "narration_style_combo") else ""
        length = self.narration_length_combo.currentText().strip() if hasattr(self, "narration_length_combo") else ""
        engagement_mode = bool(getattr(self, "narration_retention_check", None) and self.narration_retention_check.isChecked())
        engagement_goal = self.narration_retention_goal_edit.text().strip() if hasattr(self, "narration_retention_goal_edit") else ""
        package = {
            "gancho": self._first_sentence(script),
            "roteiro_narracao": script,
            "narration_blocks": blocks,
            "titulo_tiktok": title,
            "texto_tiktok": caption,
            "hashtags": hashtags,
            "estilo": style,
            "tamanho": length,
            "engagement_mode": engagement_mode,
            "engagement_goal": engagement_goal,
            "fonte": "montagem",
        }
        self._update_metadata_json(clip, {
            "narration_package": package,
            "narration_script": script,
            "narration_blocks": blocks,
            "narration_hook": package.get("gancho"),
            "tiktok_title": title,
            "tiktok_caption": caption,
            "hashtags": hashtags,
            "narration_style": style,
            "narration_length": length,
            "narration_engagement_mode": engagement_mode,
            "narration_engagement_goal": engagement_goal,
            "extra_text_items": self._current_extra_caption_entries(),
            "watermark_logo_path": str(getattr(self, "_watermark_logo_path", "") or ""),
            "watermark_logo_size_percent": float(self.watermark_logo_size_spin.value()) if hasattr(self, "watermark_logo_size_spin") else 14.0,
            "watermark_logo_opacity": float(self.watermark_logo_opacity_spin.value()) if hasattr(self, "watermark_logo_opacity_spin") else 0.78,
            "watermark_text": self.watermark_text_edit.text().strip() if hasattr(self, "watermark_text_edit") else "",
            "narration_dynamic_enabled": bool(getattr(self, "dynamic_narrator_subtitle_check", None) and self.dynamic_narrator_subtitle_check.isChecked()),
        })

    def _save_narration_metadata(self) -> None:
        clip = self._clip
        if not clip:
            return
        blocks = self._current_narration_blocks()
        script = self._current_narration_script_text()
        title = self.tiktok_title_edit.text().strip() if hasattr(self, "tiktok_title_edit") else ""
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        style = self.narration_style_combo.currentText().strip() if hasattr(self, "narration_style_combo") else ""
        length = self.narration_length_combo.currentText().strip() if hasattr(self, "narration_length_combo") else ""
        engagement_mode = bool(getattr(self, "narration_retention_check", None) and self.narration_retention_check.isChecked())
        engagement_goal = self.narration_retention_goal_edit.text().strip() if hasattr(self, "narration_retention_goal_edit") else ""
        package = {
            "gancho": self._first_sentence(script),
            "roteiro_narracao": script,
            "narration_blocks": blocks,
            "titulo_tiktok": title,
            "texto_tiktok": caption,
            "hashtags": hashtags,
            "estilo": style,
            "tamanho": length,
            "engagement_mode": engagement_mode,
            "engagement_goal": engagement_goal,
            "fonte": "manual_montagem",
        }
        self._update_metadata_json(clip, {
            "narration_package": package,
            "narration_script": script,
            "narration_blocks": blocks,
            "narration_hook": package.get("gancho"),
            "tiktok_title": title,
            "tiktok_caption": caption,
            "hashtags": hashtags,
            "narration_style": style,
            "narration_length": length,
            "narration_engagement_mode": engagement_mode,
            "narration_engagement_goal": engagement_goal,
            "extra_text_items": self._current_extra_caption_entries(),
            "watermark_logo_path": str(getattr(self, "_watermark_logo_path", "") or ""),
            "watermark_logo_size_percent": float(self.watermark_logo_size_spin.value()) if hasattr(self, "watermark_logo_size_spin") else 14.0,
            "watermark_logo_opacity": float(self.watermark_logo_opacity_spin.value()) if hasattr(self, "watermark_logo_opacity_spin") else 0.78,
            "watermark_text": self.watermark_text_edit.text().strip() if hasattr(self, "watermark_text_edit") else "",
            "narration_dynamic_enabled": bool(getattr(self, "dynamic_narrator_subtitle_check", None) and self.dynamic_narrator_subtitle_check.isChecked()),
        })
        self._reload_current_clip_metadata()
        self._refresh_complement_statuses(self._clip)
        self.status_label.setText("Roteiro, post e hashtags salvos na montagem.")
        QMessageBox.information(self, "Complementos salvos", "Roteiro, post e hashtags foram salvos no JSON lateral do clipe.")
        self._mark_preview_dirty("roteiro/post salvo")

    def _current_narration_blocks(self) -> List[str]:
        edit = getattr(self, "narration_blocks_edit", None)
        if edit is None:
            return []
        lines: List[str] = []
        for line in edit.toPlainText().splitlines():
            cleaned = self._clean_narration_block_line(line)
            if cleaned:
                lines.append(cleaned)
        return lines

    def _current_narration_script_text(self) -> str:
        blocks = self._current_narration_blocks()
        if blocks:
            return "\n\n".join(blocks).strip()
        return self.narrator_script_edit.toPlainText().strip() if hasattr(self, "narrator_script_edit") else ""

    @staticmethod
    def _clean_narration_block_line(line: str) -> str:
        cleaned = str(line or "").strip()
        cleaned = re.sub(r"^[-•*\d\.\)\s]+", "", cleaned).strip()
        return cleaned

    def _split_text_into_narration_blocks(self, text: str, max_chars: int = 95) -> List[str]:
        raw = str(text or "").strip()
        if not raw:
            return []
        raw = raw.replace("\r", "\n")
        paragraphs = [p.strip() for p in raw.split("\n") if p.strip()]
        if len(paragraphs) >= 2:
            blocks = [self._clean_narration_block_line(p) for p in paragraphs]
            return [b for b in blocks if b]
        parts = re.split(r"(?<=[.!?])\s+", raw)
        blocks: List[str] = []
        current = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if not current:
                current = part
            elif len(current) + 1 + len(part) <= max_chars:
                current = f"{current} {part}"
            else:
                blocks.append(current.strip())
                current = part
        if current:
            blocks.append(current.strip())
        return blocks

    def _split_narration_script_into_blocks(self) -> None:
        script = self.narrator_script_edit.toPlainText().strip() if hasattr(self, "narrator_script_edit") else ""
        if not script:
            QMessageBox.information(self, "Blocos de fala", "Gere ou escreva um roteiro antes de dividir em blocos.")
            return
        blocks = self._split_text_into_narration_blocks(script)
        self.narration_blocks_edit.setPlainText("\n".join(blocks))
        self.status_label.setText(f"Roteiro dividido em {len(blocks)} bloco(s) de fala.")

    def _add_narration_block(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "Adicionar fala", "Digite a nova fala do narrador:", "")
        if not ok:
            return
        cleaned = self._clean_narration_block_line(text)
        if not cleaned:
            return
        existing = self.narration_blocks_edit.toPlainText().rstrip()
        self.narration_blocks_edit.setPlainText(f"{existing}\n{cleaned}".strip())
        self._apply_narration_blocks_to_script(show_message=False)
        self._mark_preview_dirty("fala adicionada")

    def _apply_narration_blocks_to_script(self, show_message: bool = True) -> None:
        blocks = self._current_narration_blocks()
        if not blocks:
            if show_message:
                QMessageBox.information(self, "Blocos de fala", "Não há blocos para aplicar.")
            return
        self.narrator_script_edit.setPlainText("\n\n".join(blocks))
        if show_message:
            self.status_label.setText(f"{len(blocks)} bloco(s) aplicados ao roteiro principal.")
        self._mark_preview_dirty("blocos aplicados ao roteiro")

    def _on_generate_narration_audio(self) -> None:
        clip = self._clip
        if not clip:
            QMessageBox.information(self, "Narração", "Envie um clipe para montagem primeiro.")
            return
        script = self._current_narration_script_text()
        if not script:
            QMessageBox.warning(self, "Roteiro vazio", "Gere ou escreva o roteiro antes de criar o áudio.")
            return
        voice = self.narration_voice_combo.currentText().strip() if hasattr(self, "narration_voice_combo") else DEFAULT_TTS_VOICE
        rate = self.narration_rate_combo.currentText().strip() if hasattr(self, "narration_rate_combo") else DEFAULT_TTS_RATE
        self._start_narration_audio_worker(clip, script=script, voice=voice, rate=rate)

    def _start_narration_audio_worker(self, clip: Dict[str, Any], script: str, voice: str, rate: str) -> None:
        if self._narration_audio_thread is not None:
            QMessageBox.information(self, "Narração em andamento", "Aguarde o áudio atual terminar.")
            return
        self._set_complement_buttons_enabled(False)
        self.status_label.setText("Gerando áudio da narração da montagem...")
        thread = QThread(self)
        worker = _ClipNarrationAudioWorker(
            audio_service=self.narration_audio_service,
            clip=clip,
            script=script,
            voice=voice,
            rate=rate,
            action="generate_audio",
            background_volume=0.25,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(self._on_narration_audio_finished)
        worker.failed.connect(self._on_narration_audio_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_narration_audio_worker)
        self._narration_audio_thread = thread
        self._narration_audio_worker = worker
        thread.start()

    def _on_narration_audio_finished(self, payload: Dict[str, Any]) -> None:
        clip = self._clip
        if not clip:
            self._set_complement_buttons_enabled(True)
            return
        audio_path = Path(str(payload.get("audio_path") or ""))
        clip_path = Path(str(clip.get("output_path") or ""))
        audio_duration = self._probe_media_duration_seconds(audio_path)
        clip_duration = self._probe_media_duration_seconds(clip_path)
        self._update_metadata_json(clip, {
            "narration_audio_path": payload.get("audio_path"),
            "narration_sync_path": payload.get("sync_path") or "",
            "narration_sync_available": bool(payload.get("sync_available")),
            "narration_sync_word_count": payload.get("sync_word_count") or 0,
            "narration_sync_source": payload.get("sync_source") or "",
            "narration_sync_estimated": False,
            "narration_sync_warning": payload.get("sync_warning") or "",
            "narration_voice": payload.get("voice"),
            "narration_rate": payload.get("rate"),
            "narration_audio_engine": payload.get("engine"),
            "narration_audio_duration_seconds": audio_duration,
            "narration_clip_duration_seconds": clip_duration,
        })
        self._reload_current_clip_metadata()
        self._refresh_complement_statuses(self._clip)
        message = f"Áudio gerado:\n{payload.get('audio_path')}"
        if payload.get("sync_available"):
            source = str(payload.get("sync_source") or "sync")
            message += f"\n\nSync REAL da legenda dinâmica: OK ({payload.get('sync_word_count') or 0} palavras). Fonte: {source}."
        else:
            warning = str(payload.get("sync_warning") or "")
            message += (
                "\n\nAtenção: áudio gerado sem sync REAL palavra por palavra."
                "\nA Narração dinâmica ficará desativada/bloqueada para evitar legenda fora de sincronia."
            )
            if warning:
                message += f"\n\nDetalhe: {warning}"
        if audio_duration > 0 and clip_duration > 0:
            message += f"\n\nDuração do áudio: {self._format_time(audio_duration)} | Duração do clipe: {self._format_time(clip_duration)}"
            if audio_duration < clip_duration * 0.70:
                message += "\n\nAtenção: a narração ficou bem mais curta que o vídeo. Use ‘Acompanhar clipe inteiro’ e gere de novo se quiser cobrir mais tempo."
            elif audio_duration > clip_duration * 1.20:
                message += "\n\nAtenção: a narração ficou maior que o vídeo. Reduza o roteiro, aumente velocidade ou gere uma versão menor."
        QMessageBox.information(self, "Narração pronta", message)
        self.status_label.setText("Áudio da narração gerado e ativado como camada.")
        self._set_complement_buttons_enabled(True)
        self._mark_preview_dirty("áudio da narração gerado")

    def _on_narration_audio_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Áudio da narração", message)
        self.status_label.setText(f"Áudio falhou: {message}")
        self._set_complement_buttons_enabled(True)

    def _clear_narration_audio_worker(self) -> None:
        self._narration_audio_thread = None
        self._narration_audio_worker = None
        self._set_complement_buttons_enabled(True)

    def _play_narration_audio(self) -> None:
        clip = self._clip
        if not clip:
            return
        path = self._find_narration_audio_path(clip)
        if not path or not path.exists():
            QMessageBox.warning(self, "Áudio não encontrado", "Gere o áudio da narração primeiro.")
            return
        try:
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.player.pause()
            source = self.narration_audio_player.source()
            current = source.toLocalFile() if not source.isEmpty() else ""
            source_changed = True
            if current:
                try:
                    source_changed = str(Path(current).resolve()).lower() != str(path.resolve()).lower()
                except Exception:
                    source_changed = True
            if source_changed:
                self.narration_audio_player.setSource(QUrl.fromLocalFile(str(path)))
                self.narration_audio_player.setPosition(0)
            if self.narration_audio_player.playbackState() == QMediaPlayer.PlayingState:
                self.narration_audio_player.pause()
            else:
                self.narration_audio_player.play()
        except Exception as exc:
            QMessageBox.warning(self, "Ouvir narração", str(exc))

    def _on_narration_audio_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        button = getattr(self, "play_narration_audio_btn", None)
        if button is None:
            return
        if state == QMediaPlayer.PlayingState:
            button.setText("⏸ Pausar narração")
        elif state == QMediaPlayer.PausedState:
            button.setText("▶ Continuar narração")
        else:
            button.setText("Ouvir narração")

    def _open_narration_audio(self) -> None:
        clip = self._clip
        if not clip:
            return
        path = self._find_narration_audio_path(clip)
        if path and path.exists():
            self._open_path(path)
        else:
            QMessageBox.warning(self, "Áudio não encontrado", "Gere o áudio da narração primeiro.")

    def _narration_audio_data_for_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = self._read_clip_metadata(clip)
        output_path = Path(str(clip.get("output_path") or metadata.get("output_path") or ""))
        audio_path = clip.get("narration_audio_path") or metadata.get("narration_audio_path") or metadata.get("audio_narration_path") or ""
        if not audio_path and output_path.name:
            for candidate in (
                output_path.with_name(f"{output_path.stem} narração.mp3"),
                output_path.with_name(f"{output_path.stem}.narracao.mp3"),
                output_path.with_name(f"{output_path.stem} narracao.mp3"),
            ):
                if candidate.exists():
                    audio_path = str(candidate)
                    break
        sync_path = clip.get("narration_sync_path") or metadata.get("narration_sync_path") or ""
        if not sync_path and audio_path:
            candidate = Path(str(audio_path)).with_suffix(".sync.json")
            if candidate.exists():
                sync_path = str(candidate)
        return {
            "audio_path": str(audio_path or ""),
            "sync_path": str(sync_path or ""),
            "sync_available": bool(sync_path and Path(str(sync_path)).exists() and self._is_real_narration_sync(Path(str(sync_path)))),
            "sync_word_count": metadata.get("narration_sync_word_count") or "",
            "sync_source": metadata.get("narration_sync_source") or "",
            "sync_estimated": False,
            "voice": str(clip.get("narration_voice") or metadata.get("narration_voice") or DEFAULT_TTS_VOICE),
            "rate": str(clip.get("narration_rate") or metadata.get("narration_rate") or DEFAULT_TTS_RATE),
            "engine": str(metadata.get("narration_audio_engine") or "edge-tts"),
        }

    def _update_narration_audio_status_label(self, clip: Dict[str, Any]) -> None:
        label = getattr(self, "narration_audio_status_label", None)
        if label is None:
            return
        data = self._narration_audio_data_for_clip(clip)
        audio_path = Path(str(data.get("audio_path") or ""))
        sync_path = Path(str(data.get("sync_path") or ""))
        if audio_path.exists():
            if sync_path.exists():
                source = str(data.get("sync_source") or "sync")
                label.setText(
                    f"Status: áudio de narração pronto com sync dinâmico REAL OK.\n"
                    f"Fonte: {source}\nÁudio: {audio_path}\nSync: {sync_path}"
                )
            else:
                label.setText(
                    f"Status: áudio de narração pronto, mas sem sync palavra por palavra.\n"
                    f"Áudio: {audio_path}\nGere o áudio novamente após atualizar o edge-tts para tentar criar sync dinâmico real."
                )
        else:
            label.setText("Status: sem áudio de narração salvo para esta montagem. Gere o áudio após ajustar o roteiro.")

    def _update_narration_status_label(self, clip: Dict[str, Any]) -> None:
        label = getattr(self, "narration_status_label", None)
        if label is None:
            return
        metadata = self._read_clip_metadata(clip)
        package = metadata.get("narration_package") if isinstance(metadata.get("narration_package"), dict) else {}
        script = str(package.get("roteiro_narracao") or metadata.get("narration_script") or clip.get("narration_script") or "").strip()
        if script:
            label.setText(
                "Status: roteiro pronto para esta montagem.\n"
                f"Estilo: {package.get('estilo') or metadata.get('narration_style') or '-'} | Tamanho: {package.get('tamanho') or metadata.get('narration_length') or '-'}"
            )
        else:
            label.setText("Status: sem roteiro salvo. Gere com IA ou escreva manualmente aqui na Montagem.")

    def _set_complement_buttons_enabled(self, enabled: bool) -> None:
        for attr in (
            "generate_subtitle_btn", "open_subtitle_btn", "generate_narration_btn", "save_narration_btn",
            "copy_post_btn", "copy_narration_btn", "generate_narration_audio_btn", "play_narration_audio_btn",
            "open_narration_audio_btn", "test_gemini_btn", "save_api_key_btn", "clear_api_key_btn",
            "add_extra_caption_btn", "clear_extra_captions_btn", "select_watermark_logo_btn", "clear_watermark_logo_btn",
        ):
            button = getattr(self, attr, None)
            if button is not None:
                button.setEnabled(enabled)

    def _maybe_save_gemini_settings(self, api_key: str, model: str) -> None:
        checkbox = getattr(self, "save_api_key_checkbox", None)
        if checkbox is not None and checkbox.isChecked():
            try:
                self.api_settings.save_gemini(api_key=api_key, model=model)
            except Exception as exc:
                logger.warning("Não foi possível salvar Gemini settings: %s", exc)

    def _save_gemini_settings_from_fields(self) -> None:
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_GEMINI_MODEL
        if not api_key:
            QMessageBox.warning(self, "API Key vazia", "Cole uma API Key do Gemini antes de salvar.")
            return
        try:
            self.api_settings.save_gemini(api_key=api_key, model=model)
            if hasattr(self, "save_api_key_checkbox"):
                self.save_api_key_checkbox.setChecked(True)
            QMessageBox.information(self, "Chave salva", "API Key do Gemini salva localmente neste PC.")
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))

    def _clear_saved_gemini_api_key(self) -> None:
        try:
            self.api_settings.clear_gemini_api_key()
            if hasattr(self, "gemini_api_key_edit"):
                self.gemini_api_key_edit.clear()
            if hasattr(self, "save_api_key_checkbox"):
                self.save_api_key_checkbox.setChecked(False)
            QMessageBox.information(self, "Chave apagada", "API Key salva foi apagada deste PC.")
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao apagar", str(exc))

    def _test_gemini_connection(self) -> None:
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_GEMINI_MODEL
        if not api_key:
            QMessageBox.warning(self, "API Key necessária", "Cole sua API Key do Gemini no campo API Key.")
            return
        if not model:
            model = DEFAULT_GEMINI_MODEL
            self.gemini_model_edit.setText(model)
        try:
            self.status_label.setText("Testando Gemini API...")
            result = self.ai_test_service.test_connection(api_key=api_key, model=model)
            QMessageBox.information(self, "Gemini conectado", f"Gemini API respondeu corretamente.\n\nModelo: {result.get('model') or model}")
            self._maybe_save_gemini_settings(api_key, result.get("model") or model)
        except GeminiSceneAIError as exc:
            QMessageBox.warning(self, "Gemini não disponível", _friendly_gemini_error(exc))
        except Exception as exc:
            QMessageBox.warning(self, "Gemini não disponível", _friendly_gemini_error(exc))

    def _copy_tiktok_post_package(self) -> None:
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        post = self._compose_tiktok_post_text(caption, hashtags)
        if not post:
            QMessageBox.information(self, "Nada para copiar", "Gere ou escreva o texto da publicação antes de copiar.")
            return
        self._copy_text_to_clipboard(post, "Post com hashtags copiado.")

    def _copy_narration_package(self) -> None:
        title = self.tiktok_title_edit.text().strip() if hasattr(self, "tiktok_title_edit") else ""
        script = self._current_narration_script_text()
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        post = self._compose_tiktok_post_text(caption, hashtags)
        parts = []
        if title:
            parts.append(f"TÍTULO:\n{title}")
        if script:
            parts.append(f"ROTEIRO/NARRAÇÃO:\n{script}")
        if post:
            parts.append(f"TEXTO DO POST COM HASHTAGS:\n{post}")
        package = "\n\n".join(parts).strip()
        if not package:
            QMessageBox.information(self, "Nada para copiar", "Gere ou escreva o roteiro/texto antes de copiar.")
            return
        self._copy_text_to_clipboard(package, "Pacote completo copiado.")

    def _copy_text_to_clipboard(self, text: str, success_message: str) -> None:
        QApplication.clipboard().setText(str(text or ""))
        self.status_label.setText(success_message)
        QMessageBox.information(self, "Copiado", success_message)

    @staticmethod
    def _compose_tiktok_post_text(caption: str, hashtags: str) -> str:
        caption = str(caption or "").strip()
        hashtags = " ".join(str(hashtags or "").replace("\n", " ").split()).strip()
        if not caption:
            return hashtags
        if not hashtags:
            return caption
        caption_lower = caption.lower()
        tags = [tag for tag in hashtags.split() if tag.startswith("#")]
        missing = [tag for tag in tags if tag.lower() not in caption_lower]
        return f"{caption}\n\n{' '.join(missing)}".strip() if missing else caption

    @staticmethod
    def _first_sentence(text: str) -> str:
        clean = str(text or "").strip()
        if not clean:
            return ""
        for marker in (". ", "! ", "? ", "\n"):
            if marker in clean:
                return clean.split(marker, 1)[0].strip() + (marker.strip() if marker.strip() in ".!?" else "")
        return clean[:160]

    def _probe_media_duration_seconds(self, path: Path) -> float:
        if not path or not path.exists():
            return 0.0
        try:
            return float(self.service.probe_duration(path) or 0.0)
        except Exception:
            return 0.0

    def _update_metadata_json(self, clip: Dict[str, Any], updates: Dict[str, Any]) -> None:
        metadata_path = Path(str(clip.get("metadata_path") or ""))
        if not metadata_path.exists():
            output = Path(str(clip.get("output_path") or ""))
            metadata_path = output.with_suffix(".json") if output.name else metadata_path
        payload: Dict[str, Any] = {}
        if metadata_path.exists():
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
        payload.update({k: v for k, v in (updates or {}).items() if v is not None})
        if metadata_path.name:
            try:
                payload.setdefault("clip_name", clip.get("clip_name") or Path(str(clip.get("output_path") or "")).stem)
                payload.setdefault("output_path", clip.get("output_path"))
                payload.setdefault("metadata_path", str(metadata_path))
                metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning("Não foi possível atualizar JSON do clipe: %s", exc)
        if self._clip is clip or (self._clip and self._clip.get("id") == clip.get("id")):
            self._clip.update(payload)
            self._clip["metadata_json"] = payload
            if metadata_path.name:
                self._clip["metadata_path"] = str(metadata_path)

    def _reload_current_clip_metadata(self) -> None:
        if not self._clip:
            return
        metadata = self._read_clip_metadata(self._clip)
        self._clip.update({k: v for k, v in metadata.items() if v not in (None, "")})
        self._clip["metadata_json"] = metadata

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "Não foi possível abrir", str(exc))

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        index = combo.findText(text)
        if index < 0:
            combo.addItem(text)
            index = combo.findText(text)
        combo.setCurrentIndex(max(index, 0))

    # ------------------------------------------------------------------
    # Registro na biblioteca
    # ------------------------------------------------------------------
    def _register_final_clip(self, output_path: Path, metadata: Dict[str, Any]) -> Optional[int]:
        clip = self._clip or {}
        if not output_path.exists():
            return None
        if not hasattr(self.repository, "save_exported_clip"):
            return None
        existing = self._find_clip_id_by_output_path(output_path)
        if existing is not None:
            return existing

        metadata_path = output_path.with_suffix(".json")
        source_metadata = self._read_clip_metadata(clip)
        payload = dict(source_metadata)
        payload.update({
            "clip_name": output_path.stem,
            "output_path": str(output_path),
            "metadata_path": str(metadata_path),
            "library_folder": clip.get("library_folder") or payload.get("library_folder") or "Sem pasta",
            "library_season": "Finais",
            "source_library_season": clip.get("source_library_season") or clip.get("library_season") or "",
            "source_episode_name": clip.get("source_episode_name") or clip.get("episode_name") or "",
            "episode_name": clip.get("episode_name") or clip.get("source_episode_name") or "",
            "duration_seconds": self._clip_duration(clip),
            "segments": self._segments_for_clip(clip),
            "description": clip.get("description") or payload.get("description") or "",
            "tags": self._append_unique_tags(self._tags_text(clip) or str(payload.get("tags") or ""), ["final", "editor", "tedvhs"]),
            "scene_type": clip.get("scene_type") or payload.get("scene_type") or "Finalizado",
            "narration_package": clip.get("narration_package") or payload.get("narration_package") or {},
            "narration_script": self._current_narration_script_text() or clip.get("narration_script") or payload.get("narration_script") or "",
            "tiktok_title": self.tiktok_title_edit.text().strip() if hasattr(self, "tiktok_title_edit") else (clip.get("tiktok_title") or payload.get("tiktok_title") or ""),
            "tiktok_caption": self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else (clip.get("tiktok_caption") or payload.get("tiktok_caption") or ""),
            "post_text": self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else (clip.get("post_text") or payload.get("post_text") or ""),
            "hashtags": self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else (clip.get("hashtags") or payload.get("hashtags") or ""),
            "subtitle_ass_path": clip.get("subtitle_ass_path") or payload.get("subtitle_ass_path") or "",
            "subtitle_path": clip.get("subtitle_path") or payload.get("subtitle_path") or "",
            "narration_audio_path": str(self._find_narration_audio_path(clip) or payload.get("narration_audio_path") or ""),
            "extra_text_items": self._current_extra_caption_entries(),
            "watermark_logo_path": str(getattr(self, "_watermark_logo_path", "") or payload.get("watermark_logo_path") or ""),
            "watermark_logo_size_percent": float(self.watermark_logo_size_spin.value()) if hasattr(self, "watermark_logo_size_spin") else payload.get("watermark_logo_size_percent", 14.0),
            "watermark_logo_opacity": float(self.watermark_logo_opacity_spin.value()) if hasattr(self, "watermark_logo_opacity_spin") else payload.get("watermark_logo_opacity", 0.78),
            "watermark_text": self.watermark_text_edit.text().strip() if hasattr(self, "watermark_text_edit") else payload.get("watermark_text", ""),
            "export_mode": "tedvhs_layered_final",
            "derived_clip": True,
            "derived_type": "final em camadas",
            "derived_from_clip_id": clip.get("id"),
            "derived_from_clip_name": clip.get("clip_name"),
            "derived_from_output_path": clip.get("output_path"),
            "created_by": "TEDVHS Studio - Editor em Camadas",
        })
        payload.update(metadata or {})
        try:
            metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Não foi possível salvar JSON final: %s", exc)

        try:
            record_id = self.repository.save_exported_clip(
                media_id=clip.get("media_id") or clip.get("source_media_id") or payload.get("source_media_id"),
                scene_id=clip.get("scene_id") or payload.get("scene_id"),
                clip_name=output_path.stem,
                output_path=str(output_path),
                metadata_path=str(metadata_path),
                library_folder=str(payload.get("library_folder") or "Sem pasta"),
                library_season="Finais",
                episode_name=str(payload.get("episode_name") or payload.get("source_episode_name") or ""),
                duration_seconds=self._clip_duration(clip),
                segments_json=json.dumps(self._segments_for_clip(clip), ensure_ascii=False),
                description=str(payload.get("description") or ""),
                tags=str(payload.get("tags") or ""),
                scene_type=str(payload.get("scene_type") or "Finalizado"),
                export_mode="tedvhs_layered_final",
            )
            return int(record_id) if record_id is not None else None
        except Exception as exc:
            logger.warning("Não foi possível registrar final na biblioteca: %s", exc, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _clear_montage_confirmed(self) -> None:
        if not self._clip:
            self.status_label.setText("Montagem já está vazia.")
            return
        answer = QMessageBox.question(
            self,
            "Limpar montagem",
            "Deseja limpar a montagem atual?\n\nOs arquivos originais, legendas e narrações salvas não serão apagados.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._reset_montage()

    def _reset_montage(self) -> None:
        self._stop_preview()
        try:
            self.player.setSource(QUrl())
        except Exception:
            pass
        self._clip = None
        self._preview_path = None
        self._preview_dirty = True
        self.clip_info_label.setText("Nenhum clipe carregado.")
        self.status_label.setText("Montagem limpa. Vá na Biblioteca de Clipes e envie outro clipe para montagem.")
        self.preview_layers_label.setText("Prévia vazia. Envie um clipe para montagem.")
        self.current_time_label.setText("00:00")
        self.total_time_label.setText("00:00")
        self.timeline_slider.setValue(0)
        self.output_name_edit.clear()
        self.narrator_script_edit.clear()
        self.anime_subtitle_status.setText("Legenda do anime: aguardando clipe.")
        self.narration_audio_status.setText("Áudio da narração: aguardando clipe.")
        self.narrator_subtitle_status.setText("Legenda do narrador será gerada automaticamente na exportação.")
        if hasattr(self, "subtitle_status_label"):
            self.subtitle_status_label.setText("Envie um clipe para a montagem para ver o status da legenda.")
        if hasattr(self, "narration_status_label"):
            self.narration_status_label.setText("Sem roteiro carregado.")
        if hasattr(self, "narration_audio_status_label"):
            self.narration_audio_status_label.setText("Status: sem áudio de narração para esta montagem.")
        for attr in ("narration_blocks_edit", "tiktok_caption_edit"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.clear()
        for attr in ("tiktok_title_edit", "narration_hashtags_edit"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.clear()
        self._clear_extra_caption_rows_silent()
        self._watermark_logo_path = ""
        if hasattr(self, "watermark_logo_label"):
            self.watermark_logo_label.setText("Logo: nenhuma")
        self.watermark_text_edit.setText("@tedvhs")
        self.anime_subtitle_check.setChecked(False)
        self.narrator_subtitle_check.setChecked(False)
        self.narration_audio_check.setChecked(False)
        self.extra_text_check.setChecked(False)
        self.watermark_check.setChecked(False)
        self.original_volume_spin.setValue(0.30)
        self.narration_volume_spin.setValue(1.00)
        self._update_tracks()

    def _mark_preview_dirty(self, reason: str = "camadas alteradas") -> None:
        if getattr(self, "_loading_clip", False):
            return
        if not self._clip:
            return
        self._preview_dirty = True
        if hasattr(self, "preview_layers_label"):
            self.preview_layers_label.setText(
                f"Prévia desatualizada ({reason}). Clique em Atualizar prévia aplicada para ver o resultado real."
            )

    def _update_tracks(self) -> None:
        anime = bool(self.anime_subtitle_check.isChecked())
        narrator_sub = bool(self.narrator_subtitle_check.isChecked())
        narration_audio = bool(self.narration_audio_check.isChecked())
        extra_entries = self._current_extra_caption_entries() if hasattr(self, "_extra_caption_rows") else []
        extra = bool(self.extra_text_check.isChecked() and extra_entries)
        watermark = bool(getattr(self, "watermark_check", None) and self.watermark_check.isChecked())
        logo_path = str(getattr(self, "_watermark_logo_path", "") or "").strip()
        dynamic = bool(getattr(self, "dynamic_narrator_subtitle_check", None) and self.dynamic_narrator_subtitle_check.isChecked())

        self._set_track_visible(self.track_video, True, "base")
        self._set_track_visible(self.track_anime_sub, anime, self.anime_subtitle_position_combo.currentText())
        narrator_detail = self.narrator_subtitle_position_combo.currentText()
        if dynamic:
            narrator_detail += " • dinâmica REAL OK" if self._clip and self._find_narration_sync_path(self._clip) else " • dinâmica sem sync real"
        self._set_track_visible(self.track_narrator_sub, narrator_sub, narrator_detail)
        self._set_track_visible(self.track_narration_audio, narration_audio, f"vol {self.narration_volume_spin.value():.2f}x")
        if extra_entries:
            first = extra_entries[0]
            extra_detail = f"{len(extra_entries)} trecho(s) • {first.get('start_time')}–{first.get('end_time')}"
        else:
            extra_detail = "sem trechos"
        self._set_track_visible(self.track_extra_text, extra, extra_detail)
        if hasattr(self, "track_watermark"):
            watermark_detail = self.watermark_position_combo.currentText() if hasattr(self, "watermark_position_combo") else ""
            if logo_path:
                watermark_detail += " • logo"
            self._set_track_visible(self.track_watermark, watermark, watermark_detail.strip())

        if hasattr(self, "extra_text_status"):
            if extra_entries:
                self.extra_text_status.setText(f"{len(extra_entries)} legenda(s) extra(s) adicionada(s) na timeline.")
            else:
                self.extra_text_status.setText("Nenhuma legenda extra adicionada.")

        active = []
        if anime:
            active.append(f"legenda anime ({self.anime_subtitle_position_combo.currentText()})")
        if narrator_sub:
            label = f"legenda narrador ({self.narrator_subtitle_position_combo.currentText()})"
            if dynamic:
                label += " dinâmica REAL OK" if self._clip and self._find_narration_sync_path(self._clip) else " dinâmica sem sync real"
            active.append(label)
        if narration_audio:
            active.append(f"narração áudio {self.narration_volume_spin.value():.2f}x")
        if extra:
            active.append(f"{len(extra_entries)} legenda(s) extra(s)")
        if watermark and hasattr(self, "watermark_text_edit") and self.watermark_text_edit.text().strip():
            active.append(f"marca d'água {self.watermark_text_edit.text().strip()}")
        if watermark and logo_path:
            active.append("logo do canal")
        summary = ", ".join(active) if active else "nenhuma camada extra"
        if hasattr(self, "preview_layers_label") and not getattr(self, "_preview_dirty", True):
            self.preview_layers_label.setText("Prévia aplicada atualizada. Camadas ativas: " + summary + ".")
        elif hasattr(self, "preview_layers_label") and self._clip:
            self.preview_layers_label.setText("Prévia desatualizada. Camadas ativas para renderizar: " + summary + ". Clique em Atualizar prévia aplicada.")
        self._sync_preview_audio()
        self._mark_preview_dirty("camadas alteradas")

    def _set_track_visible(self, widget: QWidget, enabled: bool, detail: str = "") -> None:
        bar = getattr(widget, "_bar", None)
        if bar is not None:
            base_style = getattr(widget, "_bar_base_style", "")
            if not base_style:
                base_style = bar.styleSheet()
                setattr(widget, "_bar_base_style", base_style)
            if enabled:
                bar.setText(f"  ativo {('• ' + detail) if detail else ''}")
                bar.setStyleSheet(base_style)
            else:
                bar.setText("  desativado")
                bar.setStyleSheet(base_style + " background: #2a3038; color: #8f9aab; border: 1px dashed #56606f;")
        widget.setVisible(True)
        widget.setEnabled(True)

    def _sync_preview_audio(self) -> None:
        try:
            # Preview base toca apenas o áudio original. A prévia aplicada renderizada já inclui narração/mixagem.
            self.audio_output.setVolume(max(0.0, min(float(self.original_volume_spin.value()), 1.0)))
        except Exception:
            pass

    def _find_anime_subtitle_path(self, clip: Dict[str, Any]) -> Optional[Path]:
        candidates: List[Any] = []
        metadata = self._read_clip_metadata(clip)
        subtitles = metadata.get("subtitles_ptbr") if isinstance(metadata.get("subtitles_ptbr"), dict) else {}
        candidates.extend([
            clip.get("subtitle_ass_path"), clip.get("ass_path"), clip.get("subtitle_path"),
            clip.get("subtitle_srt_path"), clip.get("srt_path"),
            metadata.get("subtitle_ass_path"), metadata.get("ass_path"), metadata.get("subtitle_path"),
            metadata.get("subtitle_srt_path"), metadata.get("srt_path"),
            subtitles.get("ass_path") if isinstance(subtitles, dict) else None,
            subtitles.get("srt_path") if isinstance(subtitles, dict) else None,
        ])
        output_path = Path(str(clip.get("output_path") or ""))
        if output_path.name:
            candidates.extend([
                output_path.with_name(f"{output_path.stem}.pt-BR.ass"),
                output_path.with_name(f"{output_path.stem}.ass"),
                output_path.with_name(f"{output_path.stem}.pt-BR.srt"),
                output_path.with_name(f"{output_path.stem}.srt"),
            ])
        # Preferir ASS quando estiver limpo; se não, o serviço converte/limpa SRT/VTT.
        fallback: Optional[Path] = None
        for value in candidates:
            if not value:
                continue
            path = Path(str(value))
            if not path.exists() or path.suffix.lower() not in {".ass", ".srt", ".vtt"}:
                continue
            if path.suffix.lower() == ".ass":
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                    if "-->" not in raw:
                        return path
                    # ASS contaminado por SRT: segura como fallback e continua procurando SRT irmão.
                    fallback = path
                    sibling = path.with_suffix(".srt")
                    if sibling.exists():
                        return sibling
                except Exception:
                    fallback = path
            else:
                return path
        return fallback

    def _find_narration_audio_path(self, clip: Dict[str, Any]) -> Optional[Path]:
        metadata = self._read_clip_metadata(clip)
        candidates = [
            clip.get("narration_audio_path"), clip.get("audio_narration_path"),
            metadata.get("narration_audio_path"), metadata.get("audio_narration_path"),
        ]
        output_path = Path(str(clip.get("output_path") or ""))
        if output_path.name:
            candidates.extend([
                output_path.with_name(f"{output_path.stem} narração.mp3"),
                output_path.with_name(f"{output_path.stem}.narracao.mp3"),
                output_path.with_name(f"{output_path.stem} narracao.mp3"),
            ])
        for value in candidates:
            if not value:
                continue
            path = Path(str(value))
            if path.exists():
                return path
        return None

    def _find_narration_sync_path(self, clip: Dict[str, Any]) -> Optional[Path]:
        metadata = self._read_clip_metadata(clip)
        candidates = [
            clip.get("narration_sync_path"),
            metadata.get("narration_sync_path"),
        ]
        audio = self._find_narration_audio_path(clip)
        if audio:
            candidates.append(Path(audio).with_suffix(".sync.json"))
        for value in candidates:
            if not value:
                continue
            path = Path(str(value))
            if path.exists() and path.suffix.lower() == ".json" and self._is_real_narration_sync(path):
                return path
        return None

    def _is_real_narration_sync(self, path: Path) -> bool:
        """Aceita somente sync real por palavra. Sync estimado antigo é ignorado."""
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict) or payload.get("estimated"):
            return False
        words = payload.get("words")
        if not isinstance(words, list) or len(words) < 3:
            return False
        valid = 0
        last_start = -1.0
        for item in words:
            if not isinstance(item, dict):
                continue
            word = str(item.get("word") or item.get("text") or "").strip()
            if not word:
                continue
            try:
                start = float(item.get("start") or 0.0)
                end = float(item.get("end") or start + float(item.get("duration") or 0.0))
            except Exception:
                continue
            if end > start and start >= last_start - 0.05:
                valid += 1
                last_start = start
        return valid >= 3

    def _narration_script_for_clip(self, clip: Dict[str, Any]) -> str:
        metadata = self._read_clip_metadata(clip)
        package = metadata.get("narration_package") if isinstance(metadata.get("narration_package"), dict) else {}
        if not package and isinstance(clip.get("narration_package"), dict):
            package = clip.get("narration_package") or {}
        return str(
            package.get("roteiro_narracao")
            or clip.get("narration_script")
            or metadata.get("narration_script")
            or ""
        ).strip()

    def _duration_for_narrator_subtitle(self, clip: Dict[str, Any]) -> float:
        mode = "vídeo inteiro"
        if hasattr(self, "narrator_subtitle_duration_combo"):
            mode = self.narrator_subtitle_duration_combo.currentText().lower()
        if "narra" in mode or "audio" in mode or "áudio" in mode or "seguir" in mode:
            audio = self._find_narration_audio_path(clip)
            if audio:
                audio_duration = self.service.probe_duration(audio)
                if audio_duration > 0:
                    return audio_duration
        # Padrão TEDVHS: quando não há MP3, distribui pelo clipe inteiro.
        return self._clip_duration(clip)

    def _clip_duration(self, clip: Dict[str, Any]) -> float:
        value = clip.get("duration_seconds")
        try:
            number = float(value or 0.0)
            if number > 0:
                return number
        except Exception:
            pass
        output = Path(str(clip.get("output_path") or ""))
        return self.service.probe_duration(output)

    def _segments_for_clip(self, clip: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = clip.get("segments") or clip.get("segments_json")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw or "[]")
            except Exception:
                parsed = []
        elif isinstance(raw, list):
            parsed = raw
        else:
            parsed = []
        return [item for item in parsed if isinstance(item, dict)]

    def _read_clip_metadata(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(clip.get("metadata_json"), dict):
            return dict(clip.get("metadata_json") or {})
        metadata_path = Path(str(clip.get("metadata_path") or ""))
        if metadata_path.exists():
            try:
                return json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _find_clip_id_by_output_path(self, output_path: Path) -> Optional[int]:
        target = str(output_path.resolve()).lower()
        try:
            candidates = self.repository.get_exported_clips_all() if hasattr(self.repository, "get_exported_clips_all") else []
        except Exception:
            candidates = []
        for clip in candidates or []:
            try:
                candidate = Path(str(clip.get("output_path") or "")).resolve()
            except Exception:
                continue
            if str(candidate).lower() == target and clip.get("id") is not None:
                return int(clip.get("id"))
        return None

    def _open_clip_folder(self) -> None:
        clip = self._clip
        if not clip:
            return
        path = Path(str(clip.get("output_path") or ""))
        folder = path.parent if path.exists() else path
        if folder.exists():
            try:
                import os
                os.startfile(str(folder))  # type: ignore[attr-defined]
            except Exception as exc:
                QMessageBox.warning(self, "Abrir pasta", str(exc))

    @staticmethod
    def _tags_text(clip: Dict[str, Any]) -> str:
        tags = clip.get("tags")
        if isinstance(tags, list):
            return ", ".join(str(tag) for tag in tags)
        return str(tags or "")

    @staticmethod
    def _append_unique_tags(current: str, additions: List[str]) -> str:
        values: List[str] = []
        for raw in str(current or "").replace(";", ",").split(","):
            tag = raw.strip()
            if tag and tag.lower() not in {item.lower() for item in values}:
                values.append(tag)
        for raw in additions:
            tag = str(raw or "").strip()
            if tag and tag.lower() not in {item.lower() for item in values}:
                values.append(tag)
        return ", ".join(values)

    @staticmethod
    def _safe_output_stem(value: str) -> str:
        return LayeredEditorService.sanitize_name(value)

    @staticmethod
    def _time_to_seconds(value: str) -> float:
        text = str(value or "").strip().replace(",", ".")
        if not text:
            return 0.0
        try:
            if ":" not in text:
                return max(0.0, float(text))
            parts = [float(part or 0) for part in text.split(":")]
            if len(parts) == 3:
                hours, minutes, seconds = parts
            elif len(parts) == 2:
                hours = 0.0
                minutes, seconds = parts
            else:
                return max(0.0, float(parts[0]))
            return max(0.0, hours * 3600 + minutes * 60 + seconds)
        except Exception:
            return 0.0

    @staticmethod
    def _format_timecode(seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        sec = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        minutes = int(seconds // 60)
        sec = int(seconds % 60)
        return f"{minutes:02d}:{sec:02d}"

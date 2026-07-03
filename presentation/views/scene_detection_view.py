"""Aba de detecção e catalogação visual de cenas."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QTimer, Qt, QUrl
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
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository


logger = logging.getLogger(__name__)


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
        self._media_by_combo_index: dict[int, object] = {}
        self._scenes_by_row: dict[int, Dict[str, Any]] = {}
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
            "Detecte cenas, gere miniaturas, visualize o trecho, ajuste cortes e catalogue descrições/tags. "
            "Arraste as divisórias para aumentar lista, player ou catálogo."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #cccccc;")
        root_layout.addWidget(subtitle)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        top_layout.addWidget(QLabel("Episódio:"))
        self.media_combo = QComboBox()
        self.media_combo.currentIndexChanged.connect(self._on_media_changed)
        top_layout.addWidget(self.media_combo, stretch=1)

        self.refresh_btn = QPushButton("Atualizar episódios")
        self.refresh_btn.clicked.connect(self._load_media_options)
        top_layout.addWidget(self.refresh_btn)
        root_layout.addLayout(top_layout)

        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(8)
        settings_layout.addWidget(QLabel("Sensibilidade:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.05, 0.95)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(0.35)
        self.threshold_spin.setToolTip("Menor = mais cortes. Maior = menos cortes.")
        settings_layout.addWidget(self.threshold_spin)

        settings_layout.addWidget(QLabel("Cena mínima (s):"))
        self.min_scene_spin = QDoubleSpinBox()
        self.min_scene_spin.setRange(0.0, 60.0)
        self.min_scene_spin.setSingleStep(0.5)
        self.min_scene_spin.setDecimals(1)
        self.min_scene_spin.setValue(2.0)
        settings_layout.addWidget(self.min_scene_spin)

        self.detect_btn = QPushButton("Detectar + Catalogar")
        self.detect_btn.clicked.connect(self._on_detect_clicked)
        settings_layout.addWidget(self.detect_btn)

        self.clear_btn = QPushButton("Limpar cenas deste episódio")
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
        self.join_preview_btn.setToolTip("Cria um único item rascunho na lista, juntando as cenas selecionadas. Exportação em MP4 vem na Sprint 3.2.")
        self.join_preview_btn.clicked.connect(self._play_selected_scenes_joined)
        controls_layout.addWidget(self.join_preview_btn)

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
        self.scene_info_label.setStyleSheet("font-weight: bold;")
        outer_layout.addWidget(self.scene_info_label)

        self.catalog_splitter = QSplitter(Qt.Vertical)
        self.catalog_splitter.setChildrenCollapsible(False)

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
        self.description_edit.setMinimumHeight(220)
        self.description_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        description_layout.addWidget(self.description_edit, stretch=1)
        self.catalog_splitter.addWidget(description_panel)

        self.catalog_splitter.setStretchFactor(0, 1)
        self.catalog_splitter.setStretchFactor(1, 4)
        self.catalog_splitter.setSizes([120, 420])
        outer_layout.addWidget(self.catalog_splitter, stretch=1)

        catalog_actions = QHBoxLayout()
        self.save_catalog_btn = QPushButton("Salvar descrição/tags")
        self.save_catalog_btn.clicked.connect(self._save_scene_catalog)
        catalog_actions.addWidget(self.save_catalog_btn)
        catalog_actions.addStretch()
        outer_layout.addLayout(catalog_actions)

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

        self.create_clip_btn = QPushButton("Criar clipe (Sprint 3.2)")
        self.create_clip_btn.setEnabled(False)
        self.create_clip_btn.setToolTip("A geração de .mp4 entra na próxima sprint.")
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
            "Nesta sprint, a descrição é uma análise local simples por frames. "
            "IA multimodal entra depois para entender melhor a cena, áudio e contexto."
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
        current_media_id = self._selected_media_id()
        self.media_combo.blockSignals(True)
        self.media_combo.clear()
        self._media_by_combo_index.clear()

        try:
            media_files = self.repository.find_all(limit=5000, order_by="name_natural", descending=False)
        except Exception as exc:
            logger.error("Erro ao carregar mídias para detecção: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar episódios: {exc}")
            media_files = []

        if not media_files:
            self.media_combo.addItem("Nenhum episódio importado")
            self.detect_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
        else:
            self.detect_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            selected_index = 0
            for index, media in enumerate(media_files):
                folder = media.custom_metadata.get("library_folder", "Sem pasta")
                season = media.custom_metadata.get("library_season", "Sem temporada")
                label = f"{folder} / {season} / {media.file_info.file_name}"
                self.media_combo.addItem(label)
                self._media_by_combo_index[index] = media
                if current_media_id and media.id and str(media.id) == str(current_media_id):
                    selected_index = index
            self.media_combo.setCurrentIndex(selected_index)

        self.media_combo.blockSignals(False)
        self._load_scenes_for_selected_media()

    def _selected_media_obj(self):
        return self._media_by_combo_index.get(self.media_combo.currentIndex())

    def _selected_media_id(self) -> Optional[object]:
        media = self._selected_media_obj()
        return media.id if media else None

    def _on_media_changed(self, index: int) -> None:
        self._stop_preview()
        self._load_scenes_for_selected_media()

    def _on_detect_clicked(self) -> None:
        media = self._selected_media_obj()
        if not media:
            QMessageBox.information(self, "Detecção de Cenas", "Selecione um episódio válido.")
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
                "Detectar novamente vai substituir a lista atual, miniaturas e descrições. Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.detect_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.status_label.setText("Detectando cenas... isso pode levar alguns minutos em episódios longos.")

        try:
            scenes = self.scene_detector.detect_scenes(
                file_path=file_path,
                duration_seconds=media.video_info.duration.seconds if media.video_info.duration else 0.0,
                threshold=self.threshold_spin.value(),
                min_scene_seconds=self.min_scene_spin.value(),
                progress_callback=self.status_label.setText,
            )
            scenes = self.scene_detector.enrich_scenes_with_visual_catalog(
                file_path=file_path,
                media_id=media.id,
                scenes=scenes,
                output_root=Path("data") / "scene_assets",
                frames_per_scene=5,
                progress_callback=self.status_label.setText,
            )
            saved = self.repository.save_detected_scenes(media.id, scenes, self.threshold_spin.value())
            self.status_label.setText(f"Detecção concluída: {saved} cena(s) salva(s) com miniatura e descrição inicial.")
            self._load_scenes_for_selected_media()
            QMessageBox.information(self, "Detecção concluída", f"{saved} cena(s) detectada(s), catalogada(s) e salva(s).")
        except Exception as exc:
            logger.error("Erro ao detectar cenas: %s", exc, exc_info=True)
            self.status_label.setText(f"Erro ao detectar cenas: {exc}")
            QMessageBox.critical(self, "Erro ao detectar cenas", str(exc))
        finally:
            self.detect_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)

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
            "manual_edit": "editada manualmente",
            "pending": "pendente",
            "error": "erro",
        }
        return mapping.get(value, value)

    def _format_time(self, seconds: object) -> str:
        seconds = float(seconds or 0.0)
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

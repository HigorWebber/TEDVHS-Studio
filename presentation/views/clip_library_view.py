"""Biblioteca de clipes exportados do TEDVHS Studio."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QUrl, QCoreApplication
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ClipLibraryView(QWidget):
    """Aba para visualizar, pré-visualizar e organizar clipes exportados."""

    def __init__(self, repository: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self._all_clips: List[Dict[str, Any]] = []
        self._clips_by_row: Dict[int, Dict[str, Any]] = {}
        self._selected_clip: Optional[Dict[str, Any]] = None
        self._is_slider_pressed = False
        self._setup_ui()
        self.refresh_clips()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        title = QLabel("🎞️ Biblioteca de Clipes")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title)

        subtitle = QLabel(
            "Veja os clipes exportados, filtre por anime/tipo/tag, reproduza a prévia e gerencie os arquivos finais."
        )
        subtitle.setWordWrap(True)
        main_layout.addWidget(subtitle)

        filters_layout = QHBoxLayout()
        filters_layout.addWidget(QLabel("Anime/Pasta:"))
        self.folder_filter = QComboBox()
        self.folder_filter.currentIndexChanged.connect(self._apply_filters)
        filters_layout.addWidget(self.folder_filter, 1)

        filters_layout.addWidget(QLabel("Tipo:"))
        self.type_filter = QComboBox()
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        filters_layout.addWidget(self.type_filter, 1)

        filters_layout.addWidget(QLabel("Buscar:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Nome, tags, descrição ou episódio...")
        self.search_input.textChanged.connect(self._apply_filters)
        filters_layout.addWidget(self.search_input, 2)

        self.refresh_btn = QPushButton("Atualizar clipes")
        self.refresh_btn.clicked.connect(self.refresh_clips)
        filters_layout.addWidget(self.refresh_btn)
        main_layout.addLayout(filters_layout)

        self.status_label = QLabel("Carregando clipes...")
        main_layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter, 1)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels([
            "Nome", "Anime", "Temporada", "Episódio origem", "Início", "Fim",
            "Duração", "Tipo", "Tags", "Criado em", "Arquivo"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._toggle_play_pause())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.table.setMinimumWidth(520)
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(3, 170)
        self.table.setColumnWidth(4, 90)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 90)
        self.table.setColumnWidth(7, 130)
        self.table.setColumnWidth(8, 210)
        self.table.setColumnWidth(9, 150)
        self.table.setColumnWidth(10, 420)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        right_widget = QWidget()
        right_widget.setMinimumWidth(540)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 8, 0)

        preview_group = QGroupBox("Preview do clipe")
        preview_layout = QVBoxLayout(preview_group)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(260)
        self.video_widget.setMaximumHeight(420)
        self.video_widget.setStyleSheet("background: black;")
        preview_layout.addWidget(self.video_widget, 1)

        timeline_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00:00.000")
        timeline_layout.addWidget(self.current_time_label)
        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.setRange(0, 0)
        self.timeline_slider.sliderPressed.connect(self._on_slider_pressed)
        self.timeline_slider.sliderReleased.connect(self._on_slider_released)
        self.timeline_slider.sliderMoved.connect(self._on_slider_moved)
        timeline_layout.addWidget(self.timeline_slider, 1)
        self.total_time_label = QLabel("00:00:00.000")
        timeline_layout.addWidget(self.total_time_label)
        preview_layout.addLayout(timeline_layout)

        controls_layout = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play_pause)
        controls_layout.addWidget(self.play_btn)
        self.stop_btn = QPushButton("■ Parar")
        self.stop_btn.clicked.connect(self._stop_preview)
        controls_layout.addWidget(self.stop_btn)
        self.open_file_btn = QPushButton("Abrir arquivo")
        self.open_file_btn.clicked.connect(self._open_selected_file)
        controls_layout.addWidget(self.open_file_btn)
        self.open_folder_btn = QPushButton("Abrir pasta")
        self.open_folder_btn.clicked.connect(self._open_selected_folder)
        controls_layout.addWidget(self.open_folder_btn)
        controls_layout.addStretch(1)
        preview_layout.addLayout(controls_layout)
        right_layout.addWidget(preview_group, 2)

        info_group = QGroupBox("Informações do clipe")
        info_layout = QVBoxLayout(info_group)
        self.info_label = QLabel("Selecione um clipe para ver os detalhes.")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(self.info_label)
        info_layout.addWidget(QLabel("Descrição:"))
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText("Descrição do clipe exportado...")
        self.description_edit.setMinimumHeight(130)
        info_layout.addWidget(self.description_edit)
        info_layout.addWidget(QLabel("Tags:"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Ex.: luta, tensão, diálogo")
        info_layout.addWidget(self.tags_edit)
        self.save_metadata_btn = QPushButton("Salvar descrição/tags")
        self.save_metadata_btn.clicked.connect(self._save_clip_metadata)
        info_layout.addWidget(self.save_metadata_btn)
        right_layout.addWidget(info_group, 1)

        danger_layout = QHBoxLayout()
        self.rename_btn = QPushButton("Renomear clipe")
        self.rename_btn.clicked.connect(self._rename_selected_clip)
        danger_layout.addWidget(self.rename_btn)
        self.delete_btn = QPushButton("Excluir clipe")
        self.delete_btn.clicked.connect(self._delete_selected_clips)
        danger_layout.addWidget(self.delete_btn)
        right_layout.addLayout(danger_layout)

        right_scroll.setWidget(right_widget)
        splitter.addWidget(right_scroll)
        splitter.setSizes([720, 620])

        self.audio_output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

    def refresh_clips(self) -> None:
        """Recarregar clipes exportados do banco."""
        try:
            if hasattr(self.repository, "get_exported_clips_all"):
                clips = self.repository.get_exported_clips_all()
            else:
                clips = []
            self._all_clips = [self._hydrate_clip_metadata(clip) for clip in clips]
            self._refresh_filter_options()
            self._apply_filters()
        except Exception as exc:
            logger.error("Erro ao carregar clipes exportados: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar clipes exportados:\n{exc}")

    def _hydrate_clip_metadata(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        """Complementar registro do banco com dados do JSON lateral, se existir."""
        data = dict(clip)
        metadata_path = Path(str(data.get("metadata_path") or ""))
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as file:
                    payload = json.load(file)
                for key in (
                    "source_library_season", "source_episode_name", "source_file",
                    "description", "tags", "scene_type", "segments", "export_mode"
                ):
                    if payload.get(key) and not data.get(key):
                        data[key] = payload.get(key)
                data["metadata_json"] = payload
            except Exception as exc:
                logger.warning("Não foi possível ler JSON do clipe %s: %s", metadata_path, exc)
        return data

    def _refresh_filter_options(self) -> None:
        current_folder = self.folder_filter.currentText()
        current_type = self.type_filter.currentText()
        folders = sorted({str(c.get("library_folder") or "Sem pasta") for c in self._all_clips})
        types = sorted({str(c.get("scene_type") or "Geral") for c in self._all_clips})
        self.folder_filter.blockSignals(True)
        self.type_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem("Todos")
        self.folder_filter.addItems(folders)
        self.type_filter.clear()
        self.type_filter.addItem("Todos")
        self.type_filter.addItems(types)
        if current_folder:
            idx = self.folder_filter.findText(current_folder)
            if idx >= 0:
                self.folder_filter.setCurrentIndex(idx)
        if current_type:
            idx = self.type_filter.findText(current_type)
            if idx >= 0:
                self.type_filter.setCurrentIndex(idx)
        self.folder_filter.blockSignals(False)
        self.type_filter.blockSignals(False)

    def _apply_filters(self) -> None:
        folder = self.folder_filter.currentText() if self.folder_filter.count() else "Todos"
        scene_type = self.type_filter.currentText() if self.type_filter.count() else "Todos"
        query = self.search_input.text().strip().lower()
        rows = []
        for clip in self._all_clips:
            if folder != "Todos" and str(clip.get("library_folder") or "Sem pasta") != folder:
                continue
            if scene_type != "Todos" and str(clip.get("scene_type") or "Geral") != scene_type:
                continue
            haystack = " ".join([
                str(clip.get("clip_name") or ""),
                str(clip.get("library_folder") or ""),
                str(clip.get("episode_name") or ""),
                str(clip.get("source_episode_name") or ""),
                str(clip.get("tags") or ""),
                str(clip.get("description") or ""),
                str(clip.get("scene_type") or ""),
            ]).lower()
            if query and query not in haystack:
                continue
            rows.append(clip)
        self._populate_table(rows)

    def _populate_table(self, clips: List[Dict[str, Any]]) -> None:
        self.table.setRowCount(len(clips))
        self._clips_by_row.clear()
        for row, clip in enumerate(clips):
            self._clips_by_row[row] = clip
            season = self._season_text(clip)
            episode = self._episode_text(clip)
            start_text, end_text = self._segment_bounds_text(clip)
            values = [
                str(clip.get("clip_name") or "Sem nome"),
                str(clip.get("library_folder") or "Sem pasta"),
                season,
                episode,
                start_text,
                end_text,
                self._format_time(float(clip.get("duration_seconds") or 0.0)),
                str(clip.get("scene_type") or "Geral"),
                self._tags_text(clip),
                str(clip.get("created_at") or ""),
                str(clip.get("output_path") or ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
        self.status_label.setText(f"Total: {len(clips)} clipe(s) exportado(s)")

    def _season_text(self, clip: Dict[str, Any]) -> str:
        return str(clip.get("source_library_season") or clip.get("library_season") or "Sem temporada")

    def _episode_text(self, clip: Dict[str, Any]) -> str:
        return str(clip.get("source_episode_name") or clip.get("episode_name") or "Sem episódio")

    def _origin_text(self, clip: Dict[str, Any]) -> str:
        return f"{self._season_text(clip)} / {self._episode_text(clip)}"

    def _segments_for_clip(self, clip: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw = clip.get("segments")
        if not raw:
            raw = clip.get("segments_json")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw or "[]")
            except Exception:
                parsed = []
        elif isinstance(raw, list):
            parsed = raw
        else:
            parsed = []
        return [segment for segment in parsed if isinstance(segment, dict)]

    def _segment_bounds_text(self, clip: Dict[str, Any]) -> tuple[str, str]:
        segments = self._segments_for_clip(clip)
        if not segments:
            return "", ""
        try:
            start = float(segments[0].get("start_seconds") or 0.0)
            end = float(segments[-1].get("end_seconds") or 0.0)
            return self._format_time(start), self._format_time(end)
        except Exception:
            return "", ""

    def _tags_text(self, clip: Dict[str, Any]) -> str:
        tags = clip.get("tags")
        if isinstance(tags, list):
            return ", ".join(str(t) for t in tags)
        return str(tags or "")

    def _on_selection_changed(self) -> None:
        selected = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not selected:
            return
        row = selected[0].row()
        clip = self._clips_by_row.get(row)
        if clip:
            self._load_clip(clip)

    def _load_clip(self, clip: Dict[str, Any]) -> None:
        self._selected_clip = clip
        self._stop_preview(clear_source=False)
        output_path = Path(str(clip.get("output_path") or ""))
        if output_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(output_path)))
        else:
            self.player.setSource(QUrl())
        self.description_edit.setPlainText(str(clip.get("description") or ""))
        self.tags_edit.setText(self._tags_text(clip))
        start_text, end_text = self._segment_bounds_text(clip)
        segments = self._segments_for_clip(clip)
        segment_count = len(segments)
        self.info_label.setText(
            f"Nome: {clip.get('clip_name') or 'Sem nome'}\n"
            f"Anime/Pasta: {clip.get('library_folder') or 'Sem pasta'}\n"
            f"Temporada de origem: {self._season_text(clip)}\n"
            f"Episódio de origem: {self._episode_text(clip)}\n"
            f"Início/Fim na origem: {start_text or '-'} → {end_text or '-'}\n"
            f"Segmentos usados: {segment_count}\n"
            f"Duração exportada: {self._format_time(float(clip.get('duration_seconds') or 0.0))}\n"
            f"Tipo: {clip.get('scene_type') or 'Geral'}\n"
            f"Arquivo: {clip.get('output_path') or ''}"
        )
        self.current_time_label.setText("00:00:00.000")
        self.total_time_label.setText(self._format_time(float(clip.get("duration_seconds") or 0.0)))
        self.timeline_slider.setValue(0)
        self.play_btn.setText("▶ Play")

    def _toggle_play_pause(self) -> None:
        if not self._selected_clip:
            return
        output_path = Path(str(self._selected_clip.get("output_path") or ""))
        if not output_path.exists():
            QMessageBox.warning(self, "Arquivo não encontrado", f"O clipe não foi encontrado:\n{output_path}")
            return
        if self.player.source().isEmpty():
            self.player.setSource(QUrl.fromLocalFile(str(output_path)))
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _stop_preview(self, clear_source: bool = False) -> None:
        self.player.stop()
        if clear_source:
            self.player.setSource(QUrl())
        self.play_btn.setText("▶ Play")

    def _on_position_changed(self, position: int) -> None:
        if not self._is_slider_pressed:
            self.timeline_slider.setValue(position)
        self.current_time_label.setText(self._format_time(position / 1000.0))

    def _on_duration_changed(self, duration: int) -> None:
        self.timeline_slider.setRange(0, max(duration, 0))
        self.total_time_label.setText(self._format_time(duration / 1000.0))

    def _on_playback_state_changed(self, _state) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.play_btn.setText("⏸ Pausar")
        else:
            self.play_btn.setText("▶ Play")

    def _on_slider_pressed(self) -> None:
        self._is_slider_pressed = True

    def _on_slider_released(self) -> None:
        self._is_slider_pressed = False
        self.player.setPosition(self.timeline_slider.value())

    def _on_slider_moved(self, value: int) -> None:
        self.current_time_label.setText(self._format_time(value / 1000.0))

    def _save_clip_metadata(self) -> None:
        clip = self._selected_clip
        if not clip:
            return
        description = self.description_edit.toPlainText().strip()
        tags = self.tags_edit.text().strip()
        try:
            self.repository.update_exported_clip(
                int(clip["id"]),
                description=description,
                tags=tags,
            )
            self._update_metadata_json(clip, {"description": description, "tags": tags})
            self.status_label.setText("Descrição/tags salvas.")
            self.refresh_clips()
            self._select_clip_by_id(int(clip["id"]))
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))

    def _rename_selected_clip(self) -> None:
        clip = self._selected_clip
        if not clip:
            return
        old_path = Path(str(clip.get("output_path") or ""))
        old_name = str(clip.get("clip_name") or old_path.stem or "clipe")
        new_name, ok = QInputDialog.getText(self, "Renomear clipe", "Novo nome do clipe:", text=old_name)
        if not ok:
            return
        new_name = self._sanitize_name(new_name or old_name)
        if not new_name:
            return
        try:
            self._release_player_file_handles()
            new_path = old_path.with_name(f"{new_name}{old_path.suffix or '.mp4'}")
            new_path = self._unique_path(new_path)
            new_json_path = new_path.with_suffix(".json")
            old_json = Path(str(clip.get("metadata_path") or old_path.with_suffix(".json")))
            if old_path.exists():
                old_path.rename(new_path)
            if old_json.exists():
                old_json.rename(new_json_path)
            self.repository.update_exported_clip(
                int(clip["id"]),
                clip_name=new_path.stem,
                output_path=str(new_path),
                metadata_path=str(new_json_path),
            )
            self._update_metadata_json({**clip, "metadata_path": str(new_json_path)}, {"clip_name": new_path.stem, "output_path": str(new_path)})
            self.refresh_clips()
            self._select_clip_by_id(int(clip["id"]))
            self.status_label.setText(f"Clipe renomeado: {new_path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao renomear", str(exc))

    def _delete_selected_clips(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        clips = [self._clips_by_row[row.row()] for row in rows if row.row() in self._clips_by_row]
        if not clips and self._selected_clip:
            clips = [self._selected_clip]
        if not clips:
            return
        reply = QMessageBox.warning(
            self,
            "Excluir clipe exportado?",
            f"Você está prestes a excluir {len(clips)} clipe(s) exportado(s).\n\n"
            "Isso remove o arquivo MP4 e o JSON de metadados da pasta TEDVHS_Exports.\n"
            "O episódio original NÃO será apagado.\n\n"
            "Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._release_player_file_handles()
        removed = 0
        for clip in clips:
            try:
                output_path = Path(str(clip.get("output_path") or ""))
                metadata_path = Path(str(clip.get("metadata_path") or output_path.with_suffix(".json")))
                if output_path.exists():
                    output_path.unlink()
                if metadata_path.exists():
                    metadata_path.unlink()
                self.repository.delete_exported_clip(int(clip["id"]))
                removed += 1
            except Exception as exc:
                logger.error("Erro ao excluir clipe: %s", exc, exc_info=True)
        self._selected_clip = None
        self._stop_preview(clear_source=True)
        self.refresh_clips()
        self.status_label.setText(f"{removed} clipe(s) excluído(s).")

    def _show_context_menu(self, position) -> None:
        menu = QMenu(self)
        play_action = QAction("Reproduzir / Pausar", self)
        play_action.triggered.connect(self._toggle_play_pause)
        menu.addAction(play_action)
        menu.addAction("Abrir arquivo", self._open_selected_file)
        menu.addAction("Abrir pasta", self._open_selected_folder)
        menu.addSeparator()
        menu.addAction("Renomear clipe", self._rename_selected_clip)
        menu.addAction("Salvar descrição/tags", self._save_clip_metadata)
        menu.addSeparator()
        menu.addAction("Excluir clipe", self._delete_selected_clips)
        menu.addSeparator()
        menu.addAction("Atualizar lista", self.refresh_clips)
        menu.exec(self.table.viewport().mapToGlobal(position))


    def _release_player_file_handles(self) -> None:
        """Liberar o arquivo do player antes de renomear/excluir no Windows."""
        try:
            self.player.stop()
            self.player.setSource(QUrl())
            self.play_btn.setText("▶ Play")
            for _ in range(4):
                QCoreApplication.processEvents()
                time.sleep(0.03)
        except Exception:
            pass

    def _open_selected_file(self) -> None:
        clip = self._selected_clip
        if not clip:
            return
        path = Path(str(clip.get("output_path") or ""))
        if path.exists():
            self._open_path(path)

    def _open_selected_folder(self) -> None:
        clip = self._selected_clip
        if not clip:
            return
        path = Path(str(clip.get("output_path") or ""))
        if path.exists():
            self._open_path(path.parent)

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "Não foi possível abrir", str(exc))

    def _select_clip_by_id(self, clip_id: int) -> None:
        for row, clip in self._clips_by_row.items():
            if int(clip.get("id") or -1) == int(clip_id):
                self.table.selectRow(row)
                return

    def _update_metadata_json(self, clip: Dict[str, Any], updates: Dict[str, Any]) -> None:
        metadata_path = Path(str(clip.get("metadata_path") or ""))
        if not metadata_path.exists():
            return
        try:
            with open(metadata_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            payload.update(updates)
            with open(metadata_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Não foi possível atualizar JSON do clipe: %s", exc)

    @staticmethod
    def _sanitize_name(value: str) -> str:
        import re
        text = re.sub(r"[<>:\"/\\|?*]+", "-", str(value or "").strip())
        text = re.sub(r"\s+", " ", text).strip(" .")
        return text

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 1
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(float(seconds or 0.0), 0.0)
        total_ms = int(round(seconds * 1000))
        ms = total_ms % 1000
        total_seconds = total_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"

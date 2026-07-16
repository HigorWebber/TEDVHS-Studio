"""Biblioteca de clipes exportados do TEDVHS Studio."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QUrl, QCoreApplication, QObject, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QApplication,
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

from infrastructure.ai.gemini_scene_ai_service import (
    DEFAULT_GEMINI_MODEL,
    GeminiSceneAIError,
    GeminiSceneAIService,
)
from infrastructure.subtitles.hybrid_subtitle_service import (
    DEFAULT_GEMINI_SUBTITLE_MODEL,
    HybridSubtitleService,
    SubtitleGenerationError,
)
from infrastructure.ai.gemini_narration_service import (
    DEFAULT_NARRATION_MODEL,
    GeminiNarrationError,
    GeminiNarrationService,
)
from infrastructure.settings.api_settings import ApiSettingsStore


logger = logging.getLogger(__name__)


class _ClipAIWorker(QObject):
    """Worker em QThread para analisar clipes exportados com Gemini API."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, ai_service: GeminiSceneAIService, clips: List[Dict[str, Any]], api_key: str, model: str):
        super().__init__()
        self.ai_service = ai_service
        self.clips = list(clips or [])
        self.api_key = str(api_key or "").strip()
        self.model = str(model or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            results: List[Dict[str, Any]] = []
            total = len(self.clips)
            for index, clip in enumerate(self.clips, start=1):
                if self._cancel_requested:
                    raise RuntimeError("Análise de clipes cancelada pelo usuário.")
                clip_name = str(clip.get("clip_name") or "Clipe")
                self.progress.emit(f"IA do clipe: extraindo frames de {clip_name} ({index}/{total})...")
                frames = self._extract_clip_frames(clip)

                if self._cancel_requested:
                    raise RuntimeError("Análise de clipes cancelada pelo usuário.")
                self.progress.emit(f"IA do clipe: analisando {clip_name} com {self.model} ({index}/{total})...")
                ai_result = self.ai_service.describe_clip(
                    frames,
                    context=self._build_clip_context(clip),
                    api_key=self.api_key,
                    model=self.model,
                )
                results.append({
                    "id": clip.get("id"),
                    "clip_name": clip_name,
                    "description": self.ai_service.format_description(ai_result),
                    "tags": self.ai_service.normalize_tags(ai_result),
                    "scene_type": self.ai_service.normalize_scene_type(ai_result),
                    "analysis_payload": {
                        "method": "gemini_api_clip_vision_safe",
                        "model": self.model,
                        "frames": [str(frame) for frame in frames],
                        "ai_result": ai_result,
                    },
                })
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _extract_clip_frames(self, clip: Dict[str, Any]) -> List[Path]:
        output_path = Path(str(clip.get("output_path") or ""))
        if not output_path.exists():
            raise RuntimeError(f"Arquivo do clipe não encontrado: {output_path}")

        clip_id = str(clip.get("id") or self._sanitize_name(output_path.stem))
        output_root = Path("data") / "clip_ai_frames" / clip_id
        output_root.mkdir(parents=True, exist_ok=True)

        duration = float(clip.get("duration_seconds") or 0.0)
        if duration <= 0:
            sample_times = [1.0]
        elif duration <= 8:
            sample_times = [max(0.4, duration * 0.50)]
        elif duration <= 25:
            sample_times = [max(0.6, duration * 0.20), duration * 0.50, max(0.6, duration * 0.80)]
        else:
            sample_times = [max(1.0, duration * 0.15), duration * 0.50, max(1.0, duration * 0.85)]

        ffmpeg_binary = os.environ.get("FFMPEG_BINARY", "ffmpeg")
        frames: List[Path] = []
        for idx, seconds in enumerate(sample_times, start=1):
            if self._cancel_requested:
                raise RuntimeError("Análise de clipes cancelada pelo usuário.")
            seconds = max(0.0, min(float(seconds), max(duration - 0.2, 0.0))) if duration > 0 else max(0.0, float(seconds))
            frame_path = output_root / f"frame_{idx:02d}.jpg"
            cmd = [
                ffmpeg_binary,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{seconds:.3f}",
                "-i",
                str(output_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=448:-2",
                "-q:v",
                "4",
                str(frame_path),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            if completed.returncode == 0 and frame_path.exists() and frame_path.stat().st_size > 0:
                frames.append(frame_path)
        if not frames:
            raise RuntimeError("Não foi possível extrair frames do clipe para análise. Verifique FFmpeg e o arquivo MP4.")
        return frames

    def _build_clip_context(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        segments = self._segments_for_clip(clip)
        start_text, end_text = self._segment_bounds_text(segments)
        segment_lines = []
        for idx, segment in enumerate(segments[:8], start=1):
            start = self._format_time(float(segment.get("start_seconds") or 0.0))
            end = self._format_time(float(segment.get("end_seconds") or 0.0))
            segment_lines.append(f"{idx}. {start} até {end}")
        if len(segments) > 8:
            segment_lines.append(f"... e mais {len(segments) - 8} segmento(s)")

        return {
            "anime": clip.get("library_folder") or "Sem pasta",
            "season": clip.get("source_library_season") or clip.get("library_season") or "Sem temporada",
            "episode": clip.get("source_episode_name") or clip.get("episode_name") or "Sem episódio",
            "clip_name": clip.get("clip_name") or "Clipe exportado",
            "duration": self._format_time(float(clip.get("duration_seconds") or 0.0)),
            "source_range": f"{start_text or '-'} → {end_text or '-'}",
            "segments_summary": "\n".join(segment_lines) if segment_lines else "Sem segmentos detalhados",
            "scene_notes": str(clip.get("description") or "")[:900],
        }

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
        return [segment for segment in parsed if isinstance(segment, dict)]

    def _segment_bounds_text(self, segments: List[Dict[str, Any]]) -> tuple[str, str]:
        if not segments:
            return "", ""
        try:
            start = float(segments[0].get("start_seconds") or 0.0)
            end = float(segments[-1].get("end_seconds") or 0.0)
            return self._format_time(start), self._format_time(end)
        except Exception:
            return "", ""

    @staticmethod
    def _sanitize_name(value: str) -> str:
        import re
        text = re.sub(r"[<>:\"/\\|?*]+", "-", str(value or "").strip())
        text = re.sub(r"\s+", " ", text).strip(" .")
        return text or "clipe"

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


class _ClipSubtitleWorker(QObject):
    """Worker em QThread para gerar legenda PT-BR dos clipes."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        subtitle_service: HybridSubtitleService,
        clip: Dict[str, Any],
        api_key: str,
        model: str,
        action: str = "generate",
    ):
        super().__init__()
        self.subtitle_service = subtitle_service
        self.clip = dict(clip or {})
        self.api_key = str(api_key or "").strip()
        self.model = str(model or DEFAULT_GEMINI_SUBTITLE_MODEL).strip() or DEFAULT_GEMINI_SUBTITLE_MODEL
        self.action = str(action or "generate")

    def run(self) -> None:
        try:
            clip_name = str(self.clip.get("clip_name") or "Clipe")
            if self.action == "burn":
                self.progress.emit(f"Exportando MP4 legendado: {clip_name}...")
                subtitle_data = self._subtitle_data_from_clip(self.clip)
                result = self.subtitle_service.export_with_burned_subtitle(
                    self.clip,
                    ass_path=subtitle_data.get("ass_path") or None,
                )
                result.update({"id": self.clip.get("id"), "action": "burn"})
                self.finished.emit(result)
                return

            self.progress.emit(f"Gerando legenda PT-BR: {clip_name}...")
            result = self.subtitle_service.generate_ptbr_subtitle(
                self.clip,
                api_key=self.api_key,
                model=self.model,
            )
            result.update({"id": self.clip.get("id"), "action": "generate"})
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _subtitle_data_from_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = clip.get("metadata_json") if isinstance(clip.get("metadata_json"), dict) else {}
        subtitles = metadata.get("subtitles_ptbr") if isinstance(metadata.get("subtitles_ptbr"), dict) else {}
        if subtitles:
            return subtitles
        return {
            "srt_path": clip.get("subtitle_srt_path"),
            "ass_path": clip.get("subtitle_ass_path"),
        }


class _ClipNarrationWorker(QObject):
    """Worker em QThread para gerar roteiro/narração de clipe com Gemini API."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        narration_service: GeminiNarrationService,
        clip: Dict[str, Any],
        api_key: str,
        model: str,
        style: str,
        length: str,
    ):
        super().__init__()
        self.narration_service = narration_service
        self.clip = dict(clip or {})
        self.api_key = str(api_key or "").strip()
        self.model = str(model or DEFAULT_NARRATION_MODEL).strip() or DEFAULT_NARRATION_MODEL
        self.style = str(style or "Empolgado").strip() or "Empolgado"
        self.length = str(length or "Médio").strip() or "Médio"

    def run(self) -> None:
        try:
            clip_name = str(self.clip.get("clip_name") or "Clipe")
            self.progress.emit(f"Gerando roteiro de narração: {clip_name}...")
            context = self._build_context(self.clip)
            context["style"] = self.style
            context["length"] = self.length
            result = self.narration_service.generate_clip_narration(
                context=context,
                api_key=self.api_key,
                model=self.model,
            )
            self.finished.emit({
                "id": self.clip.get("id"),
                "clip_name": clip_name,
                "model": self.model,
                "style": self.style,
                "length": self.length,
                "result": result,
            })
        except Exception as exc:
            self.failed.emit(str(exc))

    def _build_context(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = self._metadata_for_clip(clip)
        subtitle_text = self._read_subtitle_text(clip, metadata)
        subtitles = metadata.get("subtitles_ptbr") if isinstance(metadata.get("subtitles_ptbr"), dict) else {}
        return {
            "anime": clip.get("library_folder") or metadata.get("library_folder") or "Anime não informado",
            "season": clip.get("source_library_season") or clip.get("library_season") or metadata.get("source_library_season") or "Temporada não informada",
            "episode": clip.get("source_episode_name") or clip.get("episode_name") or metadata.get("source_episode_name") or "Episódio não informado",
            "clip_name": clip.get("clip_name") or metadata.get("clip_name") or "Clipe exportado",
            "duration": self._format_time(float(clip.get("duration_seconds") or metadata.get("duration_seconds") or 0.0)),
            "scene_type": clip.get("scene_type") or metadata.get("scene_type") or "Geral",
            "tags": clip.get("tags") or metadata.get("tags") or "",
            "description": clip.get("description") or metadata.get("description") or "",
            "subtitle_text": subtitle_text,
            "subtitle_source": subtitles.get("source") if isinstance(subtitles, dict) else "",
            "subtitle_language": subtitles.get("source_language") if isinstance(subtitles, dict) else "",
            "segments": metadata.get("segments") or clip.get("segments") or clip.get("segments_json") or [],
        }

    def _metadata_for_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = clip.get("metadata_json") if isinstance(clip.get("metadata_json"), dict) else {}
        if metadata:
            return dict(metadata)
        metadata_path = Path(str(clip.get("metadata_path") or ""))
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                return {}
        return {}

    def _read_subtitle_text(self, clip: Dict[str, Any], metadata: Dict[str, Any]) -> str:
        candidates: List[Path] = []
        subtitles = metadata.get("subtitles_ptbr") if isinstance(metadata.get("subtitles_ptbr"), dict) else {}
        for value in (
            subtitles.get("srt_path") if isinstance(subtitles, dict) else None,
            clip.get("subtitle_srt_path"),
            metadata.get("subtitle_srt_path"),
        ):
            if value:
                candidates.append(Path(str(value)))
        output_path = Path(str(clip.get("output_path") or metadata.get("output_path") or ""))
        if output_path.name:
            candidates.append(output_path.with_name(f"{output_path.stem}.pt-BR.srt"))
        for path in candidates:
            if not path.exists() or path.stat().st_size <= 0:
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                return self._srt_to_plain_text(raw)[:5000]
            except Exception:
                continue
        return ""

    def _srt_to_plain_text(self, raw: str) -> str:
        lines: List[str] = []
        for line in str(raw or "").splitlines():
            clean = line.strip()
            if not clean:
                continue
            if clean.isdigit():
                continue
            if "-->" in clean:
                continue
            if clean.startswith("{") and clean.endswith("}"):
                continue
            lines.append(clean)
        joined = " ".join(lines)
        while "  " in joined:
            joined = joined.replace("  ", " ")
        return joined.strip()

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(float(seconds or 0.0), 0.0)
        total_seconds = int(round(seconds))
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"


class ClipLibraryView(QWidget):
    """Aba para visualizar, pré-visualizar e organizar clipes exportados."""

    def __init__(self, repository: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self._all_clips: List[Dict[str, Any]] = []
        self._clips_by_row: Dict[int, Dict[str, Any]] = {}
        self._selected_clip: Optional[Dict[str, Any]] = None
        self._is_slider_pressed = False
        self.ai_service = GeminiSceneAIService(timeout_seconds=120)
        self.subtitle_service = HybridSubtitleService(timeout_seconds=180)
        self.narration_service = GeminiNarrationService(timeout_seconds=120)
        self.api_settings = ApiSettingsStore()
        self._ai_thread: Optional[QThread] = None
        self._ai_worker: Optional[_ClipAIWorker] = None
        self._subtitle_thread: Optional[QThread] = None
        self._subtitle_worker: Optional[_ClipSubtitleWorker] = None
        self._narration_thread: Optional[QThread] = None
        self._narration_worker: Optional[_ClipNarrationWorker] = None
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
        self.description_edit.setMinimumHeight(170)
        self.description_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.description_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.description_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        info_layout.addWidget(self.description_edit)

        info_layout.addWidget(QLabel("Tipo do clipe:"))
        self.clip_type_combo = QComboBox()
        self.clip_type_combo.addItems([
            "Geral", "Ação", "Luta", "Diálogo", "Comédia", "Drama",
            "Suspense", "Romance", "Transformação", "Poder/Habilidade",
            "Revelação", "Cena épica", "Exploração", "Introdução", "Outro",
        ])
        info_layout.addWidget(self.clip_type_combo)

        info_layout.addWidget(QLabel("Tags:"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Ex.: luta, tensão, diálogo")
        info_layout.addWidget(self.tags_edit)

        metadata_actions = QHBoxLayout()
        self.save_metadata_btn = QPushButton("Salvar descrição/tags/tipo")
        self.save_metadata_btn.clicked.connect(self._save_clip_metadata)
        metadata_actions.addWidget(self.save_metadata_btn)
        metadata_actions.addStretch(1)
        info_layout.addLayout(metadata_actions)

        ai_group = QGroupBox("IA do clipe exportado")
        ai_layout = QVBoxLayout(ai_group)
        ai_help = QLabel(
            "Use Gemini API para descrever o clipe final salvo. O app envia poucos frames comprimidos do MP4, sem pesar no PC."
        )
        ai_help.setWordWrap(True)
        ai_layout.addWidget(ai_help)

        api_layout = QHBoxLayout()
        api_layout.addWidget(QLabel("API Key:"))
        saved_key = self.api_settings.get_gemini_api_key() if hasattr(self, "api_settings") else ""
        self.gemini_api_key_edit = QLineEdit(saved_key)
        self.gemini_api_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_api_key_edit.setPlaceholderText("Cole sua API Key do Gemini")
        self.gemini_api_key_edit.setToolTip("Pode salvar localmente neste PC para usar em descrições e legendas.")
        api_layout.addWidget(self.gemini_api_key_edit, 1)
        ai_layout.addLayout(api_layout)

        api_save_layout = QHBoxLayout()
        self.save_api_key_checkbox = QCheckBox("Salvar chave neste PC")
        self.save_api_key_checkbox.setChecked(bool(saved_key))
        self.save_api_key_checkbox.setToolTip("Salva em data/settings/api_settings.json. É local, mas não criptografado.")
        api_save_layout.addWidget(self.save_api_key_checkbox)
        self.save_api_key_btn = QPushButton("Salvar chave")
        self.save_api_key_btn.clicked.connect(self._save_gemini_settings_from_fields)
        api_save_layout.addWidget(self.save_api_key_btn)
        self.clear_api_key_btn = QPushButton("Apagar chave")
        self.clear_api_key_btn.clicked.connect(self._clear_saved_gemini_api_key)
        api_save_layout.addWidget(self.clear_api_key_btn)
        api_save_layout.addStretch(1)
        ai_layout.addLayout(api_save_layout)

        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("Modelo:"))
        saved_model = self.api_settings.get_gemini_model(DEFAULT_GEMINI_MODEL) if hasattr(self, "api_settings") else DEFAULT_GEMINI_MODEL
        self.gemini_model_edit = QLineEdit(saved_model or DEFAULT_GEMINI_MODEL)
        self.gemini_model_edit.setPlaceholderText(DEFAULT_GEMINI_MODEL)
        model_layout.addWidget(self.gemini_model_edit, 1)
        self.test_gemini_btn = QPushButton("Testar Gemini")
        self.test_gemini_btn.clicked.connect(self._test_gemini_connection)
        model_layout.addWidget(self.test_gemini_btn)
        ai_layout.addLayout(model_layout)

        ai_actions = QHBoxLayout()
        self.analyze_clip_ai_btn = QPushButton("Analisar clipe com IA")
        self.analyze_clip_ai_btn.clicked.connect(self._on_analyze_current_clip_ai)
        ai_actions.addWidget(self.analyze_clip_ai_btn, 1)
        self.analyze_selected_clips_ai_btn = QPushButton("IA nos clipes selecionados")
        self.analyze_selected_clips_ai_btn.clicked.connect(self._on_analyze_selected_clips_ai)
        ai_actions.addWidget(self.analyze_selected_clips_ai_btn, 1)
        ai_layout.addLayout(ai_actions)

        info_layout.addWidget(ai_group)

        subtitle_group = QGroupBox("Legendas PT-BR")
        subtitle_layout = QVBoxLayout(subtitle_group)
        subtitle_help = QLabel(
            "Gera a legenda final sempre em PT-BR. Fluxo: usa PT-BR do arquivo; se não tiver, traduz legenda existente; se não houver legenda, usa API pelo áudio."
        )
        subtitle_help.setWordWrap(True)
        subtitle_layout.addWidget(subtitle_help)

        self.subtitle_status_label = QLabel("Selecione um clipe para ver o status da legenda.")
        self.subtitle_status_label.setWordWrap(True)
        self.subtitle_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        subtitle_layout.addWidget(self.subtitle_status_label)

        subtitle_actions = QHBoxLayout()
        self.generate_subtitle_btn = QPushButton("Gerar legenda PT-BR")
        self.generate_subtitle_btn.clicked.connect(self._on_generate_current_subtitle)
        subtitle_actions.addWidget(self.generate_subtitle_btn, 1)
        self.export_subtitled_btn = QPushButton("Exportar MP4 legendado")
        self.export_subtitled_btn.clicked.connect(self._on_export_current_subtitled)
        subtitle_actions.addWidget(self.export_subtitled_btn, 1)
        subtitle_layout.addLayout(subtitle_actions)

        subtitle_actions_2 = QHBoxLayout()
        self.open_subtitle_btn = QPushButton("Abrir legenda")
        self.open_subtitle_btn.clicked.connect(self._open_selected_subtitle)
        subtitle_actions_2.addWidget(self.open_subtitle_btn, 1)
        subtitle_layout.addLayout(subtitle_actions_2)

        info_layout.addWidget(subtitle_group)

        narration_group = QGroupBox("Roteiro e narração")
        narration_layout = QVBoxLayout(narration_group)
        narration_help = QLabel(
            "Gera texto para narrador apresentar o anime/clipe. Usa descrição, tags e legenda PT-BR quando existir."
        )
        narration_help.setWordWrap(True)
        narration_layout.addWidget(narration_help)

        self.narration_status_label = QLabel("Selecione um clipe para ver o status do roteiro.")
        self.narration_status_label.setWordWrap(True)
        self.narration_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        narration_layout.addWidget(self.narration_status_label)

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
            "Curto 20-30s", "Médio 45-60s", "Longo 75-90s"
        ])
        narration_options.addWidget(self.narration_length_combo, 1)
        narration_layout.addLayout(narration_options)

        narration_layout.addWidget(QLabel("Roteiro para narrador:"))
        self.narration_script_edit = QTextEdit()
        self.narration_script_edit.setPlaceholderText("O roteiro gerado para a narração aparecerá aqui...")
        self.narration_script_edit.setMinimumHeight(150)
        self.narration_script_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.narration_script_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.narration_script_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        narration_layout.addWidget(self.narration_script_edit)

        narration_layout.addWidget(QLabel("Título sugerido:"))
        self.tiktok_title_edit = QLineEdit()
        self.tiktok_title_edit.setPlaceholderText("Título curto para TikTok/Reels/Shorts")
        narration_layout.addWidget(self.tiktok_title_edit)

        narration_layout.addWidget(QLabel("Texto para publicação:"))
        self.tiktok_caption_edit = QTextEdit()
        self.tiktok_caption_edit.setPlaceholderText("Texto da publicação para copiar e colar...")
        self.tiktok_caption_edit.setMinimumHeight(120)
        self.tiktok_caption_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.tiktok_caption_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tiktok_caption_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        narration_layout.addWidget(self.tiktok_caption_edit)

        narration_layout.addWidget(QLabel("Hashtags:"))
        self.narration_hashtags_edit = QLineEdit()
        self.narration_hashtags_edit.setPlaceholderText("Até 5 hashtags, ex.: #anime #otaku #isekai #tedvhs #animes")
        narration_layout.addWidget(self.narration_hashtags_edit)

        narration_actions = QHBoxLayout()
        self.generate_narration_btn = QPushButton("Gerar roteiro com IA")
        self.generate_narration_btn.clicked.connect(self._on_generate_current_narration)
        narration_actions.addWidget(self.generate_narration_btn, 1)
        self.save_narration_btn = QPushButton("Salvar roteiro")
        self.save_narration_btn.clicked.connect(self._save_narration_metadata)
        narration_actions.addWidget(self.save_narration_btn, 1)
        narration_layout.addLayout(narration_actions)

        narration_actions_2 = QHBoxLayout()
        self.copy_post_btn = QPushButton("Copiar post + hashtags")
        self.copy_post_btn.setToolTip("Copia apenas o texto da publicação com as hashtags, pronto para colar no TikTok/Reels/Shorts.")
        self.copy_post_btn.clicked.connect(self._copy_tiktok_post_package)
        narration_actions_2.addWidget(self.copy_post_btn, 1)
        self.copy_narration_btn = QPushButton("Copiar pacote completo")
        self.copy_narration_btn.setToolTip("Copia título, roteiro, texto da publicação e hashtags.")
        self.copy_narration_btn.clicked.connect(self._copy_narration_package)
        narration_actions_2.addWidget(self.copy_narration_btn, 1)
        narration_layout.addLayout(narration_actions_2)

        info_layout.addWidget(narration_group)
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
                    "description", "tags", "scene_type", "segments", "export_mode",
                    "subtitles_ptbr", "subtitle_srt_path", "subtitle_ass_path", "legendado_path",
                    "narration_package", "narration_script", "narration_hook", "tiktok_title",
                    "tiktok_caption", "hashtags", "narration_style", "narration_length"
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
        self._set_combo_text(self.clip_type_combo, str(clip.get("scene_type") or "Geral"))
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
        self._update_subtitle_status_label(clip)
        self._load_narration_fields(clip)
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
        scene_type = self.clip_type_combo.currentText().strip() if hasattr(self, "clip_type_combo") else str(clip.get("scene_type") or "Geral")
        try:
            self.repository.update_exported_clip(
                int(clip["id"]),
                description=description,
                tags=tags,
                scene_type=scene_type,
            )
            self._update_metadata_json(clip, {"description": description, "tags": tags, "scene_type": scene_type})
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
                for subtitle_path in self._subtitle_sidecar_paths(clip):
                    if subtitle_path.exists():
                        try:
                            subtitle_path.unlink()
                        except Exception:
                            logger.warning("Não foi possível excluir arquivo lateral de legenda: %s", subtitle_path)
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
        menu.addAction("Analisar clipe com IA", self._on_analyze_current_clip_ai)
        menu.addAction("Gerar legenda PT-BR", self._on_generate_current_subtitle)
        menu.addAction("Exportar MP4 legendado", self._on_export_current_subtitled)
        menu.addAction("Gerar roteiro/narração", self._on_generate_current_narration)
        menu.addAction("Salvar roteiro/narração", self._save_narration_metadata)
        menu.addSeparator()
        menu.addAction("Excluir clipe", self._delete_selected_clips)
        menu.addSeparator()
        menu.addAction("Atualizar lista", self.refresh_clips)
        menu.exec(self.table.viewport().mapToGlobal(position))


    def _narration_data_for_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = clip.get("metadata_json") if isinstance(clip.get("metadata_json"), dict) else {}
        package = metadata.get("narration_package") if isinstance(metadata.get("narration_package"), dict) else {}
        if not package:
            package = clip.get("narration_package") if isinstance(clip.get("narration_package"), dict) else {}
        return {
            "roteiro_narracao": package.get("roteiro_narracao") or clip.get("narration_script") or metadata.get("narration_script") or "",
            "gancho": package.get("gancho") or clip.get("narration_hook") or metadata.get("narration_hook") or "",
            "titulo_tiktok": package.get("titulo_tiktok") or clip.get("tiktok_title") or metadata.get("tiktok_title") or "",
            "texto_tiktok": package.get("texto_tiktok") or clip.get("tiktok_caption") or metadata.get("tiktok_caption") or "",
            "hashtags": package.get("hashtags") or clip.get("hashtags") or metadata.get("hashtags") or [],
            "cta": package.get("cta") or metadata.get("cta") or "",
            "estilo": package.get("estilo") or clip.get("narration_style") or metadata.get("narration_style") or "Empolgado",
            "tamanho": package.get("tamanho") or clip.get("narration_length") or metadata.get("narration_length") or "Médio 45-60s",
            "modelo": package.get("modelo") or metadata.get("narration_model") or "",
        }

    def _load_narration_fields(self, clip: Dict[str, Any]) -> None:
        data = self._narration_data_for_clip(clip)
        script = str(data.get("roteiro_narracao") or "")
        title = str(data.get("titulo_tiktok") or "")
        caption = str(data.get("texto_tiktok") or "")
        hashtags = data.get("hashtags") or []
        if isinstance(hashtags, list):
            hashtags_text = " ".join(str(tag) for tag in hashtags)
        else:
            hashtags_text = str(hashtags or "")
        if hasattr(self, "narration_script_edit"):
            self.narration_script_edit.setPlainText(script)
        if hasattr(self, "tiktok_title_edit"):
            self.tiktok_title_edit.setText(title)
        if hasattr(self, "tiktok_caption_edit"):
            self.tiktok_caption_edit.setPlainText(caption)
        if hasattr(self, "narration_hashtags_edit"):
            self.narration_hashtags_edit.setText(hashtags_text)
        if hasattr(self, "narration_style_combo"):
            self._set_combo_text(self.narration_style_combo, str(data.get("estilo") or "Empolgado"))
        if hasattr(self, "narration_length_combo"):
            self._set_combo_text(self.narration_length_combo, str(data.get("tamanho") or "Médio 45-60s"))
        self._update_narration_status_label(clip)

    def _update_narration_status_label(self, clip: Dict[str, Any]) -> None:
        label = getattr(self, "narration_status_label", None)
        if label is None:
            return
        data = self._narration_data_for_clip(clip)
        script = str(data.get("roteiro_narracao") or "").strip()
        if script:
            label.setText(
                "Status: roteiro pronto para este clipe.\n"
                f"Estilo: {data.get('estilo') or '-'} | Tamanho: {data.get('tamanho') or '-'}\n"
                f"Modelo: {data.get('modelo') or '-'}"
            )
        else:
            label.setText(
                "Status: sem roteiro salvo para este clipe.\n"
                "Clique em ‘Gerar roteiro com IA’ depois de ter descrição e, se possível, legenda PT-BR."
            )

    def _on_generate_current_narration(self) -> None:
        if not self._selected_clip:
            QMessageBox.information(self, "Roteiro de narração", "Selecione um clipe exportado para gerar roteiro.")
            return
        self._start_narration_worker(self._selected_clip)

    def _start_narration_worker(self, clip: Dict[str, Any]) -> None:
        if self._narration_thread is not None:
            QMessageBox.information(self, "Roteiro em andamento", "Aguarde o roteiro atual terminar.")
            return
        if self._ai_thread is not None or self._subtitle_thread is not None:
            QMessageBox.information(self, "Operação em andamento", "Aguarde a IA/legenda atual terminar antes de gerar roteiro.")
            return
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        if not api_key:
            QMessageBox.warning(self, "API Key necessária", "Cole sua API Key gratuita do Gemini antes de gerar o roteiro.")
            return
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_NARRATION_MODEL
        if not model:
            model = DEFAULT_NARRATION_MODEL
            self.gemini_model_edit.setText(model)
        self._maybe_save_gemini_settings(api_key, model)

        has_description = bool(str(clip.get("description") or "").strip())
        subtitle_data = self._subtitle_data_for_clip(clip)
        has_subtitle = Path(str(subtitle_data.get("srt_path") or "")).exists()
        if not has_description and not has_subtitle:
            reply = QMessageBox.question(
                self,
                "Gerar mesmo assim?",
                "Este clipe ainda não tem descrição IA nem legenda PT-BR.\n\n"
                "O roteiro pode ficar genérico. O ideal é analisar o clipe com IA ou gerar a legenda antes.\n\n"
                "Deseja continuar mesmo assim?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        style = self.narration_style_combo.currentText().strip() if hasattr(self, "narration_style_combo") else "Empolgado"
        length = self.narration_length_combo.currentText().strip() if hasattr(self, "narration_length_combo") else "Médio 45-60s"
        self._set_narration_buttons_enabled(False)
        self.status_label.setText("Preparando roteiro de narração...")
        thread = QThread(self)
        worker = _ClipNarrationWorker(
            narration_service=self.narration_service,
            clip=clip,
            api_key=api_key,
            model=model,
            style=style,
            length=length,
        )
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
        clip = self._selected_clip
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        if not result:
            QMessageBox.warning(self, "Roteiro de narração", "A API respondeu, mas o roteiro veio vazio.")
            self._set_narration_buttons_enabled(True)
            return
        if hasattr(self, "narration_script_edit"):
            self.narration_script_edit.setPlainText(str(result.get("roteiro_narracao") or ""))
        if hasattr(self, "tiktok_title_edit"):
            self.tiktok_title_edit.setText(str(result.get("titulo_tiktok") or ""))
        if hasattr(self, "tiktok_caption_edit"):
            self.tiktok_caption_edit.setPlainText(str(result.get("texto_tiktok") or ""))
        hashtags = result.get("hashtags") or []
        hashtags_text = " ".join(str(tag) for tag in hashtags) if isinstance(hashtags, list) else str(hashtags or "")
        if hasattr(self, "narration_hashtags_edit"):
            self.narration_hashtags_edit.setText(hashtags_text)
        if clip:
            package = dict(result)
            package.update({
                "modelo": payload.get("model"),
                "estilo": payload.get("style"),
                "tamanho": payload.get("length"),
            })
            self._update_metadata_json(clip, {
                "narration_package": package,
                "narration_script": result.get("roteiro_narracao"),
                "narration_hook": result.get("gancho"),
                "tiktok_title": result.get("titulo_tiktok"),
                "tiktok_caption": result.get("texto_tiktok"),
                "hashtags": hashtags_text,
                "narration_style": payload.get("style"),
                "narration_length": payload.get("length"),
                "narration_model": payload.get("model"),
            })
        self.status_label.setText("Roteiro de narração gerado e salvo no JSON do clipe.")
        QMessageBox.information(self, "Roteiro pronto", "Roteiro de narração gerado com sucesso.")
        current_id = int(clip.get("id")) if clip and clip.get("id") else None
        self.refresh_clips()
        if current_id is not None:
            self._select_clip_by_id(current_id)
        self._set_narration_buttons_enabled(True)

    def _on_narration_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Roteiro de narração", message)
        self.status_label.setText(f"Roteiro falhou: {message}")
        self._set_narration_buttons_enabled(True)

    def _clear_narration_worker(self) -> None:
        self._narration_thread = None
        self._narration_worker = None
        self._set_narration_buttons_enabled(True)

    def _set_narration_buttons_enabled(self, enabled: bool) -> None:
        for attr in ("generate_narration_btn", "save_narration_btn", "copy_narration_btn", "copy_post_btn"):
            button = getattr(self, attr, None)
            if button is not None:
                button.setEnabled(enabled)

    def _save_narration_metadata(self) -> None:
        clip = self._selected_clip
        if not clip:
            return
        script = self.narration_script_edit.toPlainText().strip() if hasattr(self, "narration_script_edit") else ""
        title = self.tiktok_title_edit.text().strip() if hasattr(self, "tiktok_title_edit") else ""
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        style = self.narration_style_combo.currentText().strip() if hasattr(self, "narration_style_combo") else ""
        length = self.narration_length_combo.currentText().strip() if hasattr(self, "narration_length_combo") else ""
        package = {
            "gancho": self._first_sentence(script),
            "roteiro_narracao": script,
            "titulo_tiktok": title,
            "texto_tiktok": caption,
            "hashtags": hashtags,
            "estilo": style,
            "tamanho": length,
            "fonte": "manual",
        }
        try:
            self._update_metadata_json(clip, {
                "narration_package": package,
                "narration_script": script,
                "narration_hook": package.get("gancho"),
                "tiktok_title": title,
                "tiktok_caption": caption,
                "hashtags": hashtags,
                "narration_style": style,
                "narration_length": length,
            })
            self.status_label.setText("Roteiro/narração salvo no JSON do clipe.")
            QMessageBox.information(self, "Roteiro salvo", "Roteiro e texto de publicação salvos no JSON lateral do clipe.")
            current_id = int(clip.get("id")) if clip.get("id") else None
            self.refresh_clips()
            if current_id is not None:
                self._select_clip_by_id(current_id)
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao salvar roteiro", str(exc))

    def _copy_tiktok_post_package(self) -> None:
        """Copia somente o texto de postagem com hashtags para a área de transferência."""
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        post_text = self._compose_tiktok_post_text(caption, hashtags)
        if not post_text:
            QMessageBox.information(
                self,
                "Nada para copiar",
                "Gere ou escreva o texto da publicação antes de copiar o post."
            )
            return
        self._copy_text_to_clipboard(post_text, "Post com hashtags copiado para a área de transferência.")

    def _copy_narration_package(self) -> None:
        """Copia título, roteiro, texto de post e hashtags para a área de transferência."""
        script = self.narration_script_edit.toPlainText().strip() if hasattr(self, "narration_script_edit") else ""
        title = self.tiktok_title_edit.text().strip() if hasattr(self, "tiktok_title_edit") else ""
        caption = self.tiktok_caption_edit.toPlainText().strip() if hasattr(self, "tiktok_caption_edit") else ""
        hashtags = self.narration_hashtags_edit.text().strip() if hasattr(self, "narration_hashtags_edit") else ""
        post_text = self._compose_tiktok_post_text(caption, hashtags)
        package_parts = []
        if title:
            package_parts.append(f"TÍTULO:\n{title}")
        if script:
            package_parts.append(f"ROTEIRO/NARRAÇÃO:\n{script}")
        if post_text:
            package_parts.append(f"TEXTO DO POST COM HASHTAGS:\n{post_text}")
        elif caption:
            package_parts.append(f"TEXTO DO POST:\n{caption}")
        elif hashtags:
            package_parts.append(f"HASHTAGS:\n{hashtags}")
        package = "\n\n".join(package_parts).strip()
        if not package:
            QMessageBox.information(
                self,
                "Nada para copiar",
                "Gere ou escreva o roteiro/texto da publicação antes de copiar o pacote."
            )
            return
        self._copy_text_to_clipboard(package, "Pacote completo copiado para a área de transferência.")

    def _copy_text_to_clipboard(self, text: str, success_message: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        # Mantém o texto também no modo Selection quando existir, sem quebrar no Windows.
        try:
            if clipboard.supportsSelection():
                clipboard.setText(text, clipboard.Mode.Selection)
        except Exception:
            pass
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
        # Evita duplicar hashtags caso a IA já tenha colocado no final do texto.
        caption_lower = caption.lower()
        hashtag_tokens = [tag for tag in hashtags.split() if tag.startswith("#")]
        missing_tags = [tag for tag in hashtag_tokens if tag.lower() not in caption_lower]
        if missing_tags:
            return f"{caption}\n\n{' '.join(missing_tags)}".strip()
        return caption

    @staticmethod
    def _first_sentence(text: str) -> str:
        clean = str(text or "").strip()
        if not clean:
            return ""
        for marker in (". ", "! ", "? ", "\n"):
            if marker in clean:
                return clean.split(marker, 1)[0].strip() + (marker.strip() if marker.strip() in ".!?" else "")
        return clean[:160]


    def _on_generate_current_subtitle(self) -> None:
        if not self._selected_clip:
            QMessageBox.information(self, "Legenda PT-BR", "Selecione um clipe exportado para gerar legenda.")
            return
        self._start_subtitle_worker(self._selected_clip, action="generate")

    def _on_export_current_subtitled(self) -> None:
        if not self._selected_clip:
            QMessageBox.information(self, "MP4 legendado", "Selecione um clipe exportado para exportar com legenda.")
            return
        subtitle_data = self._subtitle_data_for_clip(self._selected_clip)
        ass_path = Path(str(subtitle_data.get("ass_path") or ""))
        if not ass_path.exists():
            QMessageBox.warning(
                self,
                "Legenda não encontrada",
                "Gere a legenda PT-BR do clipe antes de exportar o MP4 legendado."
            )
            return
        self._start_subtitle_worker(self._selected_clip, action="burn")

    def _start_subtitle_worker(self, clip: Dict[str, Any], action: str = "generate") -> None:
        if self._subtitle_thread is not None:
            QMessageBox.information(self, "Legenda em andamento", "Aguarde a operação de legenda atual terminar.")
            return
        if self._ai_thread is not None:
            QMessageBox.information(self, "IA em andamento", "Aguarde a análise por IA terminar antes de gerar legenda.")
            return

        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_GEMINI_MODEL
        if not model:
            model = DEFAULT_GEMINI_MODEL
            self.gemini_model_edit.setText(model)
        self._maybe_save_gemini_settings(api_key, model)

        if action == "generate":
            reply = QMessageBox.question(
                self,
                "Gerar legenda PT-BR?",
                "O app tentará nesta ordem:\n\n"
                "1. usar legenda PT-BR do arquivo original;\n"
                "2. se só houver legenda em outro idioma, traduzir para PT-BR com Gemini;\n"
                "3. se não houver legenda, transcrever/traduzir o áudio com Gemini.\n\n"
                "Para tradução ou transcrição, a API Key do Gemini será necessária e consumirá cota gratuita.\n\n"
                "Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

        self._set_subtitle_buttons_enabled(False)
        self.status_label.setText("Preparando legenda PT-BR...")
        thread = QThread(self)
        worker = _ClipSubtitleWorker(
            subtitle_service=self.subtitle_service,
            clip=clip,
            api_key=api_key,
            model=model,
            action=action,
        )
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
        clip = self._selected_clip
        clip_id = result.get("id")
        if result.get("action") == "burn":
            legendado_path = result.get("legendado_path")
            if clip:
                self._update_metadata_json(clip, {"legendado_path": legendado_path})
            self.status_label.setText(f"MP4 legendado exportado: {legendado_path}")
            QMessageBox.information(self, "MP4 legendado", f"Vídeo legendado criado com sucesso:\n{legendado_path}")
            self.refresh_clips()
            if clip_id:
                self._select_clip_by_id(int(clip_id))
            self._set_subtitle_buttons_enabled(True)
            return

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
        self.status_label.setText(
            f"Legenda PT-BR criada: {result.get('cue_count') or 0} fala(s). Fonte: {result.get('source') or 'auto'}"
        )
        QMessageBox.information(
            self,
            "Legenda PT-BR criada",
            f"Legenda criada com sucesso.\n\n"
            f"Fonte: {result.get('source') or 'auto'}\n"
            f"Falas: {result.get('cue_count') or 0}\n"
            f"SRT: {result.get('srt_path')}\n"
            f"ASS: {result.get('ass_path')}"
        )
        self.refresh_clips()
        if clip_id:
            self._select_clip_by_id(int(clip_id))
        self._set_subtitle_buttons_enabled(True)

    def _on_subtitle_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Legenda PT-BR", message)
        self.status_label.setText(f"Legenda falhou: {message}")
        self._set_subtitle_buttons_enabled(True)

    def _clear_subtitle_worker(self) -> None:
        self._subtitle_thread = None
        self._subtitle_worker = None
        self._set_subtitle_buttons_enabled(True)

    def _set_subtitle_buttons_enabled(self, enabled: bool) -> None:
        for attr in ("generate_subtitle_btn", "export_subtitled_btn", "open_subtitle_btn"):
            button = getattr(self, attr, None)
            if button is not None:
                button.setEnabled(enabled)

    def _subtitle_data_for_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        metadata = clip.get("metadata_json") if isinstance(clip.get("metadata_json"), dict) else {}
        subtitles = metadata.get("subtitles_ptbr") if isinstance(metadata.get("subtitles_ptbr"), dict) else {}
        if subtitles:
            return subtitles
        output_path = Path(str(clip.get("output_path") or ""))
        direct_srt = output_path.with_name(f"{output_path.stem}.pt-BR.srt") if output_path else Path("")
        direct_ass = output_path.with_name(f"{output_path.stem}.pt-BR.ass") if output_path else Path("")
        return {
            "srt_path": clip.get("subtitle_srt_path") or (str(direct_srt) if direct_srt.exists() else ""),
            "ass_path": clip.get("subtitle_ass_path") or (str(direct_ass) if direct_ass.exists() else ""),
            "source": subtitles.get("source") if isinstance(subtitles, dict) else "",
            "cue_count": subtitles.get("cue_count") if isinstance(subtitles, dict) else "",
        }

    def _update_subtitle_status_label(self, clip: Dict[str, Any]) -> None:
        label = getattr(self, "subtitle_status_label", None)
        if label is None:
            return
        subtitle_data = self._subtitle_data_for_clip(clip)
        srt = Path(str(subtitle_data.get("srt_path") or ""))
        ass = Path(str(subtitle_data.get("ass_path") or ""))
        if srt.exists() or ass.exists():
            label.setText(
                "Status: legenda PT-BR pronta.\n"
                f"Fonte: {subtitle_data.get('source') or 'arquivo/API'}\n"
                f"Falas: {subtitle_data.get('cue_count') or '-'}\n"
                f"SRT: {srt if srt.exists() else '-'}\n"
                f"ASS: {ass if ass.exists() else '-'}"
            )
        else:
            source_file = str(clip.get("source_file") or "")
            label.setText(
                "Status: sem legenda PT-BR gerada para este clipe.\n"
                "Clique em ‘Gerar legenda PT-BR’.\n"
                f"Arquivo original: {source_file or 'não informado'}"
            )

    def _open_selected_subtitle(self) -> None:
        clip = self._selected_clip
        if not clip:
            return
        subtitle_data = self._subtitle_data_for_clip(clip)
        candidates = [Path(str(subtitle_data.get("ass_path") or "")), Path(str(subtitle_data.get("srt_path") or ""))]
        for path in candidates:
            if path.exists():
                self._open_path(path)
                return
        QMessageBox.information(self, "Legenda PT-BR", "Nenhuma legenda PT-BR foi encontrada para este clipe.")


    def _on_analyze_current_clip_ai(self) -> None:
        if not self._selected_clip:
            QMessageBox.information(self, "IA do clipe", "Selecione um clipe exportado para analisar.")
            return
        self._start_clip_ai_worker([self._selected_clip])

    def _on_analyze_selected_clips_ai(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        clips = [self._clips_by_row[row.row()] for row in rows if row.row() in self._clips_by_row]
        if not clips and self._selected_clip:
            clips = [self._selected_clip]
        if not clips:
            QMessageBox.information(self, "IA do clipe", "Selecione um ou mais clipes na biblioteca.")
            return
        if len(clips) > 1:
            reply = QMessageBox.question(
                self,
                "Usar IA nos clipes selecionados?",
                f"Você selecionou {len(clips)} clipe(s).\n\n"
                "Cada clipe usa uma chamada da Gemini API e consome cota gratuita. "
                "O app enviará poucos frames comprimidos de cada MP4.\n\n"
                "Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No if len(clips) > 8 else QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return
        self._start_clip_ai_worker(clips)

    def _start_clip_ai_worker(self, clips: List[Dict[str, Any]]) -> None:
        if self._ai_thread is not None:
            QMessageBox.information(self, "IA em andamento", "Aguarde a análise atual terminar antes de iniciar outra.")
            return
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        if not api_key:
            QMessageBox.warning(
                self,
                "API Key necessária",
                "Cole sua API Key gratuita do Gemini no campo API Key antes de analisar o clipe."
            )
            return
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_GEMINI_MODEL
        if not model:
            model = DEFAULT_GEMINI_MODEL
            self.gemini_model_edit.setText(model)
        self._maybe_save_gemini_settings(api_key, model)

        valid_clips = []
        for clip in clips:
            path = Path(str(clip.get("output_path") or ""))
            if path.exists():
                valid_clips.append(clip)
        if not valid_clips:
            QMessageBox.warning(self, "Arquivo não encontrado", "Nenhum clipe selecionado possui arquivo MP4 válido.")
            return

        self._set_ai_buttons_enabled(False)
        self.status_label.setText(f"Preparando IA para {len(valid_clips)} clipe(s)...")
        thread = QThread(self)
        worker = _ClipAIWorker(
            ai_service=self.ai_service,
            clips=valid_clips,
            api_key=api_key,
            model=model,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status_label.setText)
        worker.finished.connect(self._on_clip_ai_finished)
        worker.failed.connect(self._on_clip_ai_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_ai_worker)
        self._ai_thread = thread
        self._ai_worker = worker
        thread.start()

    def _on_clip_ai_finished(self, results: List[Dict[str, Any]]) -> None:
        current_id = int(self._selected_clip.get("id")) if self._selected_clip and self._selected_clip.get("id") else None
        updated = 0
        for result in results:
            clip_id = result.get("id")
            if not clip_id:
                continue
            try:
                self.repository.update_exported_clip(
                    int(clip_id),
                    description=result.get("description"),
                    tags=result.get("tags"),
                    scene_type=result.get("scene_type"),
                    status="ai_described",
                )
                clip = next((item for item in self._all_clips if int(item.get("id") or -1) == int(clip_id)), None)
                if clip:
                    self._update_metadata_json(clip, {
                        "description": result.get("description"),
                        "tags": result.get("tags"),
                        "scene_type": result.get("scene_type"),
                        "ai_clip_analysis": result.get("analysis_payload"),
                    })
                updated += 1
            except Exception as exc:
                logger.error("Erro ao salvar IA do clipe %s: %s", clip_id, exc, exc_info=True)
        self.status_label.setText(f"IA de clipes concluída: {updated} clipe(s) atualizado(s).")
        self.refresh_clips()
        if current_id is not None:
            self._select_clip_by_id(current_id)
        self._set_ai_buttons_enabled(True)

    def _on_clip_ai_failed(self, message: str) -> None:
        QMessageBox.warning(self, "IA do clipe", message)
        self.status_label.setText(f"IA do clipe falhou: {message}")
        self._set_ai_buttons_enabled(True)

    def _clear_ai_worker(self) -> None:
        self._ai_thread = None
        self._ai_worker = None
        self._set_ai_buttons_enabled(True)

    def _set_ai_buttons_enabled(self, enabled: bool) -> None:
        for attr in ("analyze_clip_ai_btn", "analyze_selected_clips_ai_btn", "test_gemini_btn", "save_api_key_btn", "clear_api_key_btn", "save_api_key_checkbox"):
            button = getattr(self, attr, None)
            if button is not None:
                button.setEnabled(enabled)

    def _maybe_save_gemini_settings(self, api_key: str, model: str) -> None:
        checkbox = getattr(self, "save_api_key_checkbox", None)
        if checkbox is not None and checkbox.isChecked():
            try:
                self.api_settings.save_gemini(api_key=api_key, model=model)
            except Exception as exc:
                logger.warning("Não foi possível salvar a chave Gemini: %s", exc)

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

    def _test_gemini_connection(self) -> None:
        api_key = self.gemini_api_key_edit.text().strip() if hasattr(self, "gemini_api_key_edit") else ""
        model = self.gemini_model_edit.text().strip() if hasattr(self, "gemini_model_edit") else DEFAULT_GEMINI_MODEL
        if not api_key:
            QMessageBox.warning(self, "API Key necessária", "Cole sua API Key gratuita do Gemini no campo API Key.")
            return
        if not model:
            model = DEFAULT_GEMINI_MODEL
            self.gemini_model_edit.setText(model)
        try:
            self.status_label.setText("Testando Gemini API...")
            result = self.ai_service.test_connection(api_key=api_key, model=model)
            QMessageBox.information(
                self,
                "Gemini conectado",
                "Gemini API respondeu corretamente.\n\n"
                f"Modelo: {result.get('model') or model}\n"
                f"Resposta: {result.get('response') or 'OK'}"
            )
            self.status_label.setText(f"Gemini OK. Modelo selecionado: {result.get('model') or model}")
            self._maybe_save_gemini_settings(api_key, result.get('model') or model)
        except GeminiSceneAIError as exc:
            QMessageBox.warning(self, "Gemini não disponível", str(exc))
            self.status_label.setText(f"Gemini não disponível: {exc}")
        except Exception as exc:
            QMessageBox.warning(self, "Gemini não disponível", f"Não foi possível conectar à Gemini API: {exc}")
            self.status_label.setText(f"Gemini não disponível: {exc}")

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        text = str(value or "").strip() or "Geral"
        index = combo.findText(text)
        if index < 0:
            combo.addItem(text)
            index = combo.findText(text)
        combo.setCurrentIndex(max(index, 0))

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

    def _subtitle_sidecar_paths(self, clip: Dict[str, Any]) -> List[Path]:
        output_path = Path(str(clip.get("output_path") or ""))
        paths: List[Path] = []
        if output_path.name:
            paths.extend([
                output_path.with_name(f"{output_path.stem}.pt-BR.srt"),
                output_path.with_name(f"{output_path.stem}.pt-BR.ass"),
                output_path.with_name(f"{output_path.stem} legendado.mp4"),
            ])
        subtitle_data = self._subtitle_data_for_clip(clip) if isinstance(clip, dict) else {}
        for key in ("srt_path", "ass_path", "legendado_path"):
            value = subtitle_data.get(key) or clip.get(key) if isinstance(clip, dict) else None
            if value:
                paths.append(Path(str(value)))
        unique: List[Path] = []
        for path in paths:
            if path and path not in unique:
                unique.append(path)
        return unique


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

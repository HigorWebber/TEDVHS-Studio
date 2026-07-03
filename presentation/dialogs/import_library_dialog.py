"""Diálogo para iniciar e acompanhar importação de biblioteca de mídia."""

import logging
from typing import List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QInputDialog,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from application.media.import_orchestrator import ImportOrchestrator
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository


logger = logging.getLogger(__name__)


class ImportLibraryDialog(QDialog):
    """Diálogo de seleção de arquivos/pasta e acompanhamento de progresso."""

    TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}

    def __init__(
        self,
        orchestrator: ImportOrchestrator,
        repository: SQLiteMediaRepository,
        parent=None,
    ):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.repository = repository
        self.current_session_id: Optional[str] = None
        self.selected_files: List[str] = []
        self._is_importing = False
        self._is_paused = False

        self.setWindowTitle("Importar Biblioteca")
        self.setModal(True)
        self.resize(680, 320)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll_progress)

        self._setup_ui()
        self._load_folders()
        self._load_seasons()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Selecione arquivos de mídia ou uma pasta inteira:"))

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Arquivos selecionados ou caminho da pasta...")
        path_layout.addWidget(self.path_input)

        self.files_button = QPushButton("Selecionar Arquivos")
        self.files_button.clicked.connect(self._select_files)
        path_layout.addWidget(self.files_button)

        self.browse_button = QPushButton("Selecionar Pasta")
        self.browse_button.clicked.connect(self._select_folder)
        path_layout.addWidget(self.browse_button)
        layout.addLayout(path_layout)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Pasta:"))
        self.folder_combo = QComboBox()
        self.folder_combo.currentTextChanged.connect(self._on_folder_changed)
        folder_layout.addWidget(self.folder_combo)

        self.new_folder_button = QPushButton("Nova Pasta")
        self.new_folder_button.clicked.connect(self._create_folder)
        folder_layout.addWidget(self.new_folder_button)

        folder_layout.addWidget(QLabel("Temporada:"))
        self.season_combo = QComboBox()
        folder_layout.addWidget(self.season_combo)

        self.new_season_button = QPushButton("Nova Temporada")
        self.new_season_button.clicked.connect(self._create_season)
        folder_layout.addWidget(self.new_season_button)
        layout.addLayout(folder_layout)

        self.stage_label = QLabel("Aguardando início")
        layout.addWidget(self.stage_label)

        self.current_file_label = QLabel("Arquivo atual: -")
        self.current_file_label.setWordWrap(True)
        layout.addWidget(self.current_file_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.details_label = QLabel(
            "Encontrados: 0 | Válidos: 0 | Importados: 0 | Duplicados: 0 | Falhas: 0"
        )
        layout.addWidget(self.details_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.close_button = QPushButton("Fechar")
        self.close_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.close_button)

        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.pause_button.setEnabled(False)
        buttons_layout.addWidget(self.pause_button)

        self.cancel_import_button = QPushButton("Cancelar Importação")
        self.cancel_import_button.clicked.connect(self._cancel_import)
        self.cancel_import_button.setEnabled(False)
        buttons_layout.addWidget(self.cancel_import_button)

        self.import_button = QPushButton("Iniciar Importação")
        self.import_button.clicked.connect(self._start_import)
        buttons_layout.addWidget(self.import_button)

        layout.addLayout(buttons_layout)

    def _load_folders(self, selected: Optional[str] = None) -> None:
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        try:
            folders = self.repository.get_library_folders()
        except Exception:
            folders = ["Sem pasta"]

        if not folders:
            folders = ["Sem pasta"]

        self.folder_combo.addItems(folders)
        target = selected or "Sem pasta"
        index = self.folder_combo.findText(target)
        if index >= 0:
            self.folder_combo.setCurrentIndex(index)
        self.folder_combo.blockSignals(False)

    def _load_seasons(self, selected: Optional[str] = None) -> None:
        """Carregar temporadas da pasta selecionada."""
        folder = self.folder_combo.currentText().strip() or "Sem pasta"
        self.season_combo.clear()
        try:
            seasons = self.repository.get_library_seasons(folder)
        except Exception:
            seasons = ["Sem temporada"]

        if not seasons:
            seasons = ["Sem temporada"]

        self.season_combo.addItems(seasons)
        target = selected or "Sem temporada"
        index = self.season_combo.findText(target)
        if index >= 0:
            self.season_combo.setCurrentIndex(index)

    def _on_folder_changed(self, text: str) -> None:
        self._load_seasons()

    def _create_folder(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Nova Pasta",
            "Nome da pasta da biblioteca:",
        )
        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Aviso", "Informe um nome para a pasta.")
            return

        try:
            created = self.repository.create_library_folder(name)
            self.repository.create_library_season(created, "Sem temporada")
            self._load_folders(created)
            self._load_seasons()
        except Exception as exc:
            logger.error("Erro ao criar pasta: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao criar pasta: {exc}")

    def _create_season(self) -> None:
        folder = self.folder_combo.currentText().strip() or "Sem pasta"
        name, ok = QInputDialog.getText(
            self,
            "Nova Temporada",
            f"Nome da temporada dentro de {folder}:",
        )
        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Aviso", "Informe um nome para a temporada.")
            return

        try:
            created = self.repository.create_library_season(folder, name)
            self._load_seasons(created)
        except Exception as exc:
            logger.error("Erro ao criar temporada: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao criar temporada: {exc}")

    def _select_files(self) -> None:
        """Selecionar arquivos individuais de mídia."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar Arquivos de Mídia",
            "",
            "Vídeos (*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v);;Todos os arquivos (*.*)",
        )

        if files:
            self.selected_files = files
            if len(files) == 1:
                self.path_input.setText(files[0])
            else:
                self.path_input.setText(f"{len(files)} arquivo(s) selecionado(s)")

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar Pasta",
            "",
            QFileDialog.ShowDirsOnly,
        )
        if folder:
            self.selected_files = []
            self.path_input.setText(folder)

    def _start_import(self) -> None:
        folder_path = self.path_input.text().strip()
        library_folder = self.folder_combo.currentText().strip() or "Sem pasta"
        library_season = self.season_combo.currentText().strip() or "Sem temporada"

        if not self.selected_files and not folder_path:
            QMessageBox.warning(self, "Aviso", "Selecione arquivos ou uma pasta para importar.")
            return

        try:
            if self.selected_files:
                self.current_session_id = self.orchestrator.start_import_files(
                    self.selected_files,
                    library_folder=library_folder,
                    library_season=library_season,
                )
            else:
                self.current_session_id = self.orchestrator.start_import(
                    folder_path,
                    library_folder=library_folder,
                    library_season=library_season,
                )
            logger.info("Importação iniciada: %s", self.current_session_id)

            self._is_importing = True
            self._is_paused = False
            self.path_input.setEnabled(False)
            self.files_button.setEnabled(False)
            self.browse_button.setEnabled(False)
            self.folder_combo.setEnabled(False)
            self.new_folder_button.setEnabled(False)
            self.season_combo.setEnabled(False)
            self.new_season_button.setEnabled(False)
            self.import_button.setEnabled(False)
            self.close_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.cancel_import_button.setEnabled(True)
            self.stage_label.setText(f"Importação iniciada em: {library_folder} / {library_season}")
            self.timer.start()
        except Exception as exc:
            logger.error("Erro ao iniciar importação: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Falha ao iniciar importação: {exc}")

    def _toggle_pause(self) -> None:
        if not self.current_session_id:
            return

        if self._is_paused:
            if self.orchestrator.resume_paused_import(self.current_session_id):
                self._is_paused = False
                self.pause_button.setText("Pausar")
                self.stage_label.setText("Retomando importação...")
        else:
            if self.orchestrator.pause_import(self.current_session_id):
                self._is_paused = True
                self.pause_button.setText("Retomar")
                self.stage_label.setText("Pausando ao final do arquivo atual...")

    def _cancel_import(self) -> None:
        if not self.current_session_id:
            return

        reply = QMessageBox.question(
            self,
            "Cancelar Importação",
            "Cancelar a importação atual? O arquivo em processamento pode terminar antes de parar.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.orchestrator.cancel_import(self.current_session_id)
        self.cancel_import_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.stage_label.setText("Cancelamento solicitado...")

    def _poll_progress(self) -> None:
        if not self.current_session_id:
            return

        progress = self.orchestrator.get_session_progress(self.current_session_id)
        if not progress:
            return

        percentage = int(progress.get("percentage", 0) or 0)
        status = str(progress.get("status", "IN_PROGRESS"))
        stage = progress.get("stage") or status
        current_file = progress.get("current_file") or "-"

        self.progress_bar.setValue(max(0, min(100, percentage)))
        self.stage_label.setText(f"Status: {stage} ({percentage}%)")
        self.current_file_label.setText(f"Arquivo atual: {current_file}")
        self.details_label.setText(
            "Encontrados: {found} | Válidos: {valid} | Importados: {imported} | "
            "Duplicados: {duplicate} | Falhas: {failed}".format(
                found=progress.get("total_files_found", 0),
                valid=progress.get("total_files_valid", 0),
                imported=progress.get("total_files_imported", 0),
                duplicate=progress.get("total_files_duplicate", 0),
                failed=progress.get("total_files_failed", 0),
            )
        )

        if status in self.TERMINAL_STATUSES:
            self.timer.stop()
            self._is_importing = False
            self.close_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.cancel_import_button.setEnabled(False)
            self.import_button.setEnabled(False)

            if status == "FAILED":
                error = progress.get("error", "Erro desconhecido")
                QMessageBox.critical(self, "Importação falhou", str(error))
            elif status == "CANCELLED":
                QMessageBox.information(self, "Importação cancelada", "A importação foi cancelada.")
            else:
                QMessageBox.information(self, "Importação concluída", "Importação finalizada.")

            self.accept()

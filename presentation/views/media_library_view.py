"""View para exibição e organização da biblioteca de mídia importada."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.media.import_orchestrator import ImportOrchestrator
from domain.media.processing_status import ProcessingStatus
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from presentation.dialogs.import_library_dialog import ImportLibraryDialog


logger = logging.getLogger(__name__)


class MediaLibraryView(QWidget):
    """Tabela de arquivos importados, pastas internas, filtros e ações básicas."""

    SORT_OPTIONS = {
        "Data de upload: mais recente": ("date", True),
        "Data de upload: mais antiga": ("date", False),
        "Nome: A-Z": ("name_natural", False),
        "Nome: Z-A": ("name_natural", True),
        "Tamanho: maior primeiro": ("size", True),
        "Tamanho: menor primeiro": ("size", False),
        "Duração: maior primeiro": ("duration", True),
        "Duração: menor primeiro": ("duration", False),
        "Resolução: maior primeiro": ("resolution", True),
        "Status": ("status", False),
        "Pasta": ("folder", False),
        "Temporada": ("season", False),
    }

    def __init__(
        self,
        repository: SQLiteMediaRepository,
        orchestrator: ImportOrchestrator,
        parent=None,
    ):
        super().__init__(parent)
        self.repository = repository
        self.orchestrator = orchestrator
        self.current_session_id: Optional[str] = None
        self._row_media_ids: dict[int, object] = {}
        self._setup_ui()
        self._refresh_folders()
        self._refresh_seasons()
        self._load_media_files()
        logger.info("MediaLibraryView inicializado")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        title = QLabel("Biblioteca de Mídia Importada")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        toolbar_layout = QHBoxLayout()

        self.import_btn = QPushButton("Importar Biblioteca")
        self.import_btn.clicked.connect(self._on_import_clicked)
        toolbar_layout.addWidget(self.import_btn)

        self.resume_btn = QPushButton("Retomar Importação")
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        toolbar_layout.addWidget(self.resume_btn)

        toolbar_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems([
            "Todos",
            "Pronto",
            "Processando",
            "Pendente",
            "Erro",
            "Ignorado/Duplicado",
        ])
        self.status_filter.currentTextChanged.connect(self._on_filter_changed)
        toolbar_layout.addWidget(self.status_filter)

        toolbar_layout.addWidget(QLabel("Buscar:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Nome do arquivo...")
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self.search_input)

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        toolbar_layout.addWidget(self.refresh_btn)

        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)

        organization_layout = QHBoxLayout()
        organization_layout.addWidget(QLabel("Pasta:"))
        self.folder_filter = QComboBox()
        self.folder_filter.currentTextChanged.connect(self._on_folder_filter_changed)
        organization_layout.addWidget(self.folder_filter)

        self.create_folder_btn = QPushButton("Nova Pasta")
        self.create_folder_btn.clicked.connect(self._on_create_folder_clicked)
        organization_layout.addWidget(self.create_folder_btn)

        self.delete_folder_btn = QPushButton("Excluir Pasta")
        self.delete_folder_btn.clicked.connect(self._on_delete_folder_clicked)
        organization_layout.addWidget(self.delete_folder_btn)

        organization_layout.addWidget(QLabel("Temporada:"))
        self.season_filter = QComboBox()
        self.season_filter.currentTextChanged.connect(self._on_season_filter_changed)
        organization_layout.addWidget(self.season_filter)

        self.create_season_btn = QPushButton("Nova Temporada")
        self.create_season_btn.clicked.connect(self._on_create_season_clicked)
        organization_layout.addWidget(self.create_season_btn)

        self.delete_season_btn = QPushButton("Excluir Temporada")
        self.delete_season_btn.clicked.connect(self._on_delete_season_clicked)
        organization_layout.addWidget(self.delete_season_btn)

        self.move_to_folder_btn = QPushButton("Mover Selecionados")
        self.move_to_folder_btn.clicked.connect(self._on_move_selected_clicked)
        organization_layout.addWidget(self.move_to_folder_btn)

        organization_layout.addWidget(QLabel("Ordenar por:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(list(self.SORT_OPTIONS.keys()))
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)
        organization_layout.addWidget(self.sort_combo)

        organization_layout.addStretch()
        layout.addLayout(organization_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Nome do Arquivo",
            "Pasta",
            "Temporada",
            "Duração",
            "Resolução",
            "Tamanho",
            "Status",
            "Data Upload",
            "Ações",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 9):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2d2d2d;
                alternate-background-color: #3d3d3d;
                gridline-color: #404040;
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #ffffff;
                padding: 5px;
                border: 1px solid #404040;
            }
        """)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.status_label = QLabel("Carregando biblioteca...")
        self.status_label.setStyleSheet("color: #cccccc; font-size: 10pt;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def set_session_id(self, session_id: str) -> None:
        self.current_session_id = session_id
        self._refresh_folders()
        self._refresh_seasons()
        self._load_media_files()

    def _refresh_folders(self, keep_current: bool = True) -> None:
        current = self.folder_filter.currentText() if keep_current and hasattr(self, "folder_filter") else "Todas"
        try:
            folders = self.repository.get_library_folders()
        except Exception:
            folders = ["Sem pasta"]

        self.folder_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem("Todas")
        self.folder_filter.addItems([folder for folder in folders if folder != "Todas"])
        index = self.folder_filter.findText(current)
        self.folder_filter.setCurrentIndex(index if index >= 0 else 0)
        self.folder_filter.blockSignals(False)

    def _refresh_seasons(self, keep_current: bool = True) -> None:
        current = self.season_filter.currentText() if keep_current and hasattr(self, "season_filter") else "Todas"
        folder = self.folder_filter.currentText() if hasattr(self, "folder_filter") else "Todas"
        try:
            seasons = self.repository.get_library_seasons(None if folder == "Todas" else folder)
        except Exception:
            seasons = ["Sem temporada"]

        self.season_filter.blockSignals(True)
        self.season_filter.clear()
        self.season_filter.addItem("Todas")
        self.season_filter.addItems([season for season in seasons if season != "Todas"])
        index = self.season_filter.findText(current)
        self.season_filter.setCurrentIndex(index if index >= 0 else 0)
        self.season_filter.blockSignals(False)

    def _load_media_files(self) -> None:
        """Carregar biblioteca com filtros, pastas e ordenação."""
        try:
            selected_folder = self.folder_filter.currentText() if hasattr(self, "folder_filter") else "Todas"
            selected_season = self.season_filter.currentText() if hasattr(self, "season_filter") else "Todas"
            sort_text = self.sort_combo.currentText() if hasattr(self, "sort_combo") else "Data de upload: mais recente"
            order_by, descending = self.SORT_OPTIONS.get(sort_text, ("date", True))

            media_files = self.repository.find_all(
                limit=2000,
                library_folder=None if selected_folder == "Todas" else selected_folder,
                library_season=None if selected_season == "Todas" else selected_season,
                order_by=order_by,
                descending=descending,
            )
            media_files = self._apply_filters(media_files)

            self.table.setRowCount(0)
            self._row_media_ids.clear()

            if not media_files:
                self.status_label.setText("Nenhum arquivo encontrado na biblioteca")
                return

            self.table.setRowCount(len(media_files))

            for row, media in enumerate(media_files):
                self._row_media_ids[row] = media.id
                folder_name = self._get_media_folder(media)
                season_name = self._get_media_season(media)

                self.table.setItem(row, 0, QTableWidgetItem(media.file_info.file_name))
                self.table.setItem(row, 1, QTableWidgetItem(folder_name))
                self.table.setItem(row, 2, QTableWidgetItem(season_name))
                self.table.setItem(row, 3, QTableWidgetItem(self._format_duration(media)))
                self.table.setItem(row, 4, QTableWidgetItem(self._format_resolution(media)))
                self.table.setItem(row, 5, QTableWidgetItem(self._format_size(media.file_info.file_size.bytes)))

                status_text = self._format_status(media.processing_info.status)
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(self._get_status_color(media.processing_info.status))
                self.table.setItem(row, 6, status_item)

                import_date = media.processing_info.import_date.strftime("%d/%m/%Y %H:%M")
                self.table.setItem(row, 7, QTableWidgetItem(import_date))

                delete_btn = QPushButton("Deletar")
                delete_btn.setMaximumWidth(80)
                delete_btn.clicked.connect(lambda checked, m_id=media.id: self._on_delete_clicked(m_id))
                self.table.setCellWidget(row, 8, delete_btn)

            total_all = len(self.repository.find_all(limit=10000))
            self.status_label.setText(
                f"Exibindo: {len(media_files)} arquivo(s) | Total na biblioteca: {total_all} | "
                f"Pasta: {selected_folder} | Temporada: {selected_season} | Ordenação: {sort_text}"
            )
            logger.info("Carregados %s arquivos na biblioteca", len(media_files))

        except Exception as exc:
            logger.error("Erro ao carregar arquivos: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar arquivos: {exc}")

    def _apply_filters(self, media_files):
        search_text = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        selected_status = self.status_filter.currentText() if hasattr(self, "status_filter") else "Todos"

        result = []
        for media in media_files:
            if search_text and search_text not in media.file_info.file_name.lower():
                continue

            if selected_status != "Todos" and not self._matches_status_filter(media, selected_status):
                continue

            result.append(media)
        return result

    def _matches_status_filter(self, media, selected_filter: str) -> bool:
        status = media.processing_info.status
        status_name = getattr(status, "name", str(status)).upper()
        status_value = getattr(status, "value", str(status)).upper()
        combined = f"{status_name} {status_value}"

        if selected_filter == "Pronto":
            return "READY" in combined or "COMPLETED" in combined or "METADATA_EXTRACTED" in combined
        if selected_filter == "Processando":
            return "PROCESS" in combined or "REPROCESSING" in combined
        if selected_filter == "Pendente":
            return "PENDING" in combined or "DISCOVERED" in combined or "VALIDATED" in combined
        if selected_filter == "Erro":
            return "FAILED" in combined or "ERROR" in combined
        if selected_filter == "Ignorado/Duplicado":
            return bool(getattr(media.hash_info, "is_duplicate", False)) or "SKIPPED" in combined or "DUPLICATE" in combined
        return True

    def _get_media_folder(self, media) -> str:
        return str(getattr(media, "custom_metadata", {}).get("library_folder") or "Sem pasta")

    def _get_media_season(self, media) -> str:
        return str(getattr(media, "custom_metadata", {}).get("library_season") or "Sem temporada")

    def _format_duration(self, media) -> str:
        duration = media.video_info.duration.seconds if media.video_info.duration else 0
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _format_resolution(self, media) -> str:
        if not media.video_info.resolution:
            return ""
        return f"{media.video_info.resolution.width}x{media.video_info.resolution.height}"

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def _format_status(self, status) -> str:
        value = getattr(status, "value", str(status))
        labels = {
            ProcessingStatus.DISCOVERED.value: "Descoberto",
            ProcessingStatus.VALIDATED.value: "Validado",
            ProcessingStatus.METADATA_PENDING.value: "Metadados pendentes",
            ProcessingStatus.METADATA_EXTRACTED.value: "Metadados extraídos",
            ProcessingStatus.READY.value: "Pronto",
            ProcessingStatus.FAILED.value: "Erro",
            ProcessingStatus.SKIPPED.value: "Ignorado/Duplicado",
            ProcessingStatus.REPROCESS_REQUIRED.value: "Reprocessamento necessário",
            ProcessingStatus.REPROCESSING.value: "Reprocessando",
        }
        return labels.get(value, value)

    def _get_status_color(self, status) -> QColor:
        status_name = getattr(status, "name", str(status)).upper()
        status_value = getattr(status, "value", str(status)).upper()
        combined = f"{status_name} {status_value}"

        if "FAILED" in combined or "ERROR" in combined:
            return QColor(255, 0, 0)
        if "SKIPPED" in combined or "DUPLICATE" in combined:
            return QColor(255, 165, 0)
        if "READY" in combined or "COMPLETED" in combined or "METADATA_EXTRACTED" in combined:
            return QColor(0, 180, 0)
        if "PENDING" in combined or "PROCESS" in combined or "VALID" in combined or "METADATA" in combined:
            return QColor(0, 120, 255)
        return QColor(180, 180, 180)

    def _get_selected_media_ids(self) -> list:
        selected_rows = sorted({index.row() for index in self.table.selectedIndexes()})
        media_ids = []
        for row in selected_rows:
            media_id = self._row_media_ids.get(row)
            if media_id is not None:
                media_ids.append(media_id)
        return media_ids

    def _on_import_clicked(self) -> None:
        dialog = ImportLibraryDialog(self.orchestrator, self.repository, self)
        if dialog.exec() == QDialog.Accepted:
            if dialog.current_session_id:
                self.current_session_id = dialog.current_session_id
            self._refresh_folders()
            self._refresh_seasons()
            self._load_media_files()

    def _on_resume_clicked(self) -> None:
        sessions = self.orchestrator.get_incomplete_sessions()
        if not sessions:
            QMessageBox.information(self, "Informação", "Não há importações incompletas para retomar.")
            return

        session = sessions[0]
        reply = QMessageBox.question(
            self,
            "Retomar Importação",
            f"Retomar importação de: {Path(session['folder_path']).name}?\n"
            f"Arquivos importados: {session['total_files_imported']}/{session['total_files_found']}",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.orchestrator.resume_import(session["session_id"])
            self.set_session_id(session["session_id"])

    def _on_filter_changed(self, text: str) -> None:
        self._load_media_files()

    def _on_search_changed(self, text: str) -> None:
        self._load_media_files()

    def _on_folder_filter_changed(self, text: str) -> None:
        self._refresh_seasons(keep_current=False)
        self._load_media_files()

    def _on_season_filter_changed(self, text: str) -> None:
        self._load_media_files()

    def _on_sort_changed(self, text: str) -> None:
        self._load_media_files()

    def _on_refresh_clicked(self) -> None:
        self._refresh_folders()
        self._refresh_seasons()
        self._load_media_files()

    def _on_create_folder_clicked(self) -> None:
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
            self._refresh_folders(keep_current=False)
            index = self.folder_filter.findText(created)
            if index >= 0:
                self.folder_filter.setCurrentIndex(index)
            self._refresh_seasons(keep_current=False)
            self._load_media_files()
        except Exception as exc:
            logger.error("Erro ao criar pasta: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao criar pasta: {exc}")

    def _on_create_season_clicked(self) -> None:
        folder = self.folder_filter.currentText() if hasattr(self, "folder_filter") else "Sem pasta"
        if folder == "Todas":
            QMessageBox.information(self, "Nova Temporada", "Selecione uma pasta específica antes de criar uma temporada.")
            return

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
            self._refresh_seasons(keep_current=False)
            index = self.season_filter.findText(created)
            if index >= 0:
                self.season_filter.setCurrentIndex(index)
            self._load_media_files()
        except Exception as exc:
            logger.error("Erro ao criar temporada: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao criar temporada: {exc}")

    def _on_delete_folder_clicked(self) -> None:
        """Excluir a pasta selecionada e os registros dentro dela."""
        folder = self.folder_filter.currentText() if hasattr(self, "folder_filter") else "Todas"
        if folder in {"", "Todas", "Sem pasta"}:
            QMessageBox.information(
                self,
                "Excluir Pasta",
                "Selecione uma pasta específica para excluir. A pasta padrão 'Sem pasta' não pode ser excluída.",
            )
            return

        try:
            media_count = self.repository.count_media_in_folder(folder)
            if not self._confirm_destructive_delete("pasta", folder, media_count):
                return

            removed = self.repository.delete_library_folder(folder, delete_media=True)
            QMessageBox.information(
                self,
                "Pasta excluída",
                f"A pasta '{folder}' foi excluída da biblioteca.\n"
                f"Registros removidos: {removed}.\n\n"
                "Os vídeos originais no computador não foram apagados.",
            )
            self.current_session_id = None
            self._refresh_folders(keep_current=False)
            self._refresh_seasons(keep_current=False)
            self._load_media_files()
        except Exception as exc:
            logger.error("Erro ao excluir pasta: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao excluir pasta: {exc}")

    def _on_delete_season_clicked(self) -> None:
        """Excluir a temporada selecionada e os registros dentro dela."""
        folder = self.folder_filter.currentText() if hasattr(self, "folder_filter") else "Todas"
        season = self.season_filter.currentText() if hasattr(self, "season_filter") else "Todas"

        if folder in {"", "Todas"}:
            QMessageBox.information(
                self,
                "Excluir Temporada",
                "Selecione primeiro uma pasta específica.",
            )
            return

        if season in {"", "Todas", "Sem temporada"}:
            QMessageBox.information(
                self,
                "Excluir Temporada",
                "Selecione uma temporada específica para excluir. A temporada padrão 'Sem temporada' não pode ser excluída.",
            )
            return

        try:
            media_count = self.repository.count_media_in_season(folder, season)
            label = f"{folder} / {season}"
            if not self._confirm_destructive_delete("temporada", label, media_count):
                return

            removed = self.repository.delete_library_season(folder, season, delete_media=True)
            QMessageBox.information(
                self,
                "Temporada excluída",
                f"A temporada '{season}' foi excluída de '{folder}'.\n"
                f"Registros removidos: {removed}.\n\n"
                "Os vídeos originais no computador não foram apagados.",
            )
            self.current_session_id = None
            self._refresh_seasons(keep_current=False)
            self._load_media_files()
        except Exception as exc:
            logger.error("Erro ao excluir temporada: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao excluir temporada: {exc}")

    def _confirm_destructive_delete(self, item_type: str, item_name: str, media_count: int) -> bool:
        """Confirmar exclusão destrutiva dentro da biblioteca."""
        if media_count > 0:
            message = (
                "⚠️ ATENÇÃO MÁXIMA! ⚠️\n\n"
                f"Você está prestes a EXCLUIR a {item_type}:\n\n"
                f"{item_name}\n\n"
                f"Ela contém {media_count} arquivo(s) registrado(s).\n\n"
                "AO CONFIRMAR, TODOS OS ARQUIVOS DENTRO DELA SERÃO REMOVIDOS DA BIBLIOTECA PARA SEMPRE.\n\n"
                "Essa ação não pode ser desfeita pelo programa.\n\n"
                "Observação: os vídeos originais no seu computador NÃO serão apagados, "
                "mas essa organização e esses registros sairão da biblioteca TEDVHS Studio.\n\n"
                "Deseja realmente continuar?"
            )
            return QMessageBox.warning(
                self,
                "EXCLUSÃO PERMANENTE DA BIBLIOTECA",
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) == QMessageBox.Yes

        message = (
            f"Excluir a {item_type}:\n\n{item_name}\n\n"
            "Ela não contém arquivos registrados. Deseja continuar?"
        )
        return QMessageBox.question(
            self,
            f"Excluir {item_type.capitalize()}",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def _on_move_selected_clicked(self) -> None:
        """Mover arquivos selecionados para outra pasta/temporada."""
        media_ids = self._get_selected_media_ids()
        if not media_ids:
            QMessageBox.information(self, "Mover", "Selecione um ou mais arquivos na tabela.")
            return

        destination = self._ask_destination_folder_season()
        if not destination:
            return

        folder_name, season_name = destination
        self._move_media_ids_with_conflict_handling(media_ids, folder_name, season_name)

    def _ask_destination_folder_season(self) -> Optional[tuple[str, str]]:
        """Perguntar pasta e temporada de destino."""
        folders = self.repository.get_library_folders()
        folder_name, ok = QInputDialog.getItem(
            self,
            "Mover para pasta",
            "Escolha a pasta de destino:",
            folders,
            0,
            False,
        )
        if not ok or not folder_name:
            return None

        seasons = self.repository.get_library_seasons(folder_name)
        season_name, ok = QInputDialog.getItem(
            self,
            "Mover para temporada",
            f"Escolha a temporada dentro de {folder_name}:",
            seasons,
            0,
            False,
        )
        if not ok or not season_name:
            return None

        return folder_name, season_name

    def _move_media_ids_with_conflict_handling(
        self,
        media_ids: list,
        folder_name: str,
        season_name: str,
    ) -> None:
        """Mover mídia tratando conflito de hash e nome como no Windows Explorer."""
        moved = 0
        skipped_duplicate = 0
        skipped_name = 0
        errors = 0

        for media_id in media_ids:
            try:
                media = self.repository.find_by_id(media_id)
                if media is None:
                    errors += 1
                    continue

                hash_conflict = self.repository.find_hash_conflict_in_location(
                    media.hash_info.file_hash,
                    folder_name,
                    season_name,
                    exclude_media_id=media_id,
                )
                if hash_conflict:
                    skipped_duplicate += 1
                    if len(media_ids) == 1:
                        QMessageBox.warning(
                            self,
                            "Vídeo duplicado",
                            "Este mesmo vídeo já existe na pasta/temporada de destino.\n\n"
                            "A movimentação foi negada para evitar duplicidade real.",
                        )
                    continue

                final_name = media.file_info.file_name
                name_conflict = self.repository.find_name_conflict_in_location(
                    final_name,
                    folder_name,
                    season_name,
                    exclude_media_id=media_id,
                )
                if name_conflict:
                    suggested_name = self.repository.generate_unique_file_name(
                        final_name,
                        folder_name,
                        season_name,
                        exclude_media_id=media_id,
                    )
                    reply = QMessageBox.question(
                        self,
                        "Nome já existe",
                        f"Já existe um arquivo chamado:\n\n{final_name}\n\n"
                        f"Deseja mover usando este nome?\n\n{suggested_name}\n\n"
                        "O vídeo original no seu computador não será renomeado; apenas o nome exibido na biblioteca.",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if reply != QMessageBox.Yes:
                        skipped_name += 1
                        continue
                    final_name = suggested_name

                if self.repository.set_media_folder_season(
                    media_id,
                    folder_name,
                    season_name,
                    new_file_name=final_name,
                ):
                    moved += 1
                else:
                    errors += 1

            except Exception as exc:
                logger.error("Erro ao mover mídia %s: %s", media_id, exc, exc_info=True)
                errors += 1
                if len(media_ids) == 1:
                    QMessageBox.critical(self, "Erro", f"Erro ao mover arquivo: {exc}")

        message = f"{moved} arquivo(s) movido(s) para {folder_name} / {season_name}."
        details = []
        if skipped_duplicate:
            details.append(f"{skipped_duplicate} duplicado(s) real(is) ignorado(s)")
        if skipped_name:
            details.append(f"{skipped_name} arquivo(s) não movido(s) por conflito de nome")
        if errors:
            details.append(f"{errors} erro(s)")
        if details:
            message += "\n\n" + "\n".join(details)

        QMessageBox.information(self, "Mover", message)
        self._refresh_folders()
        self._refresh_seasons()
        self._load_media_files()

    def _show_context_menu(self, position) -> None:
        """Mostrar menu com clique direito, estilo Windows Explorer."""
        index = self.table.indexAt(position)
        if index.isValid() and not self.table.selectionModel().isRowSelected(index.row()):
            self.table.clearSelection()
            self.table.selectRow(index.row())

        media_ids = self._get_selected_media_ids()
        if not media_ids:
            return

        menu = QMenu(self)
        open_move = menu.addAction("Mover para pasta/temporada...")
        rename_action = menu.addAction("Renomear na biblioteca...")
        delete_action = menu.addAction("Deletar da biblioteca")
        menu.addSeparator()
        refresh_action = menu.addAction("Atualizar lista")

        rename_action.setEnabled(len(media_ids) == 1)

        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen == open_move:
            destination = self._ask_destination_folder_season()
            if destination:
                self._move_media_ids_with_conflict_handling(media_ids, destination[0], destination[1])
        elif chosen == rename_action and len(media_ids) == 1:
            self._rename_media(media_ids[0])
        elif chosen == delete_action:
            self._on_delete_selected_clicked()
        elif chosen == refresh_action:
            self._on_refresh_clicked()

    def _rename_media(self, media_id) -> None:
        """Renomear apenas o nome exibido na biblioteca."""
        media = self.repository.find_by_id(media_id)
        if media is None:
            QMessageBox.warning(self, "Renomear", "Arquivo não encontrado na biblioteca.")
            return

        folder_name = self._get_media_folder(media)
        season_name = self._get_media_season(media)
        current_name = media.file_info.file_name

        new_name, ok = QInputDialog.getText(
            self,
            "Renomear na biblioteca",
            "Novo nome exibido:",
            text=current_name,
        )
        if not ok:
            return

        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Renomear", "O nome não pode ficar vazio.")
            return

        name_conflict = self.repository.find_name_conflict_in_location(
            new_name,
            folder_name,
            season_name,
            exclude_media_id=media_id,
        )
        if name_conflict:
            suggested_name = self.repository.generate_unique_file_name(
                new_name,
                folder_name,
                season_name,
                exclude_media_id=media_id,
            )
            reply = QMessageBox.question(
                self,
                "Nome já existe",
                f"Já existe um arquivo com esse nome nesta pasta/temporada.\n\n"
                f"Deseja usar este nome?\n\n{suggested_name}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            new_name = suggested_name

        try:
            self.repository.update_media_file_name(media_id, new_name)
            self._load_media_files()
        except Exception as exc:
            logger.error("Erro ao renomear mídia: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao renomear arquivo: {exc}")

    def _on_delete_selected_clicked(self) -> None:
        """Remover todos os itens selecionados da biblioteca."""
        media_ids = self._get_selected_media_ids()
        if not media_ids:
            QMessageBox.information(self, "Deletar", "Selecione um ou mais arquivos.")
            return

        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão",
            f"Remover {len(media_ids)} arquivo(s) da biblioteca?\n\n"
            "Os vídeos originais no computador não serão apagados.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted = 0
        try:
            for media_id in media_ids:
                if self.repository.delete_media_file(media_id):
                    deleted += 1
            QMessageBox.information(self, "Removido", f"{deleted} arquivo(s) removido(s) da biblioteca.")
            self._load_media_files()
        except Exception as exc:
            logger.error("Erro ao deletar mídias: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao deletar arquivos: {exc}")

    def _on_delete_clicked(self, media_id) -> None:
        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão",
            "Remover este arquivo da biblioteca?\n\nO arquivo de vídeo original no seu computador não será apagado.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            deleted = self.repository.delete_media_file(media_id)
            if deleted:
                QMessageBox.information(self, "Removido", "Arquivo removido da biblioteca.")
                self._load_media_files()
            else:
                QMessageBox.warning(self, "Aviso", "Arquivo não encontrado no banco.")
        except Exception as exc:
            logger.error("Erro ao deletar mídia: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao deletar arquivo: {exc}")

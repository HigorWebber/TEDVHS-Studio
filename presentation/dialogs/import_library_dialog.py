"""Diálogo para iniciar importação de biblioteca de mídia."""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
)

from application.media.import_orchestrator import ImportOrchestrator


logger = logging.getLogger(__name__)


class ImportLibraryDialog(QDialog):
    """Diálogo de seleção de pasta para importação."""

    def __init__(self, orchestrator: ImportOrchestrator, parent=None):
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.current_session_id: Optional[str] = None

        self.setWindowTitle("Importar Biblioteca")
        self.setModal(True)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Selecione a pasta com os arquivos de mídia:"))

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Caminho da pasta...")
        path_layout.addWidget(self.path_input)

        browse_button = QPushButton("Selecionar Pasta")
        browse_button.clicked.connect(self._select_folder)
        path_layout.addWidget(browse_button)
        layout.addLayout(path_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        cancel_button = QPushButton("Cancelar")
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_button)

        import_button = QPushButton("Iniciar Importação")
        import_button.clicked.connect(self._start_import)
        buttons_layout.addWidget(import_button)

        layout.addLayout(buttons_layout)

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar Pasta",
            "",
            QFileDialog.ShowDirsOnly,
        )
        if folder:
            self.path_input.setText(folder)

    def _start_import(self) -> None:
        folder_path = self.path_input.text().strip()
        if not folder_path:
            QMessageBox.warning(self, "Aviso", "Selecione uma pasta para importar.")
            return

        try:
            self.current_session_id = self.orchestrator.start_import(folder_path)
            logger.info("Importação iniciada: %s", self.current_session_id)
            self.accept()
        except Exception as exc:
            logger.error("Erro ao iniciar importação: %s", exc, exc_info=True)
            QMessageBox.critical(self, "Erro", f"Falha ao iniciar importação: {exc}")

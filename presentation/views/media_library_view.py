"""View para exibição de biblioteca de mídia importada.

Tabela com arquivos importados, filtros e operações.
"""

import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QComboBox, QLineEdit,
    QHeaderView, QMessageBox, QDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from domain.media.processing_status import ProcessingStatus
from presentation.dialogs.import_library_dialog import ImportLibraryDialog
from application.media.import_orchestrator import ImportOrchestrator


logger = logging.getLogger(__name__)


class MediaLibraryView(QWidget):
    """View para exibição de biblioteca de mídia.
    
    Exibe arquivos importados em tabela, com filtros por status
    e operações como refresh e exclusão.
    """
    
    def __init__(self, repository: SQLiteMediaRepository,
                 orchestrator: ImportOrchestrator,
                 parent=None):
        """Inicializar view.
        
        Args:
            repository: SQLiteMediaRepository
            orchestrator: ImportOrchestrator
            parent: Widget pai
        """
        super().__init__(parent)
        self.repository = repository
        self.orchestrator = orchestrator
        self.current_session_id: Optional[str] = None
        
        self._setup_ui()
        logger.info("MediaLibraryView inicializado")
    
    def _setup_ui(self) -> None:
        """Configurar interface."""
        layout = QVBoxLayout()
        
        # Título
        title = QLabel("Biblioteca de Mídia Importada")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Barra de ferramentas
        toolbar_layout = QHBoxLayout()
        
        # Botão Importar
        self.import_btn = QPushButton("Importar Biblioteca")
        self.import_btn.clicked.connect(self._on_import_clicked)
        toolbar_layout.addWidget(self.import_btn)
        
        # Botão Retomar
        self.resume_btn = QPushButton("Retomar Importação")
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        toolbar_layout.addWidget(self.resume_btn)
        
        # Filtro por status
        toolbar_layout.addWidget(QLabel("Filtrar por Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems([
            "Todos",
            "Pendente",
            "Processando",
            "Concluído",
            "Erro",
            "Duplicado"
        ])
        self.status_filter.currentTextChanged.connect(self._on_filter_changed)
        toolbar_layout.addWidget(self.status_filter)
        
        # Busca
        toolbar_layout.addWidget(QLabel("Buscar:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Nome do arquivo...")
        self.search_input.textChanged.connect(self._on_search_changed)
        toolbar_layout.addWidget(self.search_input)
        
        # Botão Refresh
        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        toolbar_layout.addWidget(self.refresh_btn)
        
        toolbar_layout.addStretch()
        layout.addLayout(toolbar_layout)
        
        # Tabela de arquivos
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Nome do Arquivo",
            "Duração",
            "Resolução",
            "Tamanho",
            "Status",
            "Data",
            "Ações"
        ])
        
        # Configurar header
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        
        # Configurar estilo
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
        
        # Status bar
        self.status_label = QLabel("Nenhum arquivo importado")
        self.status_label.setStyleSheet("color: #cccccc; font-size: 10pt;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
    
    def set_session_id(self, session_id: str) -> None:
        """Definir ID da sessão para exibir arquivos.
        
        Args:
            session_id: ID da sessão de importação
        """
        self.current_session_id = session_id
        self._load_media_files()
    
    def _load_media_files(self) -> None:
        """Carregar arquivos de mídia da sessão atual."""
        try:
            if not self.current_session_id:
                self.table.setRowCount(0)
                self.status_label.setText("Nenhuma sessão carregada")
                return
            
            # Obter arquivos
            media_files = self.repository.find_by_session(self.current_session_id)
            
            if not media_files:
                self.table.setRowCount(0)
                self.status_label.setText(f"Nenhum arquivo importado nesta sessão")
                return
            
            # Preencher tabela
            self.table.setRowCount(len(media_files))
            
            for row, media in enumerate(media_files):
                # Nome
                name_item = QTableWidgetItem(media.file_info.file_name)
                self.table.setItem(row, 0, name_item)
                
                # Duração
                duration = media.video_info.duration.seconds if media.video_info.duration else 0
                hours = int(duration // 3600)
                minutes = int((duration % 3600) // 60)
                seconds = int(duration % 60)
                duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                self.table.setItem(row, 1, QTableWidgetItem(duration_str))
                
                # Resolução
                res_str = ""
                if media.video_info.resolution:
                    res_str = f"{media.video_info.resolution.width}x{media.video_info.resolution.height}"
                self.table.setItem(row, 2, QTableWidgetItem(res_str))
                
                # Tamanho
                size_bytes = media.file_info.file_size.bytes
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024 * 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
                self.table.setItem(row, 3, QTableWidgetItem(size_str))
                
                # Status
                status_item = QTableWidgetItem(media.processing_info.status.value)
                status_color = self._get_status_color(media.processing_info.status)
                status_item.setForeground(status_color)
                self.table.setItem(row, 4, status_item)
                
                # Data
                import_date = media.processing_info.import_date.strftime("%d/%m/%Y %H:%M")
                self.table.setItem(row, 5, QTableWidgetItem(import_date))
                
                # Ações (botão Deletar)
                delete_btn = QPushButton("Deletar")
                delete_btn.setMaximumWidth(80)
                delete_btn.clicked.connect(lambda checked, m_id=media.id: self._on_delete_clicked(m_id))
                self.table.setCellWidget(row, 6, delete_btn)
            
            # Atualizar status
            self.status_label.setText(f"Total: {len(media_files)} arquivo(s)")
            
            logger.info(f"Carregados {len(media_files)} arquivos da sessão {self.current_session_id}")
            
        except Exception as e:
            logger.error(f"Erro ao carregar arquivos: {e}", exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao carregar arquivos: {e}")
    
    def _get_status_color(self, status: ProcessingStatus) -> QColor:
        """Obter cor para o status.
        
        Args:
            status: Status de processamento
            
        Returns:
            QColor apropriada
        """
        colors = {
            ProcessingStatus.READY: QColor(0, 255, 0),  # Verde
            ProcessingStatus.PENDING: QColor(255, 255, 0),  # Amarelo
            ProcessingStatus.PROCESSING: QColor(0, 150, 255),  # Azul
            ProcessingStatus.FAILED: QColor(255, 0, 0),  # Vermelho
            ProcessingStatus.SKIPPED: QColor(150, 150, 150),  # Cinza
        }
        return colors.get(status, QColor(255, 255, 255))  # Branco default
    
    def _on_import_clicked(self) -> None:
        """Abrir dialog de importação."""
        dialog = ImportLibraryDialog(self.orchestrator, self)
        if dialog.exec() == QDialog.Accepted:
            # Atualizar tabela após importação
            if dialog.current_session_id:
                self.set_session_id(dialog.current_session_id)
    
    def _on_resume_clicked(self) -> None:
        """Retomar importação incompleta."""
        sessions = self.orchestrator.get_incomplete_sessions()
        
        if not sessions:
            QMessageBox.information(
                self,
                "Informação",
                "Não há importações incompletas para retomar."
            )
            return
        
        # Mostrar dialog para selecionar sessão
        # (simplificado: usa a primeira)
        session = sessions[0]
        
        reply = QMessageBox.question(
            self,
            "Retomar Importação",
            f"Retomar importação de: {Path(session['folder_path']).name}?\n"
            f"Arquivos importados: {session['total_files_imported']}/{session['total_files_found']}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.orchestrator.resume_import(session['session_id'])
            self.set_session_id(session['session_id'])
    
    def _on_filter_changed(self, text: str) -> None:
        """Manipulador para mudança de filtro."""
        # TODO: Implementar filtragem
        pass
    
    def _on_search_changed(self, text: str) -> None:
        """Manipulador para mudança de busca."""
        # TODO: Implementar busca
        pass
    
    def _on_refresh_clicked(self) -> None:
        """Atualizar view."""
        self._load_media_files()
    
    def _on_delete_clicked(self, media_id) -> None:
        """Deletar arquivo de mídia.
        
        Args:
            media_id: ID do arquivo
        """
        reply = QMessageBox.question(
            self,
            "Confirmar Exclusão",
            "Tem certeza que deseja deletar este arquivo?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # TODO: Implementar deleção
            QMessageBox.information(self, "Informação", "Funcionalidade em desenvolvimento")

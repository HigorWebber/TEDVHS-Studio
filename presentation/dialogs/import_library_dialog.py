"""Dialog para importação de biblioteca de mídia.

Interface para seleção de pasta e exibição de progresso.
"""

import logging
from typing import Optional, Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QFileDialog, QTextEdit, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont

from application.media.import_orchestrator import ImportOrchestrator


logger = logging.getLogger(__name__)


class ImportProgressSignals(QObject):
    """Sinais para atualização de progresso."""
    
    progress_updated = Signal(dict)
    import_completed = Signal(dict)
    import_failed = Signal(str)


class ImportLibraryDialog(QDialog):
    """Dialog para importação de biblioteca de mídia.
    
    Permite seleção de pasta, exibe progresso em tempo real,
    e oferece opção de cancelamento.
    """
    
    def __init__(self, orchestrator: ImportOrchestrator, parent=None):
        """Inicializar dialog.
        
        Args:
            orchestrator: ImportOrchestrator para executar importação
            parent: Widget pai
        """
        super().__init__(parent)
        self.orchestrator = orchestrator
        self.current_session_id: Optional[str] = None
        self.is_importing = False
        
        # Sinais para thread-safe updates
        self.signals = ImportProgressSignals()
        self.signals.progress_updated.connect(self._on_progress_updated)
        self.signals.import_completed.connect(self._on_import_completed)
        self.signals.import_failed.connect(self._on_import_failed)
        
        # Timer para polling de progresso
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self._poll_progress)
        
        self._setup_ui()
        self.setWindowTitle("Importar Biblioteca de Mídia")
        self.resize(600, 400)
        
        logger.info("ImportLibraryDialog inicializado")
    
    def _setup_ui(self) -> None:
        """Configurar interface."""
        layout = QVBoxLayout()
        
        # Título
        title = QLabel("Importar Biblioteca de Mídia")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Seção de seleção de pasta
        folder_layout = QHBoxLayout()
        self.folder_label = QLabel("Nenhuma pasta selecionada")
        self.folder_label.setStyleSheet("color: #cccccc; font-style: italic;")
        folder_layout.addWidget(QLabel("Pasta:"))
        folder_layout.addWidget(self.folder_label, 1)
        
        self.browse_btn = QPushButton("Procurar...")
        self.browse_btn.clicked.connect(self._on_browse_folder)
        folder_layout.addWidget(self.browse_btn)
        
        layout.addLayout(folder_layout)
        
        # Progresso
        layout.addWidget(QLabel("Progresso:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #404040;
                border-radius: 3px;
                background-color: #2d2d2d;
            }
            QProgressBar::chunk {
                background-color: #0d47a1;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Status
        self.status_label = QLabel("Pronto para importar")
        self.status_label.setStyleSheet("color: #cccccc;")
        layout.addWidget(self.status_label)
        
        # Detalhes
        layout.addWidget(QLabel("Detalhes:"))
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setStyleSheet("""
            QTextEdit {
                background-color: #2d2d2d;
                color: #cccccc;
                border: 1px solid #404040;
                font-family: monospace;
                font-size: 9pt;
            }
        """)
        self.details_text.setMaximumHeight(150)
        layout.addWidget(self.details_text)
        
        # Botões
        button_layout = QHBoxLayout()
        
        self.import_btn = QPushButton("Importar")
        self.import_btn.clicked.connect(self._on_import_clicked)
        button_layout.addWidget(self.import_btn)
        
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.cancel_btn)
        
        self.close_btn = QPushButton("Fechar")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _on_browse_folder(self) -> None:
        """Manipulador para botão Procurar."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar Pasta com Arquivos de Mídia",
            str(Path.home())
        )
        
        if folder:
            self.folder_label.setText(folder)
            self.folder_label.setStyleSheet("color: #ffffff;")
            logger.debug(f"Pasta selecionada: {folder}")
    
    def _on_import_clicked(self) -> None:
        """Manipulador para botão Importar."""
        folder = self.folder_label.text()
        
        if folder == "Nenhuma pasta selecionada":
            QMessageBox.warning(
                self,
                "Erro",
                "Por favor, selecione uma pasta para importar."
            )
            return
        
        try:
            self.is_importing = True
            self.import_btn.setEnabled(False)
            self.browse_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.progress_bar.setValue(0)
            self.details_text.clear()
            
            self.status_label.setText("Iniciando importação...")
            
            # Iniciar importação
            self.current_session_id = self.orchestrator.start_import(
                folder,
                progress_callback=self._on_progress
            )
            
            # Iniciar polling de progresso
            self.progress_timer.start(500)
            
            logger.info(f"Importação iniciada: {self.current_session_id}")
            
        except Exception as e:
            logger.error(f"Erro ao iniciar importação: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Erro",
                f"Erro ao iniciar importação: {e}"
            )
            self._reset_ui()
    
    def _on_progress(self, stage: str, current: int = 0, total: int = 0) -> None:
        """Callback de progresso.
        
        Args:
            stage: Etapa de processamento
            current: Progresso atual
            total: Total
        """
        try:
            message = f"{stage}: {current}/{total}" if total > 0 else stage
            self.status_label.setText(message)
            
            if total > 0:
                percentage = int((current / total) * 100)
                self.progress_bar.setValue(percentage)
            
            # Adicionar linha aos detalhes
            self.details_text.append(f"[{stage}] {message}")
            
        except Exception as e:
            logger.error(f"Erro no callback de progresso: {e}")
    
    def _poll_progress(self) -> None:
        """Poll para atualizar progresso da sessão."""
        if not self.current_session_id:
            return
        
        try:
            progress = self.orchestrator.get_session_progress(self.current_session_id)
            
            if progress:
                # Atualizar progress bar
                self.progress_bar.setValue(progress['percentage'])
                
                # Atualizar labels
                imported = progress['total_files_imported']
                found = progress['total_files_found']
                failed = progress['total_files_failed']
                
                status_text = f"Importados: {imported}/{found} | Falhas: {failed}"
                self.status_label.setText(status_text)
                
                # Verificar se concluído
                if progress['status'] == 'COMPLETED':
                    self.progress_timer.stop()
                    self._on_import_completed(progress)
                elif progress['status'] == 'FAILED':
                    self.progress_timer.stop()
                    self._on_import_failed("Importação falhou")
                    
        except Exception as e:
            logger.error(f"Erro ao fazer poll: {e}")
    
    def _on_import_completed(self, stats: dict) -> None:
        """Manipulador para importação concluída.
        
        Args:
            stats: Estatísticas finais
        """
        logger.info(f"Importação concluída: {stats}")
        
        self._reset_ui()
        self.progress_bar.setValue(100)
        
        message = (
            f"Importação concluída!\n\n"
            f"Arquivos encontrados: {stats['total_files_found']}\n"
            f"Arquivos importados: {stats['total_files_imported']}\n"
            f"Falhas: {stats['total_files_failed']}\n"
            f"Duplicatas: {stats['total_files_found'] - stats['total_files_valid']}"
        )
        
        self.status_label.setText("Importação concluída!")
        self.details_text.append("\n=== IMPORTAÇÃO CONCLUÍDA ===")
        self.details_text.append(message)
        
        QMessageBox.information(self, "Sucesso", message)
    
    def _on_import_failed(self, error: str) -> None:
        """Manipulador para importação falha.
        
        Args:
            error: Mensagem de erro
        """
        logger.error(f"Importação falhou: {error}")
        
        self._reset_ui()
        self.status_label.setText(f"Erro: {error}")
        self.details_text.append(f"\n=== ERRO ===")
        self.details_text.append(error)
        
        QMessageBox.critical(self, "Erro", f"Importação falhou: {error}")
    
    def _on_cancel_clicked(self) -> None:
        """Manipulador para botão Cancelar."""
        reply = QMessageBox.question(
            self,
            "Confirmar Cancelamento",
            "Tem certeza que deseja cancelar a importação?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.progress_timer.stop()
            self._reset_ui()
            self.status_label.setText("Cancelado pelo usuário")
            self.details_text.append("\n=== CANCELADO ===")
            logger.info("Importação cancelada pelo usuário")
    
    def _reset_ui(self) -> None:
        """Resetar UI para estado inicial."""
        self.is_importing = False
        self.import_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.current_session_id = None
        self.progress_timer.stop()

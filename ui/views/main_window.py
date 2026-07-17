"""Janela principal da aplicação TEDVHS Studio.

Integra Media Library Engine com interface em PT-BR.
"""

import logging
from typing import Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QStatusBar, QLabel, QTabWidget, QMessageBox
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Qt, QTimer

from core.database.connection import DatabaseConnection
from core.database.migrations import run_migrations
from ui.controllers.main_controller import MainController
from application.media.import_orchestrator import ImportOrchestrator
from application.task_management import TaskScheduler, TaskQueue
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository
from application.media.media_pipeline import MediaPipeline
from application.event_bus import EventBus
from infrastructure.config.configuration_service import ConfigurationService
from infrastructure.media.media_scanner import MediaScanner
from infrastructure.media.media_validator import MediaValidator
from infrastructure.media.media_analyzer import FFprobeAnalyzer
from infrastructure.media.scene_detector import SceneDetector
from presentation.views.media_library_view import MediaLibraryView
from presentation.views.scene_detection_view import SceneDetectionView
from presentation.views.clip_library_view import ClipLibraryView
from presentation.views.montage_editor_view import MontageEditorView


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Janela principal da aplicação TEDVHS Studio.
    
    Coordena a interface e os componentes da UI, integrando:
    - Media Library Engine (Sprint 2.5)
    - Task Management
    - EventBus
    """
    
    def __init__(self) -> None:
        """Inicializar janela principal."""
        super().__init__()
        
        # Inicializar banco de dados e serviços
        self.db_connection: Optional[DatabaseConnection] = None
        self.task_scheduler: Optional[TaskScheduler] = None
        self.repository: Optional[SQLiteMediaRepository] = None
        self.orchestrator: Optional[ImportOrchestrator] = None
        self.event_bus: Optional[EventBus] = None
        self.config_service: Optional[ConfigurationService] = None
        self.media_library_view: Optional[MediaLibraryView] = None
        self.scene_detector: Optional[SceneDetector] = None
        self.scene_detection_view: Optional[SceneDetectionView] = None
        self.clip_library_view: Optional[ClipLibraryView] = None
        self.montage_editor_view: Optional[MontageEditorView] = None
        
        # Inicializar controller
        self.controller = MainController(DatabaseConnection())
        
        # Configurar UI
        self._initialize_services()
        self._setup_ui()
        self._setup_menu()
        self._setup_status_bar()
        
        # Aplicar configurações da janela
        self.setWindowTitle("TEDVHS Studio - Biblioteca, IA e Editor em Camadas")
        self.setGeometry(100, 100, 1360, 860)
        
        logger.info("Janela principal inicializada com sucesso")
    
    def _initialize_services(self) -> None:
        """Inicializar serviços da aplicação."""
        try:
            logger.info("Inicializando serviços...")
            
            # Banco de dados
            self.db_connection = DatabaseConnection()
            self.db_connection.connect()
            run_migrations(self.db_connection)
            
            # Repository
            self.repository = SQLiteMediaRepository(self.db_connection)
            
            # Task Management
            task_queue = TaskQueue(max_concurrent_tasks=4)
            self.task_scheduler = TaskScheduler(task_queue, max_workers=4)
            self.task_scheduler.start()
            
            # Event Bus
            self.event_bus = EventBus()
            
            # Configuração e pipeline de mídia
            self.config_service = ConfigurationService()
            media_scanner = MediaScanner(self.config_service)
            media_validator = MediaValidator()
            media_analyzer = FFprobeAnalyzer(self.config_service)
            self.scene_detector = SceneDetector(self.config_service)
            self.media_pipeline = MediaPipeline(
                scanner=media_scanner,
                validator=media_validator,
                analyzer=media_analyzer,
                repository=self.repository,
                event_bus=self.event_bus,
                config=self.config_service,
            )
            
            # ImportOrchestrator
            self.orchestrator = ImportOrchestrator(
                media_pipeline=self.media_pipeline,
                task_scheduler=self.task_scheduler,
                repository=self.repository,
                event_bus=self.event_bus
            )
            
            logger.info("Serviços inicializados com sucesso")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar serviços: {e}", exc_info=True)
            QMessageBox.critical(self, "Erro", f"Erro ao inicializar serviços: {e}")
            raise
    
    def _setup_ui(self) -> None:
        """Configurar interface principal."""
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Abas
        self.tabs = QTabWidget()
        
        # Aba: Biblioteca de Mídia
        self.media_library_view = MediaLibraryView(
            self.repository,
            self.orchestrator,
            parent=self
        )
        self.tabs.addTab(self.media_library_view, "📚 Biblioteca de Mídia")

        # Aba: Detecção de Cenas
        self.scene_detection_view = SceneDetectionView(
            self.repository,
            self.scene_detector,
            parent=self,
        )
        self.tabs.addTab(self.scene_detection_view, "🎬 Cenas Detectadas")

        # Aba: Biblioteca de Clipes
        self.clip_library_view = ClipLibraryView(
            self.repository,
            parent=self,
        )
        self.tabs.addTab(self.clip_library_view, "🎞️ Biblioteca de Clipes")

        # Aba: Montagem / Editor em Camadas
        self.montage_editor_view = MontageEditorView(
            self.repository,
            parent=self,
        )
        self.tabs.addTab(self.montage_editor_view, "🧩 Montagem / Editor")
        self.clip_library_view.send_to_montage_requested.connect(self._open_clip_in_montage)
        self.montage_editor_view.final_video_exported.connect(self._on_final_video_exported)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        
        # Aba: Configurações (placeholder)
        settings_widget = QWidget()
        settings_layout = QVBoxLayout()
        settings_layout.addWidget(QLabel("Configurações em desenvolvimento..."))
        settings_widget.setLayout(settings_layout)
        self.tabs.addTab(settings_widget, "⚙️ Configurações")
        
        main_layout.addWidget(self.tabs)
    
    def _on_tab_changed(self, index: int) -> None:
        """Ações ao trocar de aba."""
        try:
            current = self.tabs.widget(index)
            if self.scene_detection_view and current is not self.scene_detection_view:
                if hasattr(self.scene_detection_view, "player"):
                    self.scene_detection_view.player.pause()
            if self.clip_library_view and current is not self.clip_library_view:
                if hasattr(self.clip_library_view, "_stop_preview"):
                    self.clip_library_view._stop_preview(clear_source=False)
            if self.montage_editor_view and current is not self.montage_editor_view:
                self.montage_editor_view.pause_players()
            if self.clip_library_view and current is self.clip_library_view:
                self.clip_library_view.refresh_clips()
        except Exception as exc:
            logger.warning("Erro ao processar troca de aba: %s", exc)

    def _open_clip_in_montage(self, clip: object) -> None:
        """Abrir clipe selecionado na aba de montagem."""
        try:
            if not self.montage_editor_view:
                return
            self.montage_editor_view.load_clip(dict(clip or {}))
            index = self.tabs.indexOf(self.montage_editor_view)
            if index >= 0:
                self.tabs.setCurrentIndex(index)
            self.status_label.setText("Clipe enviado para Montagem / Editor")
        except Exception as exc:
            QMessageBox.warning(self, "Montagem", f"Não foi possível abrir o clipe na montagem:\n{exc}")

    def _on_final_video_exported(self, payload: object) -> None:
        """Atualizar biblioteca quando o editor exportar um vídeo final."""
        try:
            if self.clip_library_view:
                self.clip_library_view.refresh_clips()
        except Exception as exc:
            logger.warning("Não foi possível atualizar biblioteca depois do vídeo final: %s", exc)

    def _setup_menu(self) -> None:
        """Configurar menu bar."""
        menubar = self.menuBar()
        
        # Menu Arquivo
        file_menu = menubar.addMenu("&Arquivo")
        
        # Importar Biblioteca
        import_action = QAction("Importar Biblioteca", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._on_import_library)
        file_menu.addAction(import_action)
        
        file_menu.addSeparator()
        
        # Sair
        exit_action = QAction("Sair", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Menu Editar
        edit_menu = menubar.addMenu("&Editar")
        
        # Preferências (placeholder)
        preferences_action = QAction("Preferências", self)
        preferences_action.setShortcut(QKeySequence.Preferences)
        edit_menu.addAction(preferences_action)
        
        # Menu Ajuda
        help_menu = menubar.addMenu("&Ajuda")
        
        # Sobre
        about_action = QAction("Sobre TEDVHS Studio", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)
    
    def _setup_status_bar(self) -> None:
        """Configurar status bar."""
        status_bar = self.statusBar()
        
        self.status_label = QLabel("Pronto")
        status_bar.addWidget(self.status_label)
        
        # Atualizar status periodicamente
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(5000)  # A cada 5 segundos
    
    def _update_status(self) -> None:
        """Atualizar status bar."""
        if self.orchestrator and self.orchestrator.current_session_id:
            progress = self.orchestrator.get_session_progress(
                self.orchestrator.current_session_id
            )
            if progress:
                status = progress.get("status", "IN_PROGRESS")
                stage = progress.get("stage") or status
                status_text = (
                    f"{stage}: {progress.get('percentage', 0)}% | "
                    f"Importados: {progress.get('total_files_imported', 0)} | "
                    f"Duplicados: {progress.get('total_files_duplicate', 0)} | "
                    f"Falhas: {progress.get('total_files_failed', 0)}"
                )
                self.status_label.setText(status_text)
                return
        self.status_label.setText("Pronto")
    
    def _on_import_library(self) -> None:
        """Abre dialog de importação de biblioteca."""
        if self.media_library_view:
            self.media_library_view._on_import_clicked()
            # Mudar para aba de Biblioteca
            self.tabs.setCurrentIndex(0)
    
    def _on_about(self) -> None:
        """Mostrar diálogo Sobre."""
        about_text = (
            "TEDVHS Studio v0.3.0\\n\\n"
            "Importador de biblioteca de mídia com IA integrada.\\n\\n"
            "Features:\\n"
            "• Importação recursiva de vídeos\\n"
            "• Detecção automática de duplicatas\\n"
            "• Extração de metadados com FFprobe\\n"
            "• Persistência em SQLite\\n"
            "• Processamento em background\\n\\n"
            "© 2026 HigorWebber\\n"
            "GitHub: github.com/HigorWebber/TEDVHS-Studio"
        )
        
        QMessageBox.information(self, "Sobre TEDVHS Studio", about_text)
    
    def closeEvent(self, event) -> None:
        """Limpar recursos ao fechar aplicação."""
        try:
            logger.info("Encerrando aplicação...")
            
            # Parar scheduler
            if self.task_scheduler:
                self.task_scheduler.stop()
            
            # Fechar banco de dados
            if self.db_connection:
                self.db_connection.close()
            
            # Parar timers
            self.status_timer.stop()
            
            logger.info("Aplicação encerrada com sucesso")
            event.accept()
            
        except Exception as e:
            logger.error(f"Erro ao encerrar: {e}", exc_info=True)
            event.accept()

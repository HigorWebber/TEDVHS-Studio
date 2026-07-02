"""Janela principal da aplicação."""

import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QStatusBar, QLabel
)
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtCore import Qt

from core.database.connection import DatabaseConnection
from ui.controllers.main_controller import MainController


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Janela principal da aplicação.
    
    Coordena a interface e os componentes da UI.
    """
    
    def __init__(self) -> None:
        """Inicializar janela principal."""
        super().__init__()
        
        # Inicializar controller
        db_connection = DatabaseConnection()
        self.controller = MainController(db_connection)
        
        # Configurar UI
        self._setup_ui()
        self._setup_menu()
        self._setup_status_bar()
        
        logger.info("Janela principal inicializada")
    
    def _setup_ui(self) -> None:
        """Configurar interface principal."""
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Placeholder para conteúdo
        label = QLabel("TEDVHS Studio")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(label)
    
    def _setup_menu(self) -> None:
        """Configurar menu bar."""
        menubar = self.menuBar()
        
        # Menu File
        file_menu = menubar.addMenu("&File")
        
        new_project = QAction("&New Project", self)
        new_project.setShortcut(QKeySequence.New)
        file_menu.addAction(new_project)
        
        open_project = QAction("&Open Project", self)
        open_project.setShortcut(QKeySequence.Open)
        file_menu.addAction(open_project)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Menu Help
        help_menu = menubar.addMenu("&Help")
        about = QAction("&About", self)
        help_menu.addAction(about)
    
    def _setup_status_bar(self) -> None:
        """Configurar status bar."""
        status_bar = self.statusBar()
        status_label = QLabel("Ready")
        status_bar.addWidget(status_label)

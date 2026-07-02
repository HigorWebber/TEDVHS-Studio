"""Barra de status da aplicação."""

import logging
from PySide6.QtWidgets import QStatusBar, QLabel, QProgressBar
from PySide6.QtCore import Qt


logger = logging.getLogger(__name__)


class CustomStatusBar(QStatusBar):
    """Barra de status customizada.
    
    Mostra informações sobre o estado da aplicação.
    """
    
    def __init__(self) -> None:
        """Inicializar barra de status."""
        super().__init__()
        
        # Label de status
        self.status_label = QLabel("Ready")
        self.addWidget(self.status_label)
        
        # Barra de progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.addPermanentWidget(self.progress_bar)
        
        logger.info("Status bar inicializada")
    
    def set_status(self, message: str) -> None:
        """Definir mensagem de status.
        
        Args:
            message: Mensagem a exibir
        """
        self.status_label.setText(message)
    
    def show_progress(self, visible: bool = True) -> None:
        """Mostrar/ocultar barra de progresso.
        
        Args:
            visible: True para mostrar, False para ocultar
        """
        self.progress_bar.setVisible(visible)
    
    def set_progress(self, value: int) -> None:
        """Definir valor da barra de progresso.
        
        Args:
            value: Valor de 0 a 100
        """
        self.progress_bar.setValue(value)

"""Gerenciador de temas da aplicação."""

import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QPalette, QColor


logger = logging.getLogger(__name__)


class ThemeManager:
    """Gerenciador de temas e estilos da aplicação."""
    
    # Cores do tema escuro
    DARK_THEME = {
        'bg_primary': '#1e1e1e',
        'bg_secondary': '#2d2d2d',
        'bg_tertiary': '#3d3d3d',
        'text_primary': '#ffffff',
        'text_secondary': '#cccccc',
        'accent': '#0d47a1',
        'accent_hover': '#1565c0',
        'border': '#404040',
    }
    
    def __init__(self) -> None:
        """Inicializar gerenciador de temas."""
        self.current_theme = self.DARK_THEME
    
    def apply_dark_theme(self, app: QApplication) -> None:
        """Aplicar tema escuro à aplicação.
        
        Args:
            app: Aplicação Qt
        """
        try:
            # Configurar paleta
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor(self.DARK_THEME['bg_primary']))
            palette.setColor(QPalette.WindowText, QColor(self.DARK_THEME['text_primary']))
            palette.setColor(QPalette.Base, QColor(self.DARK_THEME['bg_secondary']))
            palette.setColor(QPalette.AlternateBase, QColor(self.DARK_THEME['bg_tertiary']))
            palette.setColor(QPalette.ToolTipBase, QColor(self.DARK_THEME['bg_secondary']))
            palette.setColor(QPalette.ToolTipText, QColor(self.DARK_THEME['text_primary']))
            palette.setColor(QPalette.Text, QColor(self.DARK_THEME['text_primary']))
            palette.setColor(QPalette.Button, QColor(self.DARK_THEME['bg_secondary']))
            palette.setColor(QPalette.ButtonText, QColor(self.DARK_THEME['text_primary']))
            palette.setColor(QPalette.BrightText, QColor(self.DARK_THEME['text_secondary']))
            palette.setColor(QPalette.Highlight, QColor(self.DARK_THEME['accent']))
            palette.setColor(QPalette.HighlightedText, QColor(self.DARK_THEME['text_primary']))
            
            app.setPalette(palette)
            
            # Aplicar stylesheet
            stylesheet = self._get_stylesheet()
            app.setStyle('Fusion')
            app.setStyleSheet(stylesheet)
            
            logger.info("Tema escuro aplicado com sucesso")
            
        except Exception as e:
            logger.error(f"Erro ao aplicar tema: {e}", exc_info=True)
            raise
    
    def _get_stylesheet(self) -> str:
        """Gerar stylesheet CSS.
        
        Returns:
            CSS stylesheet
        """
        theme = self.DARK_THEME
        return f"""
            QMainWindow {{
                background-color: {theme['bg_primary']};
                color: {theme['text_primary']};
            }}
            
            QWidget {{
                background-color: {theme['bg_primary']};
                color: {theme['text_primary']};
            }}
            
            QPushButton {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border']};
                padding: 5px;
                border-radius: 3px;
            }}
            
            QPushButton:hover {{
                background-color: {theme['accent']};
                border: 1px solid {theme['accent']};
            }}
            
            QPushButton:pressed {{
                background-color: {theme['accent_hover']};
            }}
            
            QLineEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border']};
                padding: 5px;
                border-radius: 3px;
            }}
            
            QTextEdit {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border']};
                padding: 5px;
                border-radius: 3px;
            }}
            
            QComboBox {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border']};
                padding: 5px;
                border-radius: 3px;
            }}
            
            QScrollBar:vertical {{
                background-color: {theme['bg_secondary']};
                border: 1px solid {theme['border']};
                width: 12px;
            }}
            
            QScrollBar::handle:vertical {{
                background-color: {theme['accent']};
                border-radius: 6px;
            }}
            
            QScrollBar::handle:vertical:hover {{
                background-color: {theme['accent_hover']};
            }}
            
            QStatusBar {{
                background-color: {theme['bg_secondary']};
                color: {theme['text_primary']};
                border-top: 1px solid {theme['border']};
            }}
        """

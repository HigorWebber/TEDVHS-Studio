"""Aplicação principal TEDVHS Studio."""

import sys
import logging
from typing import NoReturn

from PySide6.QtWidgets import QApplication

from config import APP_TITLE, WINDOW_WIDTH, WINDOW_HEIGHT
from core.logger import setup_logger
from core.database.connection import DatabaseConnection
from core.database.migrations import run_migrations
from ui.views.main_window import MainWindow
from ui.theme.theme_manager import ThemeManager


logger = logging.getLogger(__name__)


def initialize_application() -> None:
    """Inicializar aplicação.
    
    Configura:
    - Sistema de logging
    - Banco de dados
    - Temas
    
    Raises:
        RuntimeError: Se inicialização falhar
    """
    try:
        # Configurar logging
        setup_logger()
        logger.info(f"Iniciando {APP_TITLE}")
        
        # Inicializar banco de dados
        logger.info("Inicializando banco de dados")
        db_connection = DatabaseConnection()
        db_connection.connect()
        
        # Executar migrações
        logger.info("Executando migrações do banco de dados")
        run_migrations(db_connection)
        
        logger.info("Aplicação inicializada com sucesso")
        
    except Exception as e:
        logger.error(f"Erro ao inicializar aplicação: {e}", exc_info=True)
        raise RuntimeError(f"Falha ao inicializar aplicação: {e}")


def main() -> NoReturn:
    """Ponto de entrada principal da aplicação.
    
    Cria a aplicação Qt e mostra a janela principal.
    """
    try:
        # Inicializar aplicação
        initialize_application()
        
        # Criar aplicação Qt
        app = QApplication(sys.argv)
        
        # Configurar tema
        logger.info("Carregando tema da aplicação")
        theme_manager = ThemeManager()
        theme_manager.apply_dark_theme(app)
        
        # Criar janela principal
        logger.info("Criando janela principal")
        main_window = MainWindow()
        main_window.setWindowTitle(APP_TITLE)
        main_window.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        main_window.show()
        
        logger.info("Interface carregada com sucesso")
        
        # Executar aplicação
        sys.exit(app.exec())
        
    except Exception as e:
        logger.error(f"Erro fatal na aplicação: {e}", exc_info=True)
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

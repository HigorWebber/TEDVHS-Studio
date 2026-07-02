"""Sistema de logging para TEDVHS Studio."""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False

from config import LOG_FILE, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOGS_DIR


# Logger global
_logger: Optional[logging.Logger] = None


def setup_logger(
    name: str = "tedvhs_studio",
    level: Optional[str] = None
) -> logging.Logger:
    """Configurar logger da aplicação.
    
    Args:
        name: Nome do logger
        level: Nível de log (padrão: LOG_LEVEL de config)
        
    Returns:
        Logger configurado
    """
    global _logger
    
    if _logger is not None:
        return _logger
    
    # Criar logger
    logger = logging.getLogger(name)
    logger.setLevel(level or LOG_LEVEL)
    
    # Criar diretório de logs se não existir
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Handler para arquivo
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(LOG_LEVEL)
    file_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Handler para console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    
    if HAS_COLORLOG:
        # Usar colorlog se disponível
        console_formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s%(reset)s",
            datefmt=LOG_DATE_FORMAT,
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
    else:
        console_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    _logger = logger
    return logger


def get_logger(name: str = "tedvhs_studio") -> logging.Logger:
    """Obter logger da aplicação.
    
    Args:
        name: Nome do logger
        
    Returns:
        Logger da aplicação
    """
    return logging.getLogger(name)

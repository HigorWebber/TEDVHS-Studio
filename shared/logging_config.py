"""Structured logging configuration."""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional
import json
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """Formatter that outputs structured logs in JSON format."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        Args:
            record: Log record
            
        Returns:
            JSON formatted log line
        """
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(log_dir: Path, debug: bool = False) -> None:
    """Configure structured logging for all modules.
    
    Creates separate log files for:
    - application: General application logs
    - errors: Error and exception logs
    - database: Database operation logs
    - processing: Media processing logs
    - ai: AI module logs
    
    Args:
        log_dir: Directory to store log files
        debug: Enable debug logging
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Application logs
    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'application.log',
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(app_handler)
    
    # Error logs
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'errors.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(error_handler)
    
    # Database logs
    db_logger = logging.getLogger('database')
    db_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'database.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=3
    )
    db_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    db_handler.setFormatter(StructuredFormatter())
    db_logger.addHandler(db_handler)
    
    # Processing logs
    proc_logger = logging.getLogger('processing')
    proc_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'processing.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=3
    )
    proc_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    proc_handler.setFormatter(StructuredFormatter())
    proc_logger.addHandler(proc_handler)
    
    # Console handler for debug mode
    if debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
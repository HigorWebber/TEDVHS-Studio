"""Configurações centrais da aplicação TEDVHS Studio."""

import os
from pathlib import Path


# Diretórios base
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
PROJECTS_DIR = BASE_DIR / "projects"

# Aplicação
APP_TITLE = "TEDVHS Studio"
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800

# Banco de dados
DATABASE_PATH = Path(os.getenv("TEDVHS_DATABASE_PATH", str(DATA_DIR / "tedvhs_studio.db")))
DATABASE_TIMEOUT = 30.0
DATABASE_JOURNAL_MODE = "WAL"
DATABASE_SYNCHRONOUS = "NORMAL"
DATABASE_CACHE_SIZE = -64000

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE = LOGS_DIR / "tedvhs.log"

"""Gerenciamento de conexão com banco de dados."""

import sqlite3
import logging
from typing import Optional
from pathlib import Path

from config import (
    DATABASE_PATH,
    DATABASE_TIMEOUT,
    DATABASE_JOURNAL_MODE,
    DATABASE_SYNCHRONOUS,
    DATABASE_CACHE_SIZE,
)


logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Gerenciador de conexão SQLite.
    
    Implementa singleton pattern para garantir apenas uma conexão ativa.
    """
    
    _instance: Optional['DatabaseConnection'] = None
    _connection: Optional[sqlite3.Connection] = None
    
    def __new__(cls) -> 'DatabaseConnection':
        """Implementar singleton."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Inicializar gerenciador de conexão."""
        self.db_path: Path = DATABASE_PATH
    
    def connect(self) -> sqlite3.Connection:
        """Conectar ao banco de dados.
        
        Returns:
            Conexão com o banco de dados
            
        Raises:
            sqlite3.Error: Se houver erro ao conectar
        """
        if self._connection is not None:
            return self._connection
        
        try:
            logger.info(f"Conectando ao banco de dados: {self.db_path}")
            
            # Garantir que o diretório existe
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Criar conexão
            self._connection = sqlite3.connect(
                str(self.db_path),
                timeout=DATABASE_TIMEOUT,
                check_same_thread=False
            )
            
            # Configurar conexão
            self._connection.execute(f"PRAGMA journal_mode = {DATABASE_JOURNAL_MODE}")
            self._connection.execute(f"PRAGMA synchronous = {DATABASE_SYNCHRONOUS}")
            self._connection.execute(f"PRAGMA cache_size = {DATABASE_CACHE_SIZE}")
            self._connection.execute("PRAGMA foreign_keys = ON")
            
            logger.info("Conexão com banco de dados estabelecida com sucesso")
            return self._connection
            
        except sqlite3.Error as e:
            logger.error(f"Erro ao conectar ao banco de dados: {e}", exc_info=True)
            raise
    
    def get_connection(self) -> sqlite3.Connection:
        """Obter conexão ativa.
        
        Returns:
            Conexão com o banco de dados
            
        Raises:
            RuntimeError: Se não há conexão ativa
        """
        if self._connection is None:
            raise RuntimeError("Nenhuma conexão ativa. Chame connect() primeiro.")
        return self._connection
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Executar comando SQL.
        
        Args:
            sql: Comando SQL
            params: Parâmetros do comando
            
        Returns:
            Cursor com resultados
            
        Raises:
            sqlite3.Error: Se houver erro ao executar
        """
        try:
            connection = self.get_connection()
            cursor = connection.cursor()
            cursor.execute(sql, params)
            return cursor
        except sqlite3.Error as e:
            logger.error(f"Erro ao executar SQL: {e}\nSQL: {sql}", exc_info=True)
            raise
    
    def executemany(self, sql: str, params_list: list) -> sqlite3.Cursor:
        """Executar múltiplos comandos SQL.
        
        Args:
            sql: Comando SQL
            params_list: Lista de parâmetros
            
        Returns:
            Cursor com resultados
        """
        try:
            connection = self.get_connection()
            cursor = connection.cursor()
            cursor.executemany(sql, params_list)
            connection.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"Erro ao executar múltiplos SQL: {e}", exc_info=True)
            raise
    
    def commit(self) -> None:
        """Confirmar transação.
        
        Raises:
            RuntimeError: Se não há conexão ativa
        """
        connection = self.get_connection()
        connection.commit()
    
    def rollback(self) -> None:
        """Reverter transação.
        
        Raises:
            RuntimeError: Se não há conexão ativa
        """
        connection = self.get_connection()
        connection.rollback()
    
    def close(self) -> None:
        """Fechar conexão."""
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("Conexão com banco de dados fechada")
            except sqlite3.Error as e:
                logger.error(f"Erro ao fechar conexão: {e}", exc_info=True)
            finally:
                self._connection = None
    
    def __enter__(self) -> 'DatabaseConnection':
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

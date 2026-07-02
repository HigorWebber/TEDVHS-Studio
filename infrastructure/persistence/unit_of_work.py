"""Unit of Work pattern for transaction management."""

import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

from core.database.connection import DatabaseConnection
from infrastructure.persistence.repositories import Repository


logger = logging.getLogger('database')


class UnitOfWork:
    """Manages database transactions and repositories.
    
    Ensures atomicity of operations across multiple repositories.
    """
    
    def __init__(self, connection: DatabaseConnection):
        """Initialize Unit of Work.
        
        Args:
            connection: Database connection
        """
        self.connection = connection
        self.repositories: Dict[str, Repository] = {}
        self._transaction_active = False
        logger.debug("UnitOfWork initialized")
    
    def get_repository(self, table_name: str) -> Repository:
        """Get or create repository.
        
        Args:
            table_name: Table name
            
        Returns:
            Repository instance
        """
        if table_name not in self.repositories:
            self.repositories[table_name] = Repository(self.connection, table_name)
        return self.repositories[table_name]
    
    @contextmanager
    def transaction(self):
        """Context manager for database transaction.
        
        Yields:
            UnitOfWork instance
            
        Example:
            with unit_of_work.transaction():
                repo.create(data)
                # Automatically commits on success or rolls back on exception
        """
        try:
            logger.debug("Transaction started")
            self._transaction_active = True
            yield self
            self.commit()
            logger.debug("Transaction committed")
        except Exception as e:
            self.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
            raise
        finally:
            self._transaction_active = False
    
    def commit(self) -> None:
        """Commit transaction."""
        if self._transaction_active:
            self.connection.commit()
            logger.debug("Transaction committed")
    
    def rollback(self) -> None:
        """Rollback transaction."""
        if self._transaction_active:
            self.connection.rollback()
            logger.debug("Transaction rolled back")
    
    def close(self) -> None:
        """Close unit of work."""
        self.repositories.clear()
        logger.debug("UnitOfWork closed")

"""Data repositories with type safety."""

import logging
from typing import Any, List, Optional, Dict, Protocol

from core.database.connection import DatabaseConnection


logger = logging.getLogger('database')


class IRepository(Protocol):
    """Protocol for repository implementations."""
    
    def find_by_id(self, item_id: int) -> Optional[Dict[str, Any]]: ...
    def find_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]: ...
    def create(self, data: Dict[str, Any]) -> int: ...
    def update(self, item_id: int, data: Dict[str, Any]) -> bool: ...
    def delete(self, item_id: int) -> bool: ...


class Repository:
    """Generic repository implementation."""
    
    def __init__(self, connection: DatabaseConnection, table_name: str) -> None:
        """Initialize repository.
        
        Args:
            connection: Database connection
            table_name: Table name
        """
        self.connection = connection
        self.table_name = table_name
    
    def find_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Find by ID."""
        try:
            sql = f"SELECT * FROM {self.table_name} WHERE id = ?"
            cursor = self.connection.execute(sql, (item_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_dict(cursor, row)
            return None
            
        except Exception as e:
            logger.error(f"Repository error: {e}", exc_info=True)
            raise
    
    def find_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """Find all."""
        try:
            sql = f"SELECT * FROM {self.table_name}"
            params = []
            
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params = [limit, offset]
            
            cursor = self.connection.execute(sql, tuple(params))
            rows = cursor.fetchall()
            
            return [self._row_to_dict(cursor, row) for row in rows]
            
        except Exception as e:
            logger.error(f"Repository error: {e}", exc_info=True)
            raise
    
    def create(self, data: Dict[str, Any]) -> int:
        """Create record."""
        try:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?" for _ in data])
            sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
            
            cursor = self.connection.execute(sql, tuple(data.values()))
            self.connection.commit()
            
            return cursor.lastrowid
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Repository error: {e}", exc_info=True)
            raise
    
    def update(self, item_id: int, data: Dict[str, Any]) -> bool:
        """Update record."""
        try:
            set_clause = ", ".join([f"{key} = ?" for key in data.keys()])
            values = list(data.values()) + [item_id]
            sql = f"UPDATE {self.table_name} SET {set_clause} WHERE id = ?"
            
            cursor = self.connection.execute(sql, tuple(values))
            self.connection.commit()
            
            return cursor.rowcount > 0
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Repository error: {e}", exc_info=True)
            raise
    
    def delete(self, item_id: int) -> bool:
        """Delete record."""
        try:
            sql = f"DELETE FROM {self.table_name} WHERE id = ?"
            cursor = self.connection.execute(sql, (item_id,))
            self.connection.commit()
            
            return cursor.rowcount > 0
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Repository error: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _row_to_dict(cursor, row: tuple) -> Dict[str, Any]:
        """Convert row to dict."""
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

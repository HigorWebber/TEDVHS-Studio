"""Padrão Repository para acesso a dados."""

import logging
from typing import Any, List, Optional, Dict

from core.database.connection import DatabaseConnection


logger = logging.getLogger(__name__)


class Repository:
    """Classe base para repositórios de dados.
    
    Implementa o padrão Repository para abstrair acesso a dados.
    """
    
    def __init__(self, connection: DatabaseConnection, table_name: str) -> None:
        """Inicializar repositório.
        
        Args:
            connection: Conexão com banco de dados
            table_name: Nome da tabela
        """
        self.connection = connection
        self.table_name = table_name
    
    def find_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Buscar registro por ID.
        
        Args:
            item_id: ID do registro
            
        Returns:
            Dicionário com dados ou None se não encontrar
        """
        try:
            sql = f"SELECT * FROM {self.table_name} WHERE id = ?"
            cursor = self.connection.execute(sql, (item_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_dict(cursor, row)
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar {self.table_name} por ID: {e}", exc_info=True)
            raise
    
    def find_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """Buscar todos os registros.
        
        Args:
            limit: Limite de resultados
            offset: Deslocamento
            
        Returns:
            Lista de registros
        """
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
            logger.error(f"Erro ao buscar todos os {self.table_name}: {e}", exc_info=True)
            raise
    
    def create(self, data: Dict[str, Any]) -> int:
        """Criar novo registro.
        
        Args:
            data: Dados do registro
            
        Returns:
            ID do registro criado
        """
        try:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?" for _ in data])
            sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})"
            
            cursor = self.connection.execute(sql, tuple(data.values()))
            self.connection.commit()
            
            return cursor.lastrowid
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Erro ao criar {self.table_name}: {e}", exc_info=True)
            raise
    
    def update(self, item_id: int, data: Dict[str, Any]) -> bool:
        """Atualizar registro.
        
        Args:
            item_id: ID do registro
            data: Dados a atualizar
            
        Returns:
            True se atualizado com sucesso
        """
        try:
            set_clause = ", ".join([f"{key} = ?" for key in data.keys()])
            values = list(data.values()) + [item_id]
            sql = f"UPDATE {self.table_name} SET {set_clause} WHERE id = ?"
            
            cursor = self.connection.execute(sql, tuple(values))
            self.connection.commit()
            
            return cursor.rowcount > 0
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Erro ao atualizar {self.table_name}: {e}", exc_info=True)
            raise
    
    def delete(self, item_id: int) -> bool:
        """Deletar registro.
        
        Args:
            item_id: ID do registro
            
        Returns:
            True se deletado com sucesso
        """
        try:
            sql = f"DELETE FROM {self.table_name} WHERE id = ?"
            cursor = self.connection.execute(sql, (item_id,))
            self.connection.commit()
            
            return cursor.rowcount > 0
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Erro ao deletar {self.table_name}: {e}", exc_info=True)
            raise
    
    def count(self) -> int:
        """Contar registros.
        
        Returns:
            Total de registros
        """
        try:
            sql = f"SELECT COUNT(*) FROM {self.table_name}"
            cursor = self.connection.execute(sql)
            result = cursor.fetchone()
            return result[0] if result else 0
            
        except Exception as e:
            logger.error(f"Erro ao contar {self.table_name}: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _row_to_dict(cursor, row: tuple) -> Dict[str, Any]:
        """Converter linha do banco em dicionário.
        
        Args:
            cursor: Cursor do banco
            row: Linha da query
            
        Returns:
            Dicionário com dados
        """
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))

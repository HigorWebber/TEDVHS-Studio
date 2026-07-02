"""Controlador principal da aplicação."""

import logging
from typing import Optional

from core.database.connection import DatabaseConnection
from core.services.project_service import ProjectService


logger = logging.getLogger(__name__)


class MainController:
    """Controlador principal da aplicação.
    
    Gerencia a lógica de negócio e comunicação entre view e services.
    """
    
    def __init__(self, db_connection: DatabaseConnection) -> None:
        """Inicializar controlador.
        
        Args:
            db_connection: Conexão com banco de dados
        """
        self.db_connection = db_connection
        self.project_service = ProjectService(db_connection)
        self.current_project: Optional[dict] = None
    
    def create_project(self, name: str, description: Optional[str] = None) -> int:
        """Criar novo projeto.
        
        Args:
            name: Nome do projeto
            description: Descrição
            
        Returns:
            ID do projeto criado
        """
        try:
            project_id = self.project_service.create_project(name, description)
            logger.info(f"Projeto '{name}' criado (ID: {project_id})")
            return project_id
        except Exception as e:
            logger.error(f"Erro ao criar projeto: {e}", exc_info=True)
            raise
    
    def open_project(self, project_id: int) -> Optional[dict]:
        """Abrir projeto.
        
        Args:
            project_id: ID do projeto
            
        Returns:
            Dados do projeto ou None
        """
        try:
            self.current_project = self.project_service.open_project(project_id)
            return self.current_project
        except Exception as e:
            logger.error(f"Erro ao abrir projeto: {e}", exc_info=True)
            raise
    
    def list_projects(self) -> list:
        """Listar todos os projetos.
        
        Returns:
            Lista de projetos
        """
        try:
            return self.project_service.list_projects()
        except Exception as e:
            logger.error(f"Erro ao listar projetos: {e}", exc_info=True)
            raise

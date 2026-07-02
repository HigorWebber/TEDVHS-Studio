"""Serviço de gerenciamento de projetos."""

import logging
from typing import Optional, List, Dict, Any
from pathlib import Path

from core.database.connection import DatabaseConnection
from core.database.repository import Repository
from config import PROJECTS_DIR


logger = logging.getLogger(__name__)


class ProjectService:
    """Serviço para gerenciar projetos.
    
    Implementa regras de negócio para operações com projetos.
    """
    
    def __init__(self, connection: DatabaseConnection) -> None:
        """Inicializar serviço.
        
        Args:
            connection: Conexão com banco de dados
        """
        self.connection = connection
        self.repository = Repository(connection, "project")
    
    def create_project(
        self,
        name: str,
        description: Optional[str] = None
    ) -> int:
        """Criar novo projeto.
        
        Args:
            name: Nome do projeto
            description: Descrição do projeto
            
        Returns:
            ID do projeto criado
            
        Raises:
            ValueError: Se dados inválidos
            RuntimeError: Se erro ao criar
        """
        if not name or not name.strip():
            raise ValueError("Nome do projeto não pode estar vazio")
        
        try:
            # Criar diretório do projeto
            project_dir = PROJECTS_DIR / name
            project_dir.mkdir(parents=True, exist_ok=True)
            
            # Criar subdiretórios
            (project_dir / "clips").mkdir(exist_ok=True)
            (project_dir / "thumbnails").mkdir(exist_ok=True)
            
            logger.info(f"Diretórios do projeto '{name}' criados em {project_dir}")
            
            # Registrar no banco de dados
            data = {
                "name": name,
                "description": description,
                "directory": str(project_dir)
            }
            
            project_id = self.repository.create(data)
            logger.info(f"Projeto '{name}' criado com sucesso (ID: {project_id})")
            
            return project_id
            
        except Exception as e:
            logger.error(f"Erro ao criar projeto: {e}", exc_info=True)
            raise RuntimeError(f"Falha ao criar projeto: {e}")
    
    def open_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Abrir projeto existente.
        
        Args:
            project_id: ID do projeto
            
        Returns:
            Dados do projeto ou None
        """
        try:
            project = self.repository.find_by_id(project_id)
            
            if project:
                logger.info(f"Projeto '{project['name']}' aberto")
            else:
                logger.warning(f"Projeto com ID {project_id} não encontrado")
            
            return project
            
        except Exception as e:
            logger.error(f"Erro ao abrir projeto: {e}", exc_info=True)
            raise
    
    def save_project(self, project_id: int, data: Dict[str, Any]) -> bool:
        """Salvar dados do projeto.
        
        Args:
            project_id: ID do projeto
            data: Dados a atualizar
            
        Returns:
            True se salvo com sucesso
        """
        try:
            success = self.repository.update(project_id, data)
            
            if success:
                logger.info(f"Projeto ID {project_id} salvo com sucesso")
            else:
                logger.warning(f"Projeto ID {project_id} não encontrado para atualizar")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao salvar projeto: {e}", exc_info=True)
            raise
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """Listar todos os projetos.
        
        Returns:
            Lista de projetos
        """
        try:
            projects = self.repository.find_all()
            logger.info(f"Total de projetos: {len(projects)}")
            return projects
            
        except Exception as e:
            logger.error(f"Erro ao listar projetos: {e}", exc_info=True)
            raise
    
    def delete_project(self, project_id: int) -> bool:
        """Deletar projeto.
        
        Args:
            project_id: ID do projeto
            
        Returns:
            True se deletado com sucesso
        """
        try:
            project = self.repository.find_by_id(project_id)
            
            if not project:
                logger.warning(f"Projeto ID {project_id} não encontrado")
                return False
            
            # Deletar do banco de dados
            success = self.repository.delete(project_id)
            
            if success:
                logger.info(f"Projeto '{project['name']}' deletado")
            
            return success
            
        except Exception as e:
            logger.error(f"Erro ao deletar projeto: {e}", exc_info=True)
            raise

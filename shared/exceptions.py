"""Hierarquia centralizada de exceções compartilhadas."""


class MediaException(Exception):
    """Exceção base para falhas relacionadas à mídia."""


class ValidationException(MediaException):
    """Lançada quando validações de domínio falham."""


class ProcessingException(MediaException):
    """Lançada quando ocorre falha no processamento de mídia."""


class MediaProcessingException(ProcessingException):
    """Alias semântico para compatibilidade com código legado."""


class DuplicateException(ProcessingException):
    """Lançada quando um arquivo duplicado é detectado."""


class StateTransitionException(ProcessingException):
    """Lançada quando uma transição de estado é inválida."""


class InvalidStateTransitionException(StateTransitionException):
    """Nome legado mantido por compatibilidade."""


class MetadataException(ProcessingException):
    """Lançada quando extração de metadados falha."""


class RepositoryException(ProcessingException):
    """Lançada em falhas de persistência."""


class HashCalculationException(ProcessingException):
    """Lançada quando cálculo de hash falha."""

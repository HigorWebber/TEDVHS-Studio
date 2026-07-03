"""Hierarquia centralizada de exceções compartilhadas."""


class MediaException(Exception):
    """Exceção base para falhas relacionadas à mídia."""


class ValidationException(MediaException):
    """Lançada quando validações de domínio falham."""


class MediaProcessingException(MediaException):
    """Lançada quando ocorre falha no processamento de mídia."""


class ProcessingException(MediaProcessingException):
    """Alias semântico para erros de processamento no pipeline."""


class DuplicateException(MediaProcessingException):
    """Lançada quando um arquivo duplicado é detectado."""


class StateTransitionException(MediaProcessingException):
    """Lançada quando uma transição de estado é inválida."""


class InvalidStateTransitionException(StateTransitionException):
    """Nome legado mantido por compatibilidade."""


class MetadataException(MediaProcessingException):
    """Lançada quando extração de metadados falha."""


class RepositoryException(MediaProcessingException):
    """Lançada em falhas de persistência."""


class HashCalculationException(MediaProcessingException):
    """Lançada quando cálculo de hash falha."""

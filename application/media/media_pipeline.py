"""Media pipeline for orchestrating import workflow.

Coordinates all stages of media import:
Scanning -> Validation -> Hashing -> Analysis -> Persistence -> Events
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from uuid import uuid4

from application.event_bus import EventBus
from domain.media.events import (
    DuplicateDetectedEvent,
    ImportCompletedEvent,
    ImportStartedEvent,
    MediaDiscoveredEvent,
    MediaImportedEvent,
    MediaValidatedEvent,
    MetadataExtractedEvent,
)
from domain.media.exceptions import ProcessingException
from domain.media.media_file import (
    AudioInfo,
    FileInfo,
    HashInfo,
    MediaFile,
    ProcessingInfo,
    VideoInfo,
)
from domain.media.media_state_machine import MediaStateMachine
from domain.media.processing_status import ProcessingStatus
from domain.media.value_objects import FileSize
from infrastructure.config.configuration_service import ConfigurationService
from infrastructure.media.hash_calculator import HashCalculator
from infrastructure.media.media_analyzer import FFprobeAnalyzer
from infrastructure.media.media_repository import IMediaRepository
from infrastructure.media.media_scanner import MediaFileCandidate, MediaScanner
from infrastructure.media.media_validator import MediaValidator


logger = logging.getLogger(__name__)


class MediaPipeline:
    """Orquestra o processamento de importação de arquivos de mídia."""

    def __init__(
        self,
        scanner: MediaScanner,
        validator: MediaValidator,
        analyzer: FFprobeAnalyzer,
        repository: IMediaRepository,
        event_bus: EventBus,
        config: ConfigurationService,
    ):
        self._scanner = scanner
        self._validator = validator
        self._analyzer = analyzer
        self._repository = repository
        self._event_bus = event_bus
        self._config = config
        self._state_machine = MediaStateMachine()
        logger.info("MediaPipeline initialized")

    def process_directory(
        self,
        root_path: str,
        import_session_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
        pause_callback: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Processar uma pasta inteira para importação."""
        session_id = import_session_id or str(uuid4())
        return self._process_import(
            source_label=str(root_path),
            import_session_id=session_id,
            candidates_provider=lambda: self._scanner.scan(root_path),
            progress_callback=progress_callback,
            cancel_checker=cancel_checker,
            pause_callback=pause_callback,
        )

    def process_files(
        self,
        file_paths: Iterable[str],
        import_session_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
        pause_callback: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        """Processar arquivos selecionados individualmente."""
        paths = [str(path) for path in file_paths]
        session_id = import_session_id or str(uuid4())
        return self._process_import(
            source_label=f"{len(paths)} arquivo(s) selecionado(s)",
            import_session_id=session_id,
            candidates_provider=lambda: self._build_candidates_from_files(paths),
            progress_callback=progress_callback,
            cancel_checker=cancel_checker,
            pause_callback=pause_callback,
        )

    def _build_candidates_from_files(self, file_paths: Iterable[str]) -> List[MediaFileCandidate]:
        """Criar candidatos a partir de arquivos escolhidos na interface."""
        candidates: List[MediaFileCandidate] = []
        for raw_path in file_paths:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                logger.warning("Arquivo selecionado inválido ignorado: %s", raw_path)
                continue

            try:
                candidate = self._scanner._check_file(path)  # compatibilidade com scanner existente
            except Exception as exc:
                logger.warning("Erro ao avaliar arquivo %s: %s", raw_path, exc)
                candidate = None

            if candidate:
                candidates.append(candidate)
            else:
                logger.info("Arquivo selecionado não suportado/ignorado: %s", raw_path)
        return candidates

    def _process_import(
        self,
        source_label: str,
        import_session_id: str,
        candidates_provider: Callable[[], List[MediaFileCandidate]],
        progress_callback: Optional[Callable] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
        pause_callback: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        start_time = datetime.utcnow()
        logger.info("Starting import session: %s", import_session_id)
        self._event_bus.emit(ImportStartedEvent(
            import_session_id=import_session_id,
            folder_path=source_label,
        ))

        stats: Dict[str, Any] = {
            "import_session_id": import_session_id,
            "folders_scanned": 0,
            "files_found": 0,
            "files_valid": 0,
            "files_imported": 0,
            "files_duplicate": 0,
            "files_failed": 0,
            "total_size_bytes": 0,
            "total_duration_seconds": 0,
            "cancelled": False,
        }

        def emit_progress(stage: str, current: int = 0, total: int = 0,
                          current_file: Optional[str] = None) -> None:
            if not progress_callback:
                return
            try:
                progress_callback(stage, current, total, dict(stats), current_file)
            except TypeError:
                progress_callback(stage, current, total)

        def should_cancel() -> bool:
            return bool(cancel_checker and cancel_checker())

        try:
            emit_progress("Localizando arquivos", 0, 0)

            candidates = candidates_provider()
            stats["files_found"] = len(candidates)
            stats["folders_scanned"] = 1
            emit_progress("Arquivos encontrados", len(candidates), len(candidates))

            if should_cancel():
                stats["cancelled"] = True
                return self._finalize_stats(stats, start_time, emit_progress)

            valid_candidates, failed = self._validator.validate_batch(candidates)
            stats["files_valid"] = len(valid_candidates)
            stats["files_failed"] = len(failed)
            emit_progress("Arquivos validados", len(valid_candidates), len(candidates))

            logger.info("Processing %s valid media files", len(valid_candidates))
            total_to_process = len(valid_candidates)

            for index, candidate in enumerate(valid_candidates, start=1):
                if pause_callback:
                    pause_callback()

                if should_cancel():
                    stats["cancelled"] = True
                    break

                emit_progress(
                    "Processando arquivo",
                    index - 1,
                    total_to_process,
                    candidate.file_name,
                )

                try:
                    media = self._process_candidate(candidate)
                    if media is None:
                        stats["files_duplicate"] += 1
                    else:
                        stats["files_imported"] += 1
                        stats["total_size_bytes"] += candidate.file_size
                        if media.video_info.duration:
                            stats["total_duration_seconds"] += media.video_info.duration.seconds

                except ProcessingException as exc:
                    logger.error("Failed to process %s: %s", candidate.file_path, exc)
                    stats["files_failed"] += 1

                emit_progress(
                    "Processando arquivo",
                    index,
                    total_to_process,
                    candidate.file_name,
                )

            return self._finalize_stats(stats, start_time, emit_progress)

        except Exception as exc:
            logger.error("Import session failed: %s", exc, exc_info=True)
            raise

    def _finalize_stats(
        self,
        stats: Dict[str, Any],
        start_time: datetime,
        emit_progress: Callable[[str, int, int, Optional[str]], None],
    ) -> Dict[str, Any]:
        duration_seconds = (datetime.utcnow() - start_time).total_seconds()
        stats["duration_seconds"] = duration_seconds

        total_processed = (
            stats["files_imported"]
            + stats["files_duplicate"]
            + stats["files_failed"]
        )
        total_to_process = stats.get("files_valid") or stats.get("files_found") or 0

        self._event_bus.emit(ImportCompletedEvent(
            import_session_id=stats["import_session_id"],
            total_files=stats["files_found"],
            imported_files=stats["files_imported"],
            duplicate_files=stats["files_duplicate"],
            failed_files=stats["files_failed"],
            total_size_bytes=stats["total_size_bytes"],
            duration_seconds=duration_seconds,
        ))

        emit_progress(
            "Cancelado" if stats.get("cancelled") else "Concluído",
            total_processed,
            total_to_process,
            None,
        )

        logger.info(
            "Import session complete: %s | imported=%s duplicate=%s failed=%s cancelled=%s",
            stats["import_session_id"],
            stats["files_imported"],
            stats["files_duplicate"],
            stats["files_failed"],
            stats["cancelled"],
        )
        return stats

    def _process_candidate(self, candidate: MediaFileCandidate) -> Optional[MediaFile]:
        """Processar um arquivo individual.

        Returns:
            MediaFile quando importado; None quando for duplicado/ignorado.
        """
        try:
            self._event_bus.emit(MediaDiscoveredEvent(
                file_hash="",
                file_path=str(candidate.file_path),
                file_name=candidate.file_name,
                file_size=candidate.file_size,
            ))

            file_hash = HashCalculator.calculate(candidate.file_path)

            existing = self._repository.find_by_hash_in_location(file_hash)
            if existing:
                self._event_bus.emit(DuplicateDetectedEvent(
                    file_hash=str(file_hash),
                    original_hash=str(existing.hash_info.file_hash),
                    file_path=str(candidate.file_path),
                ))

                duplicate_media = MediaFile(
                    file_info=FileInfo(
                        file_path=str(candidate.file_path),
                        file_name=candidate.file_name,
                        file_name_clean=candidate.file_path.stem,
                        file_extension=candidate.file_extension,
                        file_size=FileSize(candidate.file_size),
                        file_modified_at=candidate.file_modified,
                    ),
                    video_info=existing.video_info,
                    audio_info=existing.audio_info,
                    processing_info=ProcessingInfo(
                        status=ProcessingStatus.SKIPPED,
                        last_error="Arquivo ignorado por ser duplicado",
                    ),
                    hash_info=HashInfo(
                        file_hash=file_hash,
                        is_duplicate=True,
                        duplicate_of_hash=existing.hash_info.file_hash,
                    ),
                )

                try:
                    self._repository.add(duplicate_media)
                except Exception as exc:
                    # Mesmo caminho já registrado ou outro conflito: continua como duplicado contado.
                    logger.info("Duplicado não registrado novamente: %s | %s", candidate.file_path, exc)

                logger.info("Arquivo duplicado ignorado na mesma pasta/temporada: %s", candidate.file_path)
                return None

            self._event_bus.emit(MediaValidatedEvent(
                file_hash=str(file_hash),
                file_path=str(candidate.file_path),
            ))

            metadata = self._analyzer.analyze(candidate.file_path, file_hash)
            self._event_bus.emit(MetadataExtractedEvent(
                file_hash=str(file_hash),
                duration=metadata["duration"].seconds,
                fps=metadata.get("fps", 0),
                resolution=str(metadata.get("resolution", "")),
                codec_video=metadata.get("codec_video", ""),
            ))

            media = MediaFile(
                file_info=FileInfo(
                    file_path=str(candidate.file_path),
                    file_name=candidate.file_name,
                    file_name_clean=candidate.file_path.stem,
                    file_extension=candidate.file_extension,
                    file_size=FileSize(candidate.file_size),
                    file_modified_at=candidate.file_modified,
                ),
                video_info=VideoInfo(
                    duration=metadata["duration"],
                    fps=metadata.get("fps", 0),
                    resolution=metadata.get("resolution"),
                    aspect_ratio=metadata.get("aspect_ratio"),
                    codec_video=metadata.get("codec_video", ""),
                    bitrate=metadata.get("bitrate", 0),
                    num_streams=metadata.get("num_streams", 0),
                ),
                audio_info=AudioInfo(
                    codec_audio=metadata.get("codec_audio"),
                    audio_channels=metadata.get("audio_channels", 0),
                    language_code=metadata.get("language_code"),
                ),
                processing_info=ProcessingInfo(status=ProcessingStatus.METADATA_EXTRACTED),
                hash_info=HashInfo(file_hash=file_hash),
            )

            media = self._repository.add(media)
            media.processing_info.status = ProcessingStatus.READY
            self._repository.update(media)

            self._event_bus.emit(MediaImportedEvent(
                media_id=media.id.value if media.id else 0,
                file_hash=str(file_hash),
                file_path=str(candidate.file_path),
            ))

            logger.info("Media imported: %s", candidate.file_name)
            return media

        except ProcessingException:
            raise
        except Exception as exc:
            raise ProcessingException(f"Error processing {candidate.file_path}: {exc}")

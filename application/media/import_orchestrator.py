"""Orquestrador de importação de biblioteca de mídia.

Coordena MediaPipeline, TaskScheduler e SQLiteMediaRepository.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from application.event_bus import EventBus
from application.media.media_pipeline import MediaPipeline
from application.task_management import Task, TaskPriority, TaskScheduler
from infrastructure.persistence.sqlite_media_repository import SQLiteMediaRepository


logger = logging.getLogger(__name__)


class ImportOrchestrator:
    """Orquestrador de importação de mídia.

    Responsável por criar sessões, executar o pipeline em background,
    acompanhar progresso e controlar cancelamento/pausa.
    """

    TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}

    def __init__(
        self,
        media_pipeline: MediaPipeline,
        task_scheduler: TaskScheduler,
        repository: SQLiteMediaRepository,
        event_bus: EventBus,
    ):
        self.pipeline = media_pipeline
        self.scheduler = task_scheduler
        self.repository = repository
        self.event_bus = event_bus
        self.current_session_id: Optional[str] = None

        self.progress_callbacks: Dict[str, Callable] = {}
        self.progress_state: Dict[str, Dict[str, Any]] = {}
        self.cancel_flags: Dict[str, threading.Event] = {}
        self.pause_flags: Dict[str, threading.Event] = {}
        self.task_futures: Dict[str, Any] = {}
        self._lock = threading.RLock()

        logger.info("ImportOrchestrator inicializado")

    def start_import(
        self,
        folder_path: str,
        progress_callback: Optional[Callable] = None,
        cancel_callback: Optional[Callable] = None,
        library_folder: str = "Sem pasta",
        library_season: str = "Sem temporada",
    ) -> str:
        """Iniciar importação de pasta em background.

        Args:
            folder_path: Caminho da pasta a importar.
            progress_callback: Callback opcional de progresso.
            cancel_callback: Mantido por compatibilidade.

        Returns:
            ID da sessão de importação.
        """
        try:
            folder = Path(folder_path)
            if not folder.exists() or not folder.is_dir():
                raise ValueError(f"Pasta inválida: {folder_path}")

            session_id = str(uuid4())
            self.current_session_id = session_id
            library_folder = self.repository.create_library_folder(library_folder)
            library_season = self.repository.create_library_season(library_folder, library_season)
            self.repository.create_import_session(session_id, folder_path)

            with self._lock:
                self.progress_callbacks[session_id] = progress_callback
                self.cancel_flags[session_id] = threading.Event()
                self.pause_flags[session_id] = threading.Event()
                self.progress_state[session_id] = {
                    "session_id": session_id,
                    "folder_path": folder_path,
                    "stage": "Aguardando início",
                    "current_file": "",
                    "current": 0,
                    "total": 0,
                    "percentage": 0,
                    "total_files_found": 0,
                    "total_files_valid": 0,
                    "total_files_imported": 0,
                    "total_files_duplicate": 0,
                    "total_files_failed": 0,
                    "status": "IN_PROGRESS",
                    "library_folder": library_folder,
                    "library_season": library_season,
                }

            task = Task(
                name=f"Importar biblioteca: {folder.name}",
                priority=TaskPriority.HIGH,
            )

            def import_handler(t: Task) -> None:
                self._execute_import(session_id, folder_path, progress_callback, library_folder, library_season)

            future = self.scheduler.submit_task(task, import_handler)
            with self._lock:
                self.task_futures[session_id] = future

            logger.info("Importação iniciada: session_id=%s, folder=%s", session_id, folder_path)
            return session_id

        except Exception as exc:
            logger.error("Erro ao iniciar importação: %s", exc, exc_info=True)
            raise

    def start_import_files(
        self,
        file_paths: list[str],
        progress_callback: Optional[Callable] = None,
        cancel_callback: Optional[Callable] = None,
        library_folder: str = "Sem pasta",
        library_season: str = "Sem temporada",
    ) -> str:
        """Iniciar importação de arquivos selecionados em background."""
        try:
            valid_paths = [str(Path(path)) for path in file_paths if Path(path).exists() and Path(path).is_file()]
            if not valid_paths:
                raise ValueError("Nenhum arquivo válido selecionado para importação")

            session_id = str(uuid4())
            self.current_session_id = session_id
            source_label = f"{len(valid_paths)} arquivo(s) selecionado(s)"
            library_folder = self.repository.create_library_folder(library_folder)
            library_season = self.repository.create_library_season(library_folder, library_season)
            self.repository.create_import_session(session_id, source_label)

            with self._lock:
                self.progress_callbacks[session_id] = progress_callback
                self.cancel_flags[session_id] = threading.Event()
                self.pause_flags[session_id] = threading.Event()
                self.progress_state[session_id] = {
                    "session_id": session_id,
                    "folder_path": source_label,
                    "stage": "Aguardando início",
                    "current_file": "",
                    "current": 0,
                    "total": len(valid_paths),
                    "percentage": 0,
                    "total_files_found": len(valid_paths),
                    "total_files_valid": 0,
                    "total_files_imported": 0,
                    "total_files_duplicate": 0,
                    "total_files_failed": 0,
                    "status": "IN_PROGRESS",
                    "library_folder": library_folder,
                    "library_season": library_season,
                }

            task = Task(
                name=f"Importar {len(valid_paths)} arquivo(s)",
                priority=TaskPriority.HIGH,
            )

            def import_handler(t: Task) -> None:
                self._execute_import_files(session_id, valid_paths, progress_callback, library_folder, library_season)

            future = self.scheduler.submit_task(task, import_handler)
            with self._lock:
                self.task_futures[session_id] = future

            logger.info("Importação de arquivos iniciada: session_id=%s, total=%s", session_id, len(valid_paths))
            return session_id

        except Exception as exc:
            logger.error("Erro ao iniciar importação de arquivos: %s", exc, exc_info=True)
            raise

    def cancel_import(self, session_id: Optional[str] = None) -> bool:
        """Solicitar cancelamento de uma importação.

        O cancelamento acontece com segurança entre um arquivo e outro.
        """
        target_session = session_id or self.current_session_id
        if not target_session:
            return False

        with self._lock:
            cancel_flag = self.cancel_flags.get(target_session)
            pause_flag = self.pause_flags.get(target_session)
            future = self.task_futures.get(target_session)
            state = self.progress_state.setdefault(target_session, {})
            state.update({"status": "CANCELLING", "stage": "Cancelando..."})

        if cancel_flag:
            cancel_flag.set()
        if pause_flag:
            pause_flag.clear()
        if future and not future.running():
            future.cancel()

        logger.info("Cancelamento solicitado para sessão %s", target_session)
        return True

    def pause_import(self, session_id: Optional[str] = None) -> bool:
        """Pausar a importação ao final do arquivo atual."""
        target_session = session_id or self.current_session_id
        if not target_session:
            return False

        with self._lock:
            pause_flag = self.pause_flags.get(target_session)
            state = self.progress_state.setdefault(target_session, {})
            state.update({"status": "PAUSED", "stage": "Pausado"})

        if pause_flag:
            pause_flag.set()
            logger.info("Pausa solicitada para sessão %s", target_session)
            return True
        return False

    def resume_paused_import(self, session_id: Optional[str] = None) -> bool:
        """Retomar uma importação pausada."""
        target_session = session_id or self.current_session_id
        if not target_session:
            return False

        with self._lock:
            pause_flag = self.pause_flags.get(target_session)
            state = self.progress_state.setdefault(target_session, {})
            state.update({"status": "IN_PROGRESS", "stage": "Retomando..."})

        if pause_flag:
            pause_flag.clear()
            logger.info("Importação retomada: %s", target_session)
            return True
        return False

    def _execute_import(
        self,
        session_id: str,
        folder_path: str,
        progress_callback: Optional[Callable],
        library_folder: str = "Sem pasta",
        library_season: str = "Sem temporada",
    ) -> None:
        """Executar importação em thread de background."""
        try:
            logger.info("Executando importação: %s", session_id)

            setattr(self.repository, "_active_session_id", session_id)
            setattr(self.repository, "_active_library_folder", library_folder or "Sem pasta")
            setattr(self.repository, "_active_library_season", library_season or "Sem temporada")

            def is_cancelled() -> bool:
                flag = self.cancel_flags.get(session_id)
                return bool(flag and flag.is_set())

            def wait_if_paused() -> None:
                pause_flag = self.pause_flags.get(session_id)
                while pause_flag and pause_flag.is_set() and not is_cancelled():
                    self._update_progress_state(
                        session_id,
                        stage="Pausado",
                        status="PAUSED",
                    )
                    time.sleep(0.2)

            def progress_wrapper(
                stage: str,
                current: int = 0,
                total: int = 0,
                stats: Optional[Dict[str, Any]] = None,
                current_file: Optional[str] = None,
            ) -> None:
                mapped_stats = self._map_pipeline_stats(stats or {})
                mapped_stats["status"] = "IN_PROGRESS"
                self.repository.update_session_stats(session_id, mapped_stats)

                self._update_progress_state(
                    session_id,
                    stage=stage,
                    current=current,
                    total=total,
                    stats=stats,
                    current_file=current_file,
                    status="IN_PROGRESS",
                )

                if progress_callback:
                    try:
                        progress_callback(stage, current, total, stats, current_file)
                    except TypeError:
                        progress_callback(stage, current, total)

            stats = self.pipeline.process_directory(
                folder_path,
                import_session_id=session_id,
                progress_callback=progress_wrapper,
                cancel_checker=is_cancelled,
                pause_callback=wait_if_paused,
            )

            final_status = "CANCELLED" if stats.get("cancelled") else "COMPLETED"
            db_stats = self._map_pipeline_stats(stats)
            db_stats["status"] = final_status
            self.repository.update_session_stats(session_id, db_stats)

            self._update_progress_state(
                session_id,
                stage="Cancelado" if final_status == "CANCELLED" else "Concluído",
                current=db_stats.get("total_files_imported", 0)
                + db_stats.get("total_files_failed", 0)
                + stats.get("files_duplicate", 0),
                total=db_stats.get("total_files_valid", 0) or db_stats.get("total_files_found", 0),
                stats=stats,
                status=final_status,
            )

            logger.info("Importação finalizada: %s | %s", session_id, db_stats)
            self.event_bus.emit({
                "type": "IMPORT_COMPLETED" if final_status == "COMPLETED" else "IMPORT_CANCELLED",
                "session_id": session_id,
                "stats": stats,
            })

        except Exception as exc:
            logger.error("Erro ao executar importação: %s", exc, exc_info=True)
            fail_stats = {"status": "FAILED"}
            try:
                self.repository.update_session_stats(session_id, fail_stats)
            except Exception:
                logger.exception("Falha ao marcar sessão como FAILED")

            self._update_progress_state(
                session_id,
                stage="Erro",
                status="FAILED",
                error=str(exc),
            )
            self.event_bus.emit({
                "type": "IMPORT_FAILED",
                "session_id": session_id,
                "error": str(exc),
            })

        finally:
            try:
                if getattr(self.repository, "_active_session_id", None) == session_id:
                    setattr(self.repository, "_active_session_id", None)
                    setattr(self.repository, "_active_library_folder", "Sem pasta")
                    setattr(self.repository, "_active_library_season", "Sem temporada")
            except Exception:
                pass


    def _execute_import_files(
        self,
        session_id: str,
        file_paths: list[str],
        progress_callback: Optional[Callable],
        library_folder: str = "Sem pasta",
        library_season: str = "Sem temporada",
    ) -> None:
        """Executar importação de arquivos selecionados em thread de background."""
        try:
            logger.info("Executando importação de arquivos: %s", session_id)

            setattr(self.repository, "_active_session_id", session_id)
            setattr(self.repository, "_active_library_folder", library_folder or "Sem pasta")
            setattr(self.repository, "_active_library_season", library_season or "Sem temporada")

            def is_cancelled() -> bool:
                flag = self.cancel_flags.get(session_id)
                return bool(flag and flag.is_set())

            def wait_if_paused() -> None:
                pause_flag = self.pause_flags.get(session_id)
                while pause_flag and pause_flag.is_set() and not is_cancelled():
                    self._update_progress_state(
                        session_id,
                        stage="Pausado",
                        status="PAUSED",
                    )
                    time.sleep(0.2)

            def progress_wrapper(
                stage: str,
                current: int = 0,
                total: int = 0,
                stats: Optional[Dict[str, Any]] = None,
                current_file: Optional[str] = None,
            ) -> None:
                mapped_stats = self._map_pipeline_stats(stats or {})
                mapped_stats["status"] = "IN_PROGRESS"
                self.repository.update_session_stats(session_id, mapped_stats)

                self._update_progress_state(
                    session_id,
                    stage=stage,
                    current=current,
                    total=total,
                    stats=stats,
                    current_file=current_file,
                    status="IN_PROGRESS",
                )

                if progress_callback:
                    try:
                        progress_callback(stage, current, total, stats, current_file)
                    except TypeError:
                        progress_callback(stage, current, total)

            stats = self.pipeline.process_files(
                file_paths,
                import_session_id=session_id,
                progress_callback=progress_wrapper,
                cancel_checker=is_cancelled,
                pause_callback=wait_if_paused,
            )

            final_status = "CANCELLED" if stats.get("cancelled") else "COMPLETED"
            db_stats = self._map_pipeline_stats(stats)
            db_stats["status"] = final_status
            self.repository.update_session_stats(session_id, db_stats)

            self._update_progress_state(
                session_id,
                stage="Cancelado" if final_status == "CANCELLED" else "Concluído",
                current=db_stats.get("total_files_imported", 0)
                + db_stats.get("total_files_failed", 0)
                + db_stats.get("total_files_duplicate", 0),
                total=db_stats.get("total_files_valid", 0) or db_stats.get("total_files_found", 0),
                stats=stats,
                status=final_status,
            )

            logger.info("Importação de arquivos finalizada: %s | %s", session_id, db_stats)
            self.event_bus.emit({
                "type": "IMPORT_COMPLETED" if final_status == "COMPLETED" else "IMPORT_CANCELLED",
                "session_id": session_id,
                "stats": stats,
            })

        except Exception as exc:
            logger.error("Erro ao executar importação de arquivos: %s", exc, exc_info=True)
            try:
                self.repository.update_session_stats(session_id, {"status": "FAILED"})
            except Exception:
                logger.exception("Falha ao marcar sessão de arquivos como FAILED")

            self._update_progress_state(
                session_id,
                stage="Erro",
                status="FAILED",
                error=str(exc),
            )
            self.event_bus.emit({
                "type": "IMPORT_FAILED",
                "session_id": session_id,
                "error": str(exc),
            })

        finally:
            try:
                if getattr(self.repository, "_active_session_id", None) == session_id:
                    setattr(self.repository, "_active_session_id", None)
                    setattr(self.repository, "_active_library_folder", "Sem pasta")
                    setattr(self.repository, "_active_library_season", "Sem temporada")
            except Exception:
                pass

    def _map_pipeline_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Converter estatísticas do MediaPipeline para colunas do SQLite."""
        return {
            "total_files_found": stats.get("total_files_found", stats.get("files_found", 0)),
            "total_files_valid": stats.get("total_files_valid", stats.get("files_valid", 0)),
            "total_files_imported": stats.get("total_files_imported", stats.get("files_imported", 0)),
            "total_files_duplicate": stats.get("total_files_duplicate", stats.get("files_duplicate", 0)),
            "total_files_failed": stats.get("total_files_failed", stats.get("files_failed", 0)),
            "total_duration_seconds": stats.get(
                "total_duration_seconds",
                stats.get("duration_seconds", 0),
            ),
            "total_size_bytes": stats.get("total_size_bytes", 0),
        }

    def _update_progress_state(
        self,
        session_id: str,
        stage: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
        stats: Optional[Dict[str, Any]] = None,
        current_file: Optional[str] = None,
        status: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Atualizar progresso em memória para a interface consultar."""
        with self._lock:
            state = self.progress_state.setdefault(session_id, {"session_id": session_id})
            if stage is not None:
                state["stage"] = stage
            if current is not None:
                state["current"] = current
            if total is not None:
                state["total"] = total
            if current_file is not None:
                state["current_file"] = current_file
            if status is not None:
                state["status"] = status
            if error is not None:
                state["error"] = error

            if stats:
                mapped = self._map_pipeline_stats(stats)
                state.update(mapped)
                state["total_files_duplicate"] = stats.get("files_duplicate", 0)

            total_value = state.get("total") or state.get("total_files_valid") or state.get("total_files_found") or 0
            current_value = state.get("current") or 0
            if total_value:
                state["percentage"] = min(100, int((current_value / total_value) * 100))
            elif state.get("status") in self.TERMINAL_STATUSES:
                state["percentage"] = 100
            else:
                state["percentage"] = 0

    def get_session_progress(self, session_id: str) -> Dict[str, Any]:
        """Obter progresso da sessão."""
        try:
            db_stats = self.repository.get_session_stats(session_id) or {}
            with self._lock:
                state = dict(self.progress_state.get(session_id, {}))

            progress = {
                "session_id": session_id,
                "total_files_found": db_stats.get("total_files_found", 0),
                "total_files_valid": db_stats.get("total_files_valid", 0),
                "total_files_imported": db_stats.get("total_files_imported", 0),
                "total_files_failed": db_stats.get("total_files_failed", 0),
                "total_files_duplicate": db_stats.get("total_files_duplicate", 0),
                "status": db_stats.get("status", "IN_PROGRESS"),
                "stage": "",
                "current_file": "",
                "current": 0,
                "total": 0,
                "percentage": self._calculate_progress_percentage(db_stats),
            }
            progress.update({k: v for k, v in state.items() if v is not None})
            return progress
        except Exception as exc:
            logger.error("Erro ao obter progresso: %s", exc, exc_info=True)
            return {}

    def _calculate_progress_percentage(self, stats: Dict[str, Any]) -> int:
        total = stats.get("total_files_found", 0)
        if not total:
            return 0
        processed = (
            stats.get("total_files_imported", 0)
            + stats.get("total_files_duplicate", 0)
            + stats.get("total_files_failed", 0)
        )
        return min(100, int((processed / total) * 100))

    def get_incomplete_sessions(self) -> list:
        """Obter sessões incompletas para retomada."""
        try:
            return self.repository.get_incomplete_sessions()
        except Exception as exc:
            logger.error("Erro ao obter sessões incompletas: %s", exc, exc_info=True)
            return []

    def resume_import(
        self,
        session_id: str,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        """Retomar uma sessão incompleta.

        Observação: nesta fase, a retomada reinicia a varredura da pasta e ignora
        duplicados já existentes. Retomada granular será refinada em sprint futura.
        """
        try:
            sessions = self.repository.get_incomplete_sessions()
            session_info = next((s for s in sessions if s["session_id"] == session_id), None)
            if not session_info:
                raise ValueError(f"Sessão não encontrada: {session_id}")

            folder_path = session_info["folder_path"]
            self.current_session_id = session_id
            with self._lock:
                self.cancel_flags[session_id] = threading.Event()
                self.pause_flags[session_id] = threading.Event()

            task = Task(
                name=f"Retomar importação: {Path(folder_path).name}",
                priority=TaskPriority.HIGH,
            )

            def resume_handler(t: Task) -> None:
                self._execute_import(session_id, folder_path, progress_callback)

            future = self.scheduler.submit_task(task, resume_handler)
            with self._lock:
                self.task_futures[session_id] = future

            logger.info("Importação retomada: %s", session_id)

        except Exception as exc:
            logger.error("Erro ao retomar importação: %s", exc, exc_info=True)
            raise

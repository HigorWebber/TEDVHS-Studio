"""Exportação precisa de clipes usando FFmpeg.

A exportação recebe marcações de cena já salvas no banco e só então cria o
arquivo .mp4 final. Isso mantém o fluxo econômico: cenas/cortes ficam como
metadados até o usuário mandar exportar.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)


class ClipExporter:
    """Exportador de clipes em MP4 com corte preciso por reencode.

    Estrutura padrão:

    TEDVHS_Exports/
      Anime/
        Clipes/
          nome_do_clipe.mp4
          nome_do_clipe.json

    A pasta "Clipes" funciona como uma temporada especial do anime.
    A origem real do clipe, temporada/episódio/cenas, fica salva no JSON lateral.
    """

    def __init__(self, export_root: Path | str | None = None):
        if export_root is None:
            export_root = Path.home() / "Videos" / "TEDVHS_Exports"
        self.export_root = Path(export_root)

    def ensure_ffmpeg_available(self) -> None:
        """Validar se o ffmpeg está acessível no PATH."""
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "FFmpeg não encontrado. Instale o FFmpeg e confirme que o comando 'ffmpeg' funciona no CMD."
            )

    @staticmethod
    def sanitize_component(value: Any, fallback: str = "Sem nome") -> str:
        """Sanitizar nome de pasta/arquivo para Windows."""
        text = str(value or "").strip() or fallback
        text = re.sub(r"[<>:\"/\\|?*]+", "-", text)
        text = re.sub(r"\s+", " ", text).strip(" .")
        return text or fallback

    @staticmethod
    def _unique_path(path: Path) -> Path:
        """Gerar caminho único no estilo Windows: nome (1).ext."""
        if not path.exists():
            return path
        counter = 1
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _format_seconds_for_filename(seconds: float) -> str:
        seconds = max(float(seconds or 0.0), 0.0)
        total = int(seconds)
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        return f"{hours:02d}-{minutes:02d}-{secs:02d}"

    def build_output_path(self, media: Any, scene: Dict[str, Any], clip_name: str) -> Path:
        folder = self.sanitize_component(media.custom_metadata.get("library_folder", "Sem pasta"), "Sem pasta")
        safe_clip_name = self.sanitize_component(clip_name, "clipe")

        # Clipes ficam no nível do anime, como uma "temporada" especial:
        # TEDVHS_Exports / Naruto / Clipes / nome_do_clipe.mp4
        # A temporada e o episódio de origem são preservados no JSON e no banco.
        output_dir = self.export_root / folder / "Clipes"
        output_dir.mkdir(parents=True, exist_ok=True)
        return self._unique_path(output_dir / f"{safe_clip_name}.mp4")

    def export_scene(
        self,
        source_file: Path | str,
        segments: Iterable[Tuple[float, float]],
        output_path: Path | str,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Exportar uma cena/corte/clipe juntado com precisão.

        Args:
            source_file: vídeo original.
            segments: lista de pares (início_segundos, fim_segundos).
            output_path: arquivo MP4 final.
            metadata: dados salvos no JSON lateral.

        Returns:
            Dicionário com informações da exportação.
        """
        self.ensure_ffmpeg_available()

        source = Path(source_file)
        if not source.exists():
            raise FileNotFoundError(f"Arquivo original não encontrado: {source}")

        clean_segments: List[Tuple[float, float]] = []
        for start, end in segments:
            start = max(float(start or 0.0), 0.0)
            end = max(float(end or start), start)
            if end - start >= 0.10:
                clean_segments.append((start, end))

        if not clean_segments:
            raise ValueError("Nenhum trecho válido para exportar.")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        if len(clean_segments) == 1:
            self._export_single_segment(source, clean_segments[0], output)
        else:
            self._export_multi_segment(source, clean_segments, output)

        duration_seconds = sum(end - start for start, end in clean_segments)
        result = {
            "output_path": str(output),
            "metadata_path": str(output.with_suffix(".json")),
            "duration_seconds": duration_seconds,
            "segments": [
                {"start_seconds": start, "end_seconds": end, "duration_seconds": end - start}
                for start, end in clean_segments
            ],
            "exported_at": datetime.utcnow().isoformat(),
            "export_mode": "precise_ffmpeg_reencode",
        }

        payload = dict(metadata or {})
        payload.update(result)
        with open(output.with_suffix(".json"), "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

        return result

    def _run_ffmpeg(self, command: List[str]) -> None:
        logger.info("Executando FFmpeg: %s", " ".join(command))
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "FFmpeg falhou sem mensagem detalhada.")

    def _export_single_segment(self, source: Path, segment: Tuple[float, float], output: Path) -> None:
        start, end = segment
        duration = max(end - start, 0.10)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(source),
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
        self._run_ffmpeg(command)

    def _export_multi_segment(self, source: Path, segments: List[Tuple[float, float]], output: Path) -> None:
        with tempfile.TemporaryDirectory(prefix="tedvhs_export_") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            part_files: List[Path] = []
            for index, segment in enumerate(segments, start=1):
                part_path = temp_dir / f"part_{index:03d}.mp4"
                self._export_single_segment(source, segment, part_path)
                part_files.append(part_path)

            concat_file = temp_dir / "concat.txt"
            with open(concat_file, "w", encoding="utf-8") as file:
                for part in part_files:
                    safe_path = str(part).replace("\\", "/").replace("'", "'\\''")
                    file.write(f"file '{safe_path}'\n")

            command = [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
            self._run_ffmpeg(command)

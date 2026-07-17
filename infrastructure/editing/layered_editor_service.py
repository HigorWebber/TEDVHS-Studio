"""Serviço de exportação do Editor em Camadas do TEDVHS Studio.

Primeira versão do editor estilo Vegas simplificado:
- 1 vídeo base;
- áudio original com volume ajustável;
- áudio da narração opcional;
- legenda do anime opcional;
- legenda do narrador opcional;
- texto extra opcional;
- exportação final em MP4.

A implementação usa FFmpeg/FFprobe e não depende de IA local pesada.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


class LayeredEditorError(RuntimeError):
    """Erro amigável do editor em camadas."""


@dataclass
class EditorExportOptions:
    base_video_path: Path
    output_path: Path
    original_volume: float = 0.30
    narration_audio_path: Optional[Path] = None
    narration_volume: float = 1.00
    anime_subtitle_path: Optional[Path] = None
    narrator_subtitle_path: Optional[Path] = None
    extra_text_subtitle_path: Optional[Path] = None
    watermark_subtitle_path: Optional[Path] = None
    duration_seconds: float = 0.0


class LayeredEditorService:
    """Exportar vídeos finais usando camadas simples e FFmpeg."""

    def __init__(self, timeout_seconds: int = 1200) -> None:
        self.timeout_seconds = max(120, int(timeout_seconds or 1200))
        self.ffmpeg_binary = os.environ.get("FFMPEG_BINARY", "ffmpeg")
        self.ffprobe_binary = os.environ.get("FFPROBE_BINARY", "ffprobe")

    def export_final_video(self, options: EditorExportOptions) -> Dict[str, Any]:
        """Exportar MP4 final com as camadas selecionadas."""
        base_video = Path(options.base_video_path)
        if not base_video.exists():
            raise LayeredEditorError(f"Vídeo base não encontrado:\n{base_video}")

        output_path = self._unique_path(Path(options.output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        inputs: List[str] = [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(base_video),
        ]

        has_narration_audio = bool(options.narration_audio_path and Path(options.narration_audio_path).exists())
        if has_narration_audio:
            inputs.extend(["-i", str(options.narration_audio_path)])

        video_filters: List[str] = []
        for subtitle_path in (
            options.anime_subtitle_path,
            options.narrator_subtitle_path,
            options.extra_text_subtitle_path,
            options.watermark_subtitle_path,
        ):
            if subtitle_path and Path(subtitle_path).exists():
                escaped = self._escape_subtitle_filter_path(Path(subtitle_path))
                video_filters.append(f"subtitles='{escaped}'")

        cmd = list(inputs)

        if has_narration_audio:
            vf_chain = ",".join(video_filters) if video_filters else "null"
            original_volume = self._clamp_float(options.original_volume, 0.0, 2.0)
            narration_volume = self._clamp_float(options.narration_volume, 0.0, 2.0)
            filter_complex = (
                f"[0:v]{vf_chain}[vout];"
                f"[0:a]volume={original_volume:.3f}[a0];"
                f"[1:a]volume={narration_volume:.3f}[a1];"
                f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            cmd.extend([
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(output_path),
            ])
        else:
            if video_filters:
                original_volume = self._clamp_float(options.original_volume, 0.0, 2.0)
                cmd.extend([
                    "-vf",
                    ",".join(video_filters),
                    "-af",
                    f"volume={original_volume:.3f}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ])
            else:
                # Sem camadas visuais e sem áudio de narração: ainda respeita o volume original configurado.
                original_volume = self._clamp_float(options.original_volume, 0.0, 2.0)
                cmd.extend([
                    "-c:v",
                    "copy",
                    "-af",
                    f"volume={original_volume:.3f}",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ])

        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if completed.returncode != 0 or not output_path.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise LayeredEditorError(f"FFmpeg não conseguiu exportar o vídeo final.\n{detail[:1600]}")

        return {
            "output_path": str(output_path),
            "used_layers": {
                "anime_subtitle": bool(options.anime_subtitle_path and Path(options.anime_subtitle_path).exists()),
                "narrator_subtitle": bool(options.narrator_subtitle_path and Path(options.narrator_subtitle_path).exists()),
                "extra_text": bool(options.extra_text_subtitle_path and Path(options.extra_text_subtitle_path).exists()),
                "watermark": bool(options.watermark_subtitle_path and Path(options.watermark_subtitle_path).exists()),
                "narration_audio": has_narration_audio,
                "original_volume": options.original_volume,
                "narration_volume": options.narration_volume,
            },
        }


    def export_preview_video(self, options: EditorExportOptions) -> Dict[str, Any]:
        """Gerar uma prévia temporária com as camadas aplicadas.

        A prévia é renderizada em qualidade mais leve para o usuário conseguir
        conferir legenda, narração, marca d'água, textos e volumes antes da
        exportação final. Ela não registra nada na biblioteca.
        """
        base_video = Path(options.base_video_path)
        if not base_video.exists():
            raise LayeredEditorError(f"Vídeo base não encontrado:\n{base_video}")

        output_path = Path(options.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            output_path = self._unique_path(output_path)

        inputs: List[str] = [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(base_video),
        ]

        has_narration_audio = bool(options.narration_audio_path and Path(options.narration_audio_path).exists())
        if has_narration_audio:
            inputs.extend(["-i", str(options.narration_audio_path)])

        video_filters: List[str] = []
        for subtitle_path in (
            options.anime_subtitle_path,
            options.narrator_subtitle_path,
            options.extra_text_subtitle_path,
            options.watermark_subtitle_path,
        ):
            if subtitle_path and Path(subtitle_path).exists():
                escaped = self._escape_subtitle_filter_path(Path(subtitle_path))
                video_filters.append(f"subtitles='{escaped}'")
        # Prévia mais leve: mantém as camadas aplicadas, mas reduz a altura para 720p.
        video_filters.append("scale=-2:720")

        cmd = list(inputs)
        if has_narration_audio:
            vf_chain = ",".join(video_filters)
            original_volume = self._clamp_float(options.original_volume, 0.0, 2.0)
            narration_volume = self._clamp_float(options.narration_volume, 0.0, 2.0)
            filter_complex = (
                f"[0:v]{vf_chain}[vout];"
                f"[0:a]volume={original_volume:.3f}[a0];"
                f"[1:a]volume={narration_volume:.3f}[a1];"
                f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
            cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "[aout]",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-shortest",
                str(output_path),
            ])
        else:
            original_volume = self._clamp_float(options.original_volume, 0.0, 2.0)
            cmd.extend([
                "-vf", ",".join(video_filters),
                "-af", f"volume={original_volume:.3f}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ])

        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if completed.returncode != 0 or not output_path.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise LayeredEditorError(f"FFmpeg não conseguiu gerar a prévia aplicada.\n{detail[:1600]}")

        return {
            "output_path": str(output_path),
            "used_layers": {
                "anime_subtitle": bool(options.anime_subtitle_path and Path(options.anime_subtitle_path).exists()),
                "narrator_subtitle": bool(options.narrator_subtitle_path and Path(options.narrator_subtitle_path).exists()),
                "extra_text": bool(options.extra_text_subtitle_path and Path(options.extra_text_subtitle_path).exists()),
                "watermark": bool(options.watermark_subtitle_path and Path(options.watermark_subtitle_path).exists()),
                "narration_audio": has_narration_audio,
                "original_volume": options.original_volume,
                "narration_volume": options.narration_volume,
            },
        }

    def generate_narrator_ass(
        self,
        script: str,
        output_path: Path,
        duration_seconds: float,
        position: str = "superior",
        title: str = "Legenda do narrador",
    ) -> Path:
        """Gerar ASS da narração, distribuindo as frases no tempo do vídeo/áudio."""
        text = str(script or "").strip()
        if not text:
            raise LayeredEditorError("Roteiro do narrador vazio. Gere ou escreva a narração antes.")
        duration = max(1.0, float(duration_seconds or 1.0))
        cues = self._split_script_into_cues(text, duration)
        ass = self._format_ass(
            cues,
            title=title,
            style_name="Narrador",
            font_size=54,
            alignment=self._alignment_for_position(position, default=8),
            margin_v=58,
            primary="&H00FFFFFF",
            outline="&H00000000",
            back="&H88000000",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass, encoding="utf-8")
        return output_path

    def generate_extra_text_ass(
        self,
        text: str,
        output_path: Path,
        duration_seconds: float,
        position: str = "centro",
        title: str = "Texto extra",
    ) -> Optional[Path]:
        value = str(text or "").strip()
        if not value:
            return None
        duration = max(1.0, float(duration_seconds or 1.0))
        cues = [{"start": 0.0, "end": duration, "text": value}]
        ass = self._format_ass(
            cues,
            title=title,
            style_name="TextoExtra",
            font_size=62,
            alignment=self._alignment_for_position(position, default=5),
            margin_v=80,
            primary="&H00FFFFFF",
            outline="&H00000000",
            back="&H99000000",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass, encoding="utf-8")
        return output_path

    def create_positioned_subtitle_copy(
        self,
        source_ass_path: Path,
        output_path: Path,
        position: str,
    ) -> Path:
        """Criar cópia ASS com alinhamento alterado de forma simples."""
        source = Path(source_ass_path)
        if not source.exists():
            raise LayeredEditorError(f"Legenda ASS não encontrada:\n{source}")
        content = source.read_text(encoding="utf-8", errors="replace")
        alignment = self._alignment_for_position(position, default=2)
        # Em ASS, o campo Alignment é o 18º campo do Style padrão. Esta correção cobre a maioria dos arquivos gerados pelo app.
        lines: List[str] = []
        in_styles = False
        fmt_fields: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.lower() == "[v4+ styles]":
                in_styles = True
                lines.append(line)
                continue
            if stripped.startswith("[") and stripped.lower() != "[v4+ styles]":
                in_styles = False
            if in_styles and stripped.lower().startswith("format:"):
                raw_fields = stripped.split(":", 1)[1]
                fmt_fields = [part.strip().lower() for part in raw_fields.split(",")]
                lines.append(line)
                continue
            if in_styles and stripped.lower().startswith("style:") and fmt_fields:
                prefix, raw_values = line.split(":", 1)
                values = [part.strip() for part in raw_values.split(",")]
                try:
                    idx = fmt_fields.index("alignment")
                    if idx < len(values):
                        values[idx] = str(alignment)
                        line = f"{prefix}: " + ",".join(values)
                except ValueError:
                    pass
            lines.append(line)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path


    def generate_watermark_ass(
        self,
        text: str,
        output_path: Path,
        duration_seconds: float,
        position: str = "superior direito",
        title: str = "Marca d'água",
    ) -> Optional[Path]:
        """Gerar camada ASS simples para marca d'água textual, como @tedvhs."""
        value = str(text or "").strip()
        if not value:
            return None
        duration = max(1.0, float(duration_seconds or 1.0))
        alignment = self._watermark_alignment(position)
        cues = [{"start": 0.0, "end": duration, "text": value}]
        ass = self._format_ass(
            cues,
            title=title,
            style_name="Watermark",
            font_size=34,
            alignment=alignment,
            margin_v=42,
            primary="&HCCFFFFFF",
            outline="&H66000000",
            back="&H22000000",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass, encoding="utf-8")
        return output_path

    def _watermark_alignment(self, position: str) -> int:
        text = str(position or "").lower()
        # ASS: 7 topo-esquerda, 8 topo-centro, 9 topo-direita, 1 baixo-esquerda, 2 baixo-centro, 3 baixo-direita.
        if "baixo" in text or "infer" in text or "bottom" in text:
            if "esquer" in text or "left" in text:
                return 1
            if "direit" in text or "right" in text:
                return 3
            return 2
        if "esquer" in text or "left" in text:
            return 7
        if "cent" in text or "meio" in text:
            return 8
        return 9

    def probe_duration(self, media_path: str | Path) -> float:
        path = Path(media_path)
        if not path.exists():
            return 0.0
        cmd = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if completed.returncode == 0:
                return max(0.0, float((completed.stdout or "0").strip() or 0.0))
        except Exception:
            return 0.0
        return 0.0

    def _split_script_into_cues(self, script: str, duration_seconds: float) -> List[Dict[str, Any]]:
        clean = re.sub(r"\s+", " ", str(script or "").strip())
        # Remove cabeçalhos comuns gerados em pacotes.
        clean = re.sub(r"^(roteiro|narra[cç][aã]o|texto do narrador)\s*:\s*", "", clean, flags=re.I)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", clean) if s.strip()]
        if not sentences:
            sentences = [clean]
        # Quebra frases muito longas para legenda ficar legível.
        chunks: List[str] = []
        for sentence in sentences:
            words = sentence.split()
            current: List[str] = []
            for word in words:
                if sum(len(w) + 1 for w in current) + len(word) > 78 and current:
                    chunks.append(" ".join(current).strip())
                    current = [word]
                else:
                    current.append(word)
            if current:
                chunks.append(" ".join(current).strip())
        chunks = [chunk for chunk in chunks if chunk]
        total_words = max(1, sum(len(chunk.split()) for chunk in chunks))
        start = 0.0
        cues: List[Dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            words = max(1, len(chunk.split()))
            if index == len(chunks) - 1:
                end = duration_seconds
            else:
                end = start + duration_seconds * (words / total_words)
                end = max(end, start + 1.2)
                end = min(end, duration_seconds)
            cues.append({"start": start, "end": max(end, start + 0.8), "text": chunk})
            start = end
            if start >= duration_seconds:
                break
        return cues or [{"start": 0.0, "end": duration_seconds, "text": clean}]

    def _format_ass(
        self,
        cues: Sequence[Dict[str, Any]],
        title: str,
        style_name: str,
        font_size: int,
        alignment: int,
        margin_v: int,
        primary: str,
        outline: str,
        back: str,
    ) -> str:
        safe_title = str(title or "TEDVHS")
        header = [
            "[Script Info]",
            f"Title: {safe_title}",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
            f"Style: {style_name},Arial,{font_size},{primary},&H000000FF,{outline},{back},-1,0,0,0,100,100,0,0,1,4,1,{alignment},80,80,{margin_v},1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]
        lines = list(header)
        for cue in cues:
            start = self._ass_time(float(cue.get("start") or 0.0))
            end = self._ass_time(float(cue.get("end") or 0.0))
            text = self._ass_text(str(cue.get("text") or ""))
            if text:
                lines.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}")
        return "\n".join(lines) + "\n"

    def _ass_text(self, text: str) -> str:
        value = str(text or "").replace("{", "").replace("}", "")
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        # Quebra em duas linhas quando passar de ~45 caracteres.
        if "\n" not in value and len(value) > 48:
            words = value.split()
            mid = max(1, len(words) // 2)
            value = " ".join(words[:mid]) + r"\N" + " ".join(words[mid:])
        else:
            value = value.replace("\n", r"\N")
        return value

    @staticmethod
    def _ass_time(seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int(round((seconds - int(seconds)) * 100))
        if centis >= 100:
            secs += 1
            centis -= 100
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    def _alignment_for_position(self, position: str, default: int = 2) -> int:
        text = str(position or "").lower()
        if "super" in text or "top" in text or "cima" in text:
            return 8
        if "centro" in text or "meio" in text or "center" in text:
            return 5
        if "baixo" in text or "infer" in text or "bottom" in text:
            return 2
        return int(default)

    def _escape_subtitle_filter_path(self, path: Path) -> str:
        value = str(Path(path).resolve()).replace("\\", "/")
        value = value.replace(":", r"\:")
        value = value.replace("'", r"\'")
        return value

    @staticmethod
    def _clamp_float(value: float, minimum: float, maximum: float) -> float:
        try:
            number = float(value)
        except Exception:
            number = minimum
        return max(minimum, min(maximum, number))

    def _unique_path(self, path: Path) -> Path:
        candidate = Path(path)
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        parent = candidate.parent
        for index in range(2, 1000):
            new_candidate = parent / f"{stem} {index}{suffix}"
            if not new_candidate.exists():
                return new_candidate
        return parent / f"{stem} {os.getpid()}{suffix}"

    @staticmethod
    def sanitize_name(value: str) -> str:
        text = re.sub(r"[<>:\"/\\|?*]+", "-", str(value or "").strip())
        text = re.sub(r"\s+", " ", text).strip(" .")
        return text or "video"

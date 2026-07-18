"""Serviço de exportação do Editor em Camadas do TEDVHS Studio.

Sprint 4.7.7:
- legenda dinâmica do narrador sincronizada pelos tempos reais do edge-tts;
- fallback estável por frases quando não há sync;
- múltiplas legendas extras com início/fim/posição;
- marca d'água por texto ou imagem/logo;
- prévia aplicada e exportação final usando FFmpeg.
"""

from __future__ import annotations

import os
import json
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
    watermark_image_path: Optional[Path] = None
    watermark_image_position: str = "superior direito"
    watermark_image_scale_percent: float = 14.0
    watermark_image_opacity: float = 0.78
    duration_seconds: float = 0.0


class LayeredEditorService:
    """Exportar vídeos finais usando camadas simples e FFmpeg."""

    def __init__(self, timeout_seconds: int = 1200) -> None:
        self.timeout_seconds = max(120, int(timeout_seconds or 1200))
        self.ffmpeg_binary = os.environ.get("FFMPEG_BINARY", "ffmpeg")
        self.ffprobe_binary = os.environ.get("FFPROBE_BINARY", "ffprobe")

    # ------------------------------------------------------------------
    # Exportação / prévia
    # ------------------------------------------------------------------
    def export_final_video(self, options: EditorExportOptions) -> Dict[str, Any]:
        return self._export_with_ffmpeg(options, preview=False)

    def export_preview_video(self, options: EditorExportOptions) -> Dict[str, Any]:
        return self._export_with_ffmpeg(options, preview=True)

    def _export_with_ffmpeg(self, options: EditorExportOptions, preview: bool = False) -> Dict[str, Any]:
        base_video = Path(options.base_video_path)
        if not base_video.exists():
            raise LayeredEditorError(f"Vídeo base não encontrado:\n{base_video}")

        if preview:
            output_path = Path(options.output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if output_path.exists():
                    output_path.unlink()
            except Exception:
                output_path = self._unique_path(output_path)
        else:
            output_path = self._unique_path(Path(options.output_path))
            output_path.parent.mkdir(parents=True, exist_ok=True)

        has_narration_audio = bool(options.narration_audio_path and Path(options.narration_audio_path).exists())
        has_watermark_image = bool(options.watermark_image_path and Path(options.watermark_image_path).exists())

        cmd: List[str] = [self.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error", "-i", str(base_video)]
        narration_index: Optional[int] = None
        watermark_index: Optional[int] = None
        input_index = 1
        if has_narration_audio:
            narration_index = input_index
            cmd.extend(["-i", str(options.narration_audio_path)])
            input_index += 1
        if has_watermark_image:
            watermark_index = input_index
            cmd.extend(["-i", str(options.watermark_image_path)])
            input_index += 1

        subtitle_filters: List[str] = []
        for subtitle_path in (
            options.anime_subtitle_path,
            options.narrator_subtitle_path,
            options.extra_text_subtitle_path,
            options.watermark_subtitle_path,
        ):
            if subtitle_path and Path(subtitle_path).exists():
                escaped = self._escape_subtitle_filter_path(Path(subtitle_path))
                subtitle_filters.append(f"subtitles='{escaped}'")

        needs_filter_complex = bool(has_narration_audio or has_watermark_image)
        original_volume = self._clamp_float(options.original_volume, 0.0, 2.0)
        narration_volume = self._clamp_float(options.narration_volume, 0.0, 2.0)

        # A prévia é mais leve, mas ainda deve mostrar todas as camadas aplicadas.
        video_chain_filters = list(subtitle_filters)
        if preview:
            video_chain_filters.append("scale=-2:720")
        vf_chain = ",".join(video_chain_filters) if video_chain_filters else "null"

        if needs_filter_complex:
            filter_parts: List[str] = []
            video_label = "vsub"
            filter_parts.append(f"[0:v]{vf_chain}[{video_label}]")

            if has_watermark_image and watermark_index is not None:
                scale_percent = self._clamp_float(options.watermark_image_scale_percent, 3.0, 60.0) / 100.0
                opacity = self._clamp_float(options.watermark_image_opacity, 0.05, 1.0)
                filter_parts.append(
                    f"[{watermark_index}:v]format=rgba,scale=iw*{scale_percent:.4f}:-1,"
                    f"colorchannelmixer=aa={opacity:.3f}[wm]"
                )
                x_expr, y_expr = self._overlay_xy(options.watermark_image_position)
                filter_parts.append(f"[{video_label}][wm]overlay={x_expr}:{y_expr}[vout]")
                video_label = "vout"

            if has_narration_audio and narration_index is not None:
                filter_parts.append(f"[0:a]volume={original_volume:.3f}[a0]")
                filter_parts.append(f"[{narration_index}:a]volume={narration_volume:.3f}[a1]")
                filter_parts.append("[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]")
                cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", f"[{video_label}]", "-map", "[aout]"])
            else:
                filter_parts.append(f"[0:a]volume={original_volume:.3f}[aout]")
                cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", f"[{video_label}]", "-map", "[aout]"])

            cmd.extend([
                "-c:v", "libx264",
                "-preset", "ultrafast" if preview else "veryfast",
                "-crf", "28" if preview else "20",
                "-c:a", "aac",
                "-b:a", "128k" if preview else "192k",
                "-movflags", "+faststart",
            ])
            if has_narration_audio:
                cmd.append("-shortest")
            cmd.append(str(output_path))
        else:
            # Caminho simples quando só há legendas ASS/texto e áudio original.
            if video_chain_filters:
                cmd.extend(["-vf", ",".join(video_chain_filters), "-af", f"volume={original_volume:.3f}"])
                cmd.extend(["-c:v", "libx264", "-preset", "ultrafast" if preview else "veryfast", "-crf", "28" if preview else "20"])
            else:
                cmd.extend(["-c:v", "copy", "-af", f"volume={original_volume:.3f}"])
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "128k" if preview else "192k",
                "-movflags", "+faststart",
                str(output_path),
            ])

        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_seconds)
        if completed.returncode != 0 or not output_path.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            label = "prévia aplicada" if preview else "vídeo final"
            raise LayeredEditorError(f"FFmpeg não conseguiu gerar {label}.\n{detail[:1600]}")

        return {
            "output_path": str(output_path),
            "used_layers": {
                "anime_subtitle": bool(options.anime_subtitle_path and Path(options.anime_subtitle_path).exists()),
                "narrator_subtitle": bool(options.narrator_subtitle_path and Path(options.narrator_subtitle_path).exists()),
                "extra_text": bool(options.extra_text_subtitle_path and Path(options.extra_text_subtitle_path).exists()),
                "watermark_text": bool(options.watermark_subtitle_path and Path(options.watermark_subtitle_path).exists()),
                "watermark_image": has_watermark_image,
                "watermark_image_path": str(options.watermark_image_path or ""),
                "narration_audio": has_narration_audio,
                "original_volume": options.original_volume,
                "narration_volume": options.narration_volume,
            },
        }

    # ------------------------------------------------------------------
    # ASS / camadas de texto
    # ------------------------------------------------------------------
    def generate_narrator_ass(
        self,
        script: str,
        output_path: Path,
        duration_seconds: float,
        position: str = "superior",
        title: str = "Legenda do narrador",
        dynamic_words: bool = True,
    ) -> Path:
        """Gerar ASS da narração.

        dynamic_words=True gera uma legenda estilo karaoke: a palavra que está
        sendo dita fica destacada conforme o tempo avança dentro de cada bloco.
        A sincronização ainda é estimada pelo número de palavras, mas fica bem
        mais próxima da fala do narrador do que uma legenda estática inteira.
        """
        text = str(script or "").strip()
        if not text:
            raise LayeredEditorError("Roteiro do narrador vazio. Gere ou escreva a narração antes.")
        duration = max(1.0, float(duration_seconds or 1.0))
        cues = self._split_script_into_cues(text, duration)
        if dynamic_words:
            ass = self._format_karaoke_ass(
                cues,
                title=title,
                style_name="Narrador",
                font_size=56,
                alignment=self._alignment_for_position(position, default=8),
                margin_v=58,
            )
        else:
            ass = self._format_ass(
                cues,
                title=title,
                style_name="Narrador",
                font_size=44,
                alignment=self._alignment_for_position(position, default=8),
                margin_v=46,
                primary="&H00FFFFFF",
                outline="&H00000000",
                back="&H88000000",
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass, encoding="utf-8")
        return output_path

    def generate_narrator_ass_from_sync(
        self,
        script: str,
        sync_path: Path,
        output_path: Path,
        duration_seconds: float,
        position: str = "superior",
        title: str = "Legenda do narrador sincronizada",
    ) -> Path:
        """Gerar legenda dinâmica usando WordBoundary real do edge-tts.

        Sprint 4.7.13:
        - remove o modelo visual anterior que tentava trocar estilo no meio
          da mesma linha e, em alguns players/libass, deixava tudo amarelo;
        - usa uma única linha ativa por vez;
        - aplica cor explícita em CADA palavra: branco para contexto e
          laranja apenas na palavra que está sendo falada;
        - se o renderizador ignorar as tags, a legenda cai para branco, nunca
          para tudo amarelo.
        """
        words = self._load_sync_words(sync_path)
        if not words:
            raise LayeredEditorError(
                "Não encontrei dados de sincronização da narração.\n\n"
                "Gere o áudio da narração novamente nesta versão para criar a legenda dinâmica perfeita."
            )
        duration = max(1.0, float(duration_seconds or 1.0))
        cues = self._split_timed_words_into_cues(words, max_duration=duration)
        ass = self._format_dynamic_word_highlight_ass(
            cues,
            title=title,
            style_name="NarradorDyn",
            font_size=36,
            alignment=self._alignment_for_position(position, default=8),
            margin_v=38,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass, encoding="utf-8")
        return output_path

    def generate_narrator_stable_blocks_ass(
        self,
        script: str,
        output_path: Path,
        duration_seconds: float,
        position: str = "superior",
        title: str = "Legenda do narrador estável",
    ) -> Path:
        """Fallback profissional: legenda por blocos/frases, sem destaque fora de sync."""
        text = str(script or "").strip()
        if not text:
            raise LayeredEditorError("Roteiro do narrador vazio. Gere ou escreva a narração antes.")
        cues = self._split_script_into_cues(text, max(1.0, float(duration_seconds or 1.0)))
        ass = self._format_ass(
            cues,
            title=title,
            style_name="Narrador",
            font_size=46,
            alignment=self._alignment_for_position(position, default=8),
            margin_v=46,
            primary="&H00FFFFFF",
            outline="&H00000000",
            back="&H88000000",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass, encoding="utf-8")
        return output_path

    def generate_extra_texts_ass(
        self,
        entries: Sequence[Dict[str, Any]],
        output_path: Path,
        duration_seconds: float,
        title: str = "Legendas extras TEDVHS",
    ) -> Optional[Path]:
        """Gerar um único ASS com várias legendas extras cronometradas."""
        duration = max(1.0, float(duration_seconds or 1.0))
        cues: List[Dict[str, Any]] = []
        for item in entries or []:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start = self._clamp_float(float(item.get("start") or 0.0), 0.0, duration)
            end = self._clamp_float(float(item.get("end") or min(duration, start + 15.0)), 0.0, duration)
            if end <= start:
                end = min(duration, start + 1.0)
            position = str(item.get("position") or "centro")
            cues.append({"start": start, "end": end, "text": text, "position": position})
        if not cues:
            return None
        ass = self._format_positioned_ass(
            cues,
            title=title,
            style_name="TextoExtra",
            font_size=38,
            primary="&H00FFFFFF",
            outline="&H00000000",
            back="&H99000000",
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
        start_seconds: float = 0.0,
        end_seconds: Optional[float] = None,
    ) -> Optional[Path]:
        value = str(text or "").strip()
        if not value:
            return None
        duration = max(1.0, float(duration_seconds or 1.0))
        end = duration if end_seconds is None else float(end_seconds)
        return self.generate_extra_texts_ass(
            [{"text": value, "start": start_seconds, "end": end, "position": position}],
            output_path,
            duration_seconds=duration,
            title=title,
        )

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

    def create_positioned_subtitle_copy(self, source_ass_path: Path, output_path: Path, position: str) -> Path:
        """Criar ASS limpo/posicionado para a camada de legenda do anime.

        A versão anterior apenas copiava o .ass e trocava o alinhamento. Isso
        mantinha arquivos ASS gerados a partir de SRT mal formatado, fazendo o
        vídeo mostrar números e linhas de tempo na tela. Agora esta função:
        - aceita .ass, .srt ou .vtt;
        - quando o .ass parece contaminado por timestamps de SRT, tenta usar o
          .srt irmão;
        - se precisar, converte SRT/VTT para ASS limpo;
        - reduz o tamanho da fonte para não ficar enorme no preview.
        """
        source = Path(source_ass_path)
        if not source.exists():
            raise LayeredEditorError(f"Legenda não encontrada:\n{source}")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = source.read_text(encoding="utf-8", errors="replace")
        source_to_use = source
        # Se o ASS contém blocos de SRT dentro do texto, preferimos reconstruir
        # a legenda a partir do .srt irmão quando existir.
        if source.suffix.lower() == ".ass" and self._ass_looks_contaminated(content):
            sibling_srt = source.with_suffix(".srt")
            if sibling_srt.exists():
                source_to_use = sibling_srt
                content = sibling_srt.read_text(encoding="utf-8", errors="replace")

        alignment = self._alignment_for_position(position, default=2)

        if source_to_use.suffix.lower() in {".srt", ".vtt"} or not self._is_valid_ass(content) or self._ass_looks_contaminated(content):
            cues = self._parse_subtitle_cues(content)
            if not cues:
                raise LayeredEditorError(
                    "Não consegui limpar/converter a legenda do anime. Gere a legenda PT-BR novamente na aba Montagem."
                )
            ass = self._format_clean_anime_ass(
                cues,
                title="Legenda anime PT-BR TEDVHS",
                alignment=alignment,
            )
            output_path.write_text(ass, encoding="utf-8")
            return output_path

        # ASS válido: ajusta alinhamento e reduz fonte/margem para padrão TEDVHS.
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
                def set_field(name: str, value: str) -> None:
                    try:
                        idx = fmt_fields.index(name)
                        if idx < len(values):
                            values[idx] = value
                    except ValueError:
                        pass
                set_field("alignment", str(alignment))
                set_field("fontsize", "42")
                set_field("marginv", "64" if alignment == 2 else "48")
                line = f"{prefix}: " + ",".join(values)
            lines.append(line)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    # ------------------------------------------------------------------
    # Helpers ASS / sincronização
    # ------------------------------------------------------------------
    def _split_script_into_cues(self, script: str, duration_seconds: float) -> List[Dict[str, Any]]:
        clean = str(script or "").strip().replace("\r", "\n")
        clean = re.sub(r"^(roteiro|narra[cç][aã]o|texto do narrador)\s*:\s*", "", clean, flags=re.I).strip()
        paragraphs = [p.strip() for p in clean.split("\n") if p.strip()]
        if len(paragraphs) >= 2:
            raw_chunks = paragraphs
        else:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", re.sub(r"\s+", " ", clean)) if s.strip()]
            raw_chunks = sentences or [clean]

        chunks: List[str] = []
        for part in raw_chunks:
            words = part.split()
            current: List[str] = []
            for word in words:
                if sum(len(w) + 1 for w in current) + len(word) > 64 and current:
                    chunks.append(" ".join(current).strip())
                    current = [word]
                else:
                    current.append(word)
            if current:
                chunks.append(" ".join(current).strip())
        chunks = [chunk for chunk in chunks if chunk]
        if not chunks:
            return [{"start": 0.0, "end": duration_seconds, "text": clean}]

        # Distribuição por palavras, com pequena folga por bloco para ficar mais natural.
        total_words = max(1, sum(len(chunk.split()) for chunk in chunks))
        start = 0.0
        cues: List[Dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            words = max(1, len(chunk.split()))
            if index == len(chunks) - 1:
                end = duration_seconds
            else:
                end = start + duration_seconds * (words / total_words)
                end = max(end, start + 1.15)
                end = min(end, duration_seconds)
            cues.append({"start": start, "end": max(end, start + 0.80), "text": chunk})
            start = end
            if start >= duration_seconds:
                break
        return cues

    def _format_karaoke_ass(
        self,
        cues: Sequence[Dict[str, Any]],
        title: str,
        style_name: str,
        font_size: int,
        alignment: int,
        margin_v: int,
    ) -> str:
        header = self._ass_header(
            title=title,
            style_name=style_name,
            font_size=font_size,
            alignment=alignment,
            margin_v=margin_v,
            primary="&H00FFFFFF",     # palavra já falada / destacada
            secondary="&H0000D7FF",   # amarelo/laranja da palavra no karaoke
            outline="&H00000000",
            back="&H88000000",
        )
        lines = list(header)
        for cue in cues:
            start_f = float(cue.get("start") or 0.0)
            end_f = float(cue.get("end") or 0.0)
            words = self._words_for_karaoke(str(cue.get("text") or ""))
            if not words:
                continue
            duration_cs = max(1, int(round(max(0.4, end_f - start_f) * 100)))
            weights = [max(1, len(re.sub(r"\W+", "", word))) for word in words]
            total_weight = max(1, sum(weights))
            allocated = 0
            parts: List[str] = []
            for idx, word in enumerate(words):
                if idx == len(words) - 1:
                    cs = max(1, duration_cs - allocated)
                else:
                    cs = max(1, int(round(duration_cs * (weights[idx] / total_weight))))
                    allocated += cs
                safe = self._ass_text_no_wrap(word)
                parts.append(r"{\k" + str(cs) + "}" + safe)
            text = " ".join(parts)
            lines.append(f"Dialogue: 0,{self._ass_time(start_f)},{self._ass_time(end_f)},{style_name},,0,0,0,,{text}")
        return "\n".join(lines) + "\n"

    def _is_valid_ass(self, content: str) -> bool:
        lower = str(content or "").lower()
        return "[script info]" in lower and "[events]" in lower and "dialogue:" in lower

    def _ass_looks_contaminated(self, content: str) -> bool:
        value = str(content or "")
        # ASS válido não deve exibir linhas SRT dentro do campo Text.
        return bool(re.search(r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}", value))

    def _parse_subtitle_cues(self, content: str) -> List[Dict[str, Any]]:
        """Parser robusto para SRT/VTT mesmo quando não há linha em branco entre cues."""
        raw = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
        raw = re.sub(r"^```(?:srt|vtt)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        time_re = re.compile(
            r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?:[^\n]*)"
        )
        matches = list(time_re.finditer(raw))
        cues: List[Dict[str, Any]] = []
        for index, match in enumerate(matches):
            start = self._parse_sub_time(match.group("start"))
            end = self._parse_sub_time(match.group("end"))
            text_start = match.end()
            text_end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
            block = raw[text_start:text_end]
            lines = []
            for line in block.split("\n"):
                line = line.strip("\ufeff \t")
                if not line:
                    continue
                if re.fullmatch(r"\d+", line):
                    continue
                if time_re.search(line):
                    continue
                lines.append(line)
            text = self._clean_subtitle_text_basic("\n".join(lines))
            if text and end > start:
                cues.append({"start": start, "end": end, "text": text})
        return cues

    def _format_clean_anime_ass(self, cues: Sequence[Dict[str, Any]], title: str, alignment: int) -> str:
        margin_v = 64 if alignment == 2 else 48
        header = self._ass_header(
            title=title,
            style_name="AnimePTBR",
            font_size=42,
            alignment=alignment,
            margin_v=margin_v,
            primary="&H00FFFFFF",
            secondary="&H000000FF",
            outline="&H00000000",
            back="&H7F000000",
        )
        lines = list(header)
        for cue in cues:
            text = self._ass_text(str(cue.get("text") or ""))
            if text:
                lines.append(
                    f"Dialogue: 0,{self._ass_time(float(cue.get('start') or 0.0))},{self._ass_time(float(cue.get('end') or 0.0))},AnimePTBR,,0,0,0,,{text}"
                )
        return "\n".join(lines) + "\n"

    def _clean_subtitle_text_basic(self, text: str) -> str:
        value = str(text or "")
        value = re.sub(r"<[^>]+>", "", value)
        value = re.sub(r"\{[^{}]*\}", "", value)
        value = value.replace("\\N", "\n")
        value = re.sub(r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}", "", value)
        value = re.sub(r"(?m)^\s*\d+\s*$", "", value)
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    @staticmethod
    def _parse_sub_time(text: str) -> float:
        value = str(text or "").strip().replace(",", ".")
        match = re.match(r"(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", value)
        if not match:
            return 0.0
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        ms = int((match.group(4) or "0").ljust(3, "0")[:3])
        return hours * 3600 + minutes * 60 + seconds + ms / 1000.0

    def _load_sync_words(self, sync_path: Path) -> List[Dict[str, Any]]:
        """Carrega o sync da narração e garante unidades de PALAVRA.

        O arquivo enviado pelo Higor provou o bug: algumas versões do edge-tts
        entregam boundaries por FRASE, mas o app estava tratando a frase inteira
        como se fosse uma palavra. Resultado: a legenda da narração ficava
        toda amarela/destacada.

        Aqui a regra é: a saída desta função sempre é word-by-word. Se o sync
        vier em frases, quebramos a frase em palavras dentro do intervalo real
        daquela frase. Isso mantém uma ÚNICA legenda da narração e evita frase
        inteira destacada.
        """
        path = Path(sync_path)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(data, dict) or data.get("estimated"):
            return []
        raw_words = data.get("words")
        if not isinstance(raw_words, list):
            return []
        words: List[Dict[str, Any]] = []
        for item in raw_words:
            if not isinstance(item, dict):
                continue
            raw_text = str(item.get("word") or item.get("text") or "").strip()
            if not raw_text:
                continue
            try:
                start = max(0.0, float(item.get("start") or 0.0))
                end = max(start + 0.04, float(item.get("end") or start + float(item.get("duration") or 0.12)))
            except Exception:
                continue
            pieces = self._split_sync_text_into_word_boundaries(raw_text, start, end)
            if pieces:
                words.extend(pieces)
        words.sort(key=lambda value: float(value.get("start") or 0.0))
        return words

    def _split_sync_text_into_word_boundaries(self, text: str, start: float, end: float) -> List[Dict[str, Any]]:
        """Quebra um boundary de frase em palavras sem duplicar legenda.

        Quando o edge-tts retorna uma frase inteira em um único item, não existe
        como destacar apenas uma palavra se tratarmos aquilo como token único.
        Esta função divide a frase em tokens e distribui os tempos dentro do
        intervalo real do boundary recebido.
        """
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if not value:
            return []
        tokens = re.findall(r"[^\s]+", value)
        if not tokens:
            return []
        start = max(0.0, float(start or 0.0))
        end = max(start + 0.04, float(end or start + 0.12))
        if len(tokens) == 1:
            return [{"word": tokens[0], "start": start, "end": end, "duration": max(0.04, end - start)}]

        # Peso por tamanho da palavra + pequenas pausas em pontuação forte.
        weights: List[float] = []
        for token in tokens:
            base = max(1.0, float(len(re.sub(r"\W+", "", token))))
            if token.rstrip().endswith((".", "!", "?", "…", ":", ";")):
                base += 2.0
            elif token.rstrip().endswith((",",)):
                base += 1.0
            weights.append(base)
        total = max(1.0, sum(weights))
        duration = max(0.04 * len(tokens), end - start)
        cursor = start
        out: List[Dict[str, Any]] = []
        for idx, token in enumerate(tokens):
            if idx == len(tokens) - 1:
                token_end = end
            else:
                token_end = cursor + duration * (weights[idx] / total)
                token_end = min(end - 0.04 * (len(tokens) - idx - 1), token_end)
            token_end = max(cursor + 0.04, token_end)
            out.append({
                "word": token,
                "start": round(cursor, 4),
                "end": round(min(end, token_end), 4),
                "duration": round(max(0.04, min(end, token_end) - cursor), 4),
            })
            cursor = min(end, token_end)
        return out

    def _split_timed_words_into_cues(self, words: Sequence[Dict[str, Any]], max_duration: float) -> List[Dict[str, Any]]:
        cues: List[Dict[str, Any]] = []
        current: List[Dict[str, Any]] = []
        char_count = 0
        max_duration = max(1.0, float(max_duration or 1.0))

        def flush() -> None:
            nonlocal current, char_count
            if not current:
                return
            start = max(0.0, float(current[0].get("start") or 0.0))
            end = min(max_duration, max(start + 0.20, float(current[-1].get("end") or start + 0.20)))
            cues.append({"start": start, "end": end, "words": list(current)})
            current = []
            char_count = 0

        for item in words:
            word = str(item.get("word") or "").strip()
            if not word:
                continue
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or start + 0.10)
            if start > max_duration:
                break
            # troca de linha em pontuação forte, pausa longa, ou texto grande.
            pause = 0.0
            if current:
                pause = max(0.0, start - float(current[-1].get("end") or start))
            should_flush = bool(current) and (
                len(current) >= 7
                or char_count + len(word) > 42
                or pause >= 0.55
                or str(current[-1].get("word") or "").rstrip().endswith((".", "!", "?", "…", ":", ";"))
            )
            if should_flush:
                flush()
            current.append({"word": word, "start": max(0.0, start), "end": max(start + 0.04, end)})
            char_count += len(word) + 1
        flush()
        return cues

    def _format_dynamic_word_highlight_ass(
        self,
        cues: Sequence[Dict[str, Any]],
        title: str,
        style_name: str,
        font_size: int,
        alignment: int,
        margin_v: int,
    ) -> str:
        """Legenda dinâmica REAL da NARRAÇÃO no padrão TikTok/Reels.

        Sprint 4.7.16:
        - a legenda do anime continua separada e normal;
        - esta função gera APENAS a legenda da narração;
        - não duplica texto em duas linhas;
        - não usa sync estimado;
        - cada palavra cria um único evento curto com a frase/trecho inteiro;
        - todas as palavras ficam brancas, exceto a palavra falada no momento,
          que fica amarelo/laranja.

        O segredo é não usar "linha branca + linha amarela" e também não usar
        estilo amarelo como base. A base sempre é branca, e o destaque é um
        override local só na palavra atual.
        """
        normal_style = f"{style_name}TikTok"
        highlight_style = f"{style_name}Unused"
        base_size = max(30, min(42, int(font_size or 36)))
        active_size = base_size  # mesmo tamanho; destaque é cor + leve negrito
        lines = self._dynamic_word_header(
            title=title,
            normal_style=normal_style,
            highlight_style=highlight_style,
            font_size=base_size,
            alignment=alignment,
            margin_v=margin_v,
        )

        white = r"&HFFFFFF&"       # ASS: BGR, branco
        orange = r"&H00D7FF&"      # ASS: BGR, laranja/amarelo TEDVHS

        for cue in cues:
            timed_words = list(cue.get("words") or [])
            if not timed_words:
                continue

            cue_end = max(float(cue.get("end") or 0.0), float(timed_words[-1].get("end") or 0.0))

            # Janela curta para caber no vídeo. Não mostramos a narração inteira.
            for idx, item in enumerate(timed_words):
                try:
                    start_f = max(0.0, float(item.get("start") or 0.0))
                except Exception:
                    continue

                if idx + 1 < len(timed_words):
                    try:
                        next_start = max(start_f + 0.055, float(timed_words[idx + 1].get("start") or start_f + 0.18))
                    except Exception:
                        next_start = start_f + 0.18
                    end_f = min(cue_end, next_start - 0.003)
                else:
                    try:
                        real_end = float(item.get("end") or start_f + 0.22)
                    except Exception:
                        real_end = start_f + 0.22
                    end_f = min(cue_end, max(real_end, start_f + 0.16))

                if end_f <= start_f + 0.035:
                    end_f = min(cue_end, start_f + 0.12)
                if end_f <= start_f:
                    continue

                # Mostra um trecho curto em uma única linha/bloco. A palavra
                # atual fica destacada no meio da própria frase, sem duplicar.
                left = max(0, idx - 3)
                right = min(len(timed_words), idx + 4)
                parts: List[str] = []
                for source_index in range(left, right):
                    word = self._ass_text_no_wrap(str(timed_words[source_index].get("word") or ""))
                    if not word:
                        continue
                    if source_index == idx:
                        parts.append(rf"{{\c{orange}\fs{active_size}\b1}}{word}{{\b0\c{white}\fs{base_size}}}")
                    else:
                        parts.append(rf"{{\c{white}\fs{base_size}\b0}}{word}")

                text = " ".join(parts).strip()
                if not text:
                    continue

                # Garantia final: volta para branco ao fim do evento para não
                # contaminar a próxima fala no libass/FFmpeg.
                text += rf"{{\b0\c{white}\fs{base_size}}}"
                lines.append(
                    f"Dialogue: 9,{self._ass_time(start_f)},{self._ass_time(end_f)},{normal_style},,0,0,0,,{text}"
                )
        return "\n".join(lines) + "\n"

    def _dynamic_word_header(
        self,
        title: str,
        normal_style: str,
        highlight_style: str,
        font_size: int,
        alignment: int,
        margin_v: int,
    ) -> List[str]:
        safe_title = str(title or "TEDVHS")
        normal_size = max(30, min(42, int(font_size or 36)))
        # Cores ASS são BGR. A base da narração dinâmica SEMPRE é branca.
        # O amarelo só aparece por override local na palavra falada.
        return [
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
            f"Style: {normal_style},Arial,{normal_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H88000000,-1,0,0,0,100,100,0,0,1,4,1,{alignment},80,80,{margin_v},1",
            # Mantido apenas por compatibilidade com chamadas antigas; não é usado.
            f"Style: {highlight_style},Arial,{normal_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H88000000,-1,0,0,0,100,100,0,0,1,4,1,{alignment},80,80,{margin_v},1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]

    def _wrap_ass_words(self, text: str, max_chars: int = 42) -> str:
        """Quebra linha sem destruir comandos ASS."""
        value = str(text or "")
        visible = re.sub(r"\{[^}]*\}", "", value)
        if len(visible) <= max_chars:
            return value
        words = value.split()
        left: List[str] = []
        right: List[str] = []
        visible_count = 0
        half = max(10, len(visible) // 2)
        target_left = True
        for word in words:
            clean = re.sub(r"\{[^}]*\}", "", word)
            if target_left and visible_count + len(clean) <= half:
                left.append(word)
                visible_count += len(clean) + 1
            else:
                target_left = False
                right.append(word)
        if left and right:
            return " ".join(left) + r"\N" + " ".join(right)
        return value

    def _format_timed_karaoke_ass(
        self,
        cues: Sequence[Dict[str, Any]],
        title: str,
        style_name: str,
        font_size: int,
        alignment: int,
        margin_v: int,
    ) -> str:
        header = self._ass_header(
            title=title,
            style_name=style_name,
            font_size=font_size,
            alignment=alignment,
            margin_v=margin_v,
            primary="&H00FFFFFF",
            secondary="&H0000D7FF",
            outline="&H00000000",
            back="&H88000000",
        )
        lines = list(header)
        for cue in cues:
            timed_words = cue.get("words") or []
            if not timed_words:
                continue
            start_f = max(0.0, float(cue.get("start") or 0.0))
            end_f = max(start_f + 0.20, float(cue.get("end") or start_f + 0.20))
            parts: List[str] = []
            cursor = start_f
            for idx, item in enumerate(timed_words):
                word = str(item.get("word") or "").strip()
                if not word:
                    continue
                w_start = max(cursor, float(item.get("start") or cursor))
                next_start = None
                if idx + 1 < len(timed_words):
                    try:
                        next_start = float(timed_words[idx + 1].get("start") or 0.0)
                    except Exception:
                        next_start = None
                w_end = float(item.get("end") or w_start + 0.12)
                hold_until = max(w_end, next_start if next_start is not None else w_end)
                if w_start > cursor + 0.03:
                    gap_cs = max(1, int(round((w_start - cursor) * 100)))
                    parts.append(r"{\k" + str(gap_cs) + "}")
                cs = max(1, int(round(max(0.04, hold_until - w_start) * 100)))
                parts.append(r"{\k" + str(cs) + "}" + self._ass_text_no_wrap(word))
                cursor = max(cursor, hold_until)
            text = " ".join(part for part in parts if part)
            if text:
                lines.append(f"Dialogue: 0,{self._ass_time(start_f)},{self._ass_time(end_f)},{style_name},,0,0,0,,{text}")
        return "\n".join(lines) + "\n"

    def _format_positioned_ass(
        self,
        cues: Sequence[Dict[str, Any]],
        title: str,
        style_name: str,
        font_size: int,
        primary: str,
        outline: str,
        back: str,
    ) -> str:
        styles: Dict[int, str] = {}
        for cue in cues:
            alignment = self._alignment_for_position(str(cue.get("position") or "centro"), default=5)
            styles[alignment] = f"{style_name}{alignment}"
        header = [
            "[Script Info]",
            f"Title: {str(title or 'TEDVHS')}",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "",
            "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        ]
        for alignment, name in sorted(styles.items()):
            header.append(f"Style: {name},Arial,{font_size},{primary},&H000000FF,{outline},{back},-1,0,0,0,100,100,0,0,1,3,1,{alignment},80,80,80,1")
        header.extend(["", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"])
        lines = list(header)
        for cue in cues:
            alignment = self._alignment_for_position(str(cue.get("position") or "centro"), default=5)
            style = styles.get(alignment, f"{style_name}{alignment}")
            text = self._ass_text(str(cue.get("text") or ""))
            if text:
                lines.append(f"Dialogue: 0,{self._ass_time(float(cue.get('start') or 0.0))},{self._ass_time(float(cue.get('end') or 0.0))},{style},,0,0,0,,{text}")
        return "\n".join(lines) + "\n"

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
        header = self._ass_header(title, style_name, font_size, alignment, margin_v, primary, "&H000000FF", outline, back)
        lines = list(header)
        for cue in cues:
            text = self._ass_text(str(cue.get("text") or ""))
            if text:
                lines.append(f"Dialogue: 0,{self._ass_time(float(cue.get('start') or 0.0))},{self._ass_time(float(cue.get('end') or 0.0))},{style_name},,0,0,0,,{text}")
        return "\n".join(lines) + "\n"

    def _ass_header(
        self,
        title: str,
        style_name: str,
        font_size: int,
        alignment: int,
        margin_v: int,
        primary: str,
        secondary: str,
        outline: str,
        back: str,
    ) -> List[str]:
        safe_title = str(title or "TEDVHS")
        return [
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
            f"Style: {style_name},Arial,{font_size},{primary},{secondary},{outline},{back},-1,0,0,0,100,100,0,0,1,4,1,{alignment},80,80,{margin_v},1",
            "",
            "[Events]",
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
        ]

    def _words_for_karaoke(self, text: str) -> List[str]:
        # Mantém pontuação grudada à palavra, mas evita chaves ASS.
        value = str(text or "").replace("{", "").replace("}", "")
        return [part for part in re.split(r"\s+", value.strip()) if part]

    def _ass_text(self, text: str) -> str:
        value = self._ass_text_no_wrap(text)
        if r"\N" not in value and len(value) > 48:
            words = value.split()
            mid = max(1, len(words) // 2)
            value = " ".join(words[:mid]) + r"\N" + " ".join(words[mid:])
        return value

    def _ass_text_no_wrap(self, text: str) -> str:
        value = str(text or "").replace("{", "").replace("}", "")
        value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")
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

    def _watermark_alignment(self, position: str) -> int:
        text = str(position or "").lower()
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

    def _overlay_xy(self, position: str) -> tuple[str, str]:
        text = str(position or "").lower()
        margin = "40"
        if "baixo" in text or "infer" in text or "bottom" in text:
            y = f"H-h-{margin}"
        elif "cent" in text or "meio" in text:
            y = "(H-h)/2"
        else:
            y = margin
        if "esquer" in text or "left" in text:
            x = margin
        elif "cent" in text or "meio" in text:
            x = "(W-w)/2"
        else:
            x = f"W-w-{margin}"
        return x, y

    # ------------------------------------------------------------------
    # FFprobe / paths
    # ------------------------------------------------------------------
    def probe_duration(self, media_path: str | Path) -> float:
        path = Path(media_path)
        if not path.exists():
            return 0.0
        cmd = [
            self.ffprobe_binary,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if completed.returncode == 0:
                return max(0.0, float((completed.stdout or "0").strip() or 0.0))
        except Exception:
            return 0.0
        return 0.0

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

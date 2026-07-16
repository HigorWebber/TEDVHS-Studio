"""Serviço de legendas PT-BR para clipes exportados.

Fluxo híbrido:
1. tenta usar legenda PT-BR do arquivo original;
2. se só houver legenda em outro idioma, recorta e traduz para PT-BR via Gemini API;
3. se não houver legenda, transcreve/traduz o áudio do clipe via Gemini API;
4. salva SRT + ASS estilo anime/TikTok ao lado do MP4 final.

A implementação usa apenas biblioteca padrão + FFmpeg/FFprobe para evitar novas dependências.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import socket
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_SUBTITLE_MODEL = "gemini-3.1-flash-lite"


class SubtitleGenerationError(RuntimeError):
    """Erro amigável do sistema de legendas."""


@dataclass
class SubtitleStream:
    order: int
    index: int
    codec: str
    language: str
    title: str

    @property
    def display_name(self) -> str:
        language = self.language or "und"
        title = f" - {self.title}" if self.title else ""
        return f"{language.upper()} / {self.codec}{title}"


@dataclass
class SrtCue:
    start: float
    end: float
    text: str


class HybridSubtitleService:
    """Gerar legendas PT-BR para clipes com fonte híbrida."""

    def __init__(self, timeout_seconds: int = 180) -> None:
        self.timeout_seconds = max(45, int(timeout_seconds or 180))
        self.ffmpeg_binary = os.environ.get("FFMPEG_BINARY", "ffmpeg")
        self.ffprobe_binary = os.environ.get("FFPROBE_BINARY", "ffprobe")
        self.gemini_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def generate_ptbr_subtitle(
        self,
        clip: Dict[str, Any],
        api_key: str = "",
        model: str = DEFAULT_GEMINI_SUBTITLE_MODEL,
    ) -> Dict[str, Any]:
        """Gerar legenda PT-BR do clipe e retornar caminhos/metadata."""
        output_path = Path(str(clip.get("output_path") or ""))
        if not output_path.exists():
            raise SubtitleGenerationError(f"Arquivo MP4 do clipe não encontrado:\n{output_path}")

        source_file = Path(str(clip.get("source_file") or ""))
        segments = self._segments_for_clip(clip)
        selected_stream: Optional[SubtitleStream] = None
        source_label = ""
        cues: List[SrtCue] = []
        translation_used = False
        transcription_used = False

        if source_file.exists() and segments:
            streams = self.list_subtitle_streams(source_file)
            selected_stream = self._select_best_stream(streams)
            if selected_stream:
                source_label = selected_stream.display_name
                extracted_srt = self._extract_subtitle_stream_to_srt(source_file, selected_stream)
                source_cues = self._parse_srt(extracted_srt.read_text(encoding="utf-8", errors="replace"))
                cues = self._cut_cues_to_clip(source_cues, segments)
                if cues and not self._is_ptbr_stream(selected_stream):
                    api_key = self._clean_api_key(api_key, purpose="traduzir a legenda para PT-BR")
                    cues = self._translate_cues_ptbr(cues, api_key=api_key, model=model)
                    translation_used = True
        if not cues:
            api_key = self._clean_api_key(api_key, purpose="transcrever o áudio do clipe para PT-BR")
            cues = self._transcribe_clip_audio_ptbr(output_path, api_key=api_key, model=model)
            source_label = "Áudio do clipe via Gemini API"
            transcription_used = True

        if not cues:
            raise SubtitleGenerationError("Não foi possível gerar nenhuma legenda para este clipe.")

        srt_path = output_path.with_name(f"{output_path.stem}.pt-BR.srt")
        ass_path = output_path.with_name(f"{output_path.stem}.pt-BR.ass")
        srt_path.write_text(self._format_srt(cues), encoding="utf-8")
        ass_path.write_text(self._format_ass(cues, title=output_path.stem), encoding="utf-8")

        return {
            "srt_path": str(srt_path),
            "ass_path": str(ass_path),
            "cue_count": len(cues),
            "source": source_label or "Legenda gerada",
            "source_language": selected_stream.language if selected_stream else "auto",
            "source_codec": selected_stream.codec if selected_stream else "audio",
            "translated_to_ptbr": translation_used,
            "transcribed_from_audio": transcription_used,
            "model": self._clean_model_name(model),
            "status": "ptbr_subtitle_ready",
        }

    def export_with_burned_subtitle(self, clip: Dict[str, Any], ass_path: str | Path | None = None) -> Dict[str, Any]:
        """Exportar uma cópia MP4 com legenda ASS queimada no vídeo."""
        output_path = Path(str(clip.get("output_path") or ""))
        if not output_path.exists():
            raise SubtitleGenerationError(f"Arquivo MP4 do clipe não encontrado:\n{output_path}")

        subtitle_path = Path(str(ass_path or "")) if ass_path else self._find_existing_ass(output_path)
        if not subtitle_path.exists():
            raise SubtitleGenerationError(
                "Nenhuma legenda .ass PT-BR encontrada. Gere a legenda PT-BR antes de exportar o MP4 legendado."
            )

        final_path = self._unique_path(output_path.with_name(f"{output_path.stem} legendado.mp4"))
        subtitle_filter_path = self._escape_subtitle_filter_path(subtitle_path)
        cmd = [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(output_path),
            "-vf",
            f"subtitles='{subtitle_filter_path}'",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "copy",
            str(final_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if completed.returncode != 0 or not final_path.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise SubtitleGenerationError(f"FFmpeg não conseguiu exportar o vídeo legendado.\n{detail[:1200]}")
        return {"legendado_path": str(final_path), "subtitle_path": str(subtitle_path)}

    def list_subtitle_streams(self, source_file: str | Path) -> List[SubtitleStream]:
        source = Path(source_file)
        if not source.exists():
            return []
        cmd = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(source),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            logger.warning("ffprobe falhou ao listar legendas: %s", completed.stderr)
            return []
        try:
            data = json.loads(completed.stdout or "{}")
        except Exception:
            return []
        streams: List[SubtitleStream] = []
        order = 0
        for stream in data.get("streams") or []:
            if stream.get("codec_type") != "subtitle":
                continue
            tags = stream.get("tags") or {}
            streams.append(
                SubtitleStream(
                    order=order,
                    index=int(stream.get("index") or order),
                    codec=str(stream.get("codec_name") or "subtitle"),
                    language=str(tags.get("language") or "und").lower(),
                    title=str(tags.get("title") or ""),
                )
            )
            order += 1
        return streams

    def _select_best_stream(self, streams: Sequence[SubtitleStream]) -> Optional[SubtitleStream]:
        if not streams:
            return None
        pt = [stream for stream in streams if self._is_ptbr_stream(stream)]
        if pt:
            return pt[0]
        english = [stream for stream in streams if self._is_english_stream(stream)]
        if english:
            return english[0]
        return streams[0]

    def _is_ptbr_stream(self, stream: SubtitleStream) -> bool:
        hay = f"{stream.language} {stream.title}".lower()
        return any(token in hay for token in ["por", "pt", "pt-br", "pt_br", "brasil", "brazil", "portuguese"])

    def _is_english_stream(self, stream: SubtitleStream) -> bool:
        hay = f"{stream.language} {stream.title}".lower()
        return any(token in hay for token in ["eng", "en", "english", "ingl"])

    def _extract_subtitle_stream_to_srt(self, source_file: Path, stream: SubtitleStream) -> Path:
        temp_root = Path("data") / "subtitle_cache"
        temp_root.mkdir(parents=True, exist_ok=True)
        out_path = temp_root / f"{self._sanitize_name(source_file.stem)}_s{stream.order}.srt"
        cmd = [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_file),
            "-map",
            f"0:s:{stream.order}",
            str(out_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0 or not out_path.exists():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise SubtitleGenerationError(f"Não foi possível extrair a legenda do arquivo original.\n{detail[:1000]}")
        return out_path

    def _segments_for_clip(self, clip: Dict[str, Any]) -> List[Dict[str, float]]:
        raw = clip.get("segments") or clip.get("segments_json")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw or "[]")
            except Exception:
                parsed = []
        elif isinstance(raw, list):
            parsed = raw
        else:
            parsed = []
        segments: List[Dict[str, float]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            start = self._float_or_none(item.get("start_seconds"))
            end = self._float_or_none(item.get("end_seconds"))
            if start is None or end is None or end <= start:
                continue
            segments.append({"start_seconds": start, "end_seconds": end})
        return segments

    def _cut_cues_to_clip(self, cues: Sequence[SrtCue], segments: Sequence[Dict[str, float]]) -> List[SrtCue]:
        result: List[SrtCue] = []
        out_offset = 0.0
        for segment in segments:
            seg_start = float(segment.get("start_seconds") or 0.0)
            seg_end = float(segment.get("end_seconds") or 0.0)
            if seg_end <= seg_start:
                continue
            for cue in cues:
                if cue.end <= seg_start or cue.start >= seg_end:
                    continue
                start = max(cue.start, seg_start)
                end = min(cue.end, seg_end)
                if end <= start:
                    continue
                result.append(SrtCue(
                    start=max(0.0, out_offset + (start - seg_start)),
                    end=max(0.0, out_offset + (end - seg_start)),
                    text=cue.text,
                ))
            out_offset += max(0.0, seg_end - seg_start)
        return self._merge_and_clean_cues(result)

    def _translate_cues_ptbr(self, cues: Sequence[SrtCue], api_key: str, model: str) -> List[SrtCue]:
        translated: List[SrtCue] = []
        batch_size = 35
        for start in range(0, len(cues), batch_size):
            batch = list(cues[start : start + batch_size])
            texts = [cue.text for cue in batch]
            translated_texts = self._translate_text_batch(texts, api_key=api_key, model=model)
            if len(translated_texts) != len(batch):
                raise SubtitleGenerationError("A Gemini API retornou uma quantidade diferente de legendas traduzidas.")
            for cue, text in zip(batch, translated_texts):
                translated.append(SrtCue(cue.start, cue.end, self._clean_subtitle_text(text)))
        return translated

    def _translate_text_batch(self, texts: Sequence[str], api_key: str, model: str) -> List[str]:
        model = self._clean_model_name(model)
        prompt = (
            "Traduza as falas de legenda abaixo para português do Brasil natural, como legenda de anime.\n"
            "Mantenha nomes próprios, honoríficos importantes e o sentido original.\n"
            "Não adicione explicações. Não una nem divida itens.\n"
            "Retorne somente um JSON array de strings, com o mesmo número de itens.\n\n"
            f"Textos: {json.dumps(list(texts), ensure_ascii=False)}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 3500},
        }
        data = self._gemini_generate(api_key=api_key, model=model, payload=payload, timeout_seconds=self.timeout_seconds)
        raw = self._extract_response_text(data)
        parsed = self._parse_json_array(raw)
        return [self._clean_subtitle_text(str(item)) for item in parsed]

    def _transcribe_clip_audio_ptbr(self, clip_path: Path, api_key: str, model: str) -> List[SrtCue]:
        wav_path = self._extract_audio_wav(clip_path)
        model = self._clean_model_name(model)
        prompt = (
            "Transcreva o áudio deste clipe de anime e traduza tudo para português do Brasil.\n"
            "Retorne somente uma legenda SRT válida, com timestamps relativos ao início do áudio.\n"
            "Use frases curtas e naturais para legenda. Não inclua comentários fora do SRT.\n"
            "Formato obrigatório:\n1\n00:00:00,000 --> 00:00:02,000\nTexto em PT-BR\n"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": base64.b64encode(wav_path.read_bytes()).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 6000},
        }
        data = self._gemini_generate(api_key=api_key, model=model, payload=payload, timeout_seconds=max(self.timeout_seconds, 240))
        raw = self._extract_response_text(data)
        cues = self._parse_srt(raw)
        if not cues:
            raise SubtitleGenerationError("A Gemini API respondeu, mas não retornou um SRT válido para o áudio.")
        return self._merge_and_clean_cues(cues)

    def _extract_audio_wav(self, clip_path: Path) -> Path:
        temp_root = Path("data") / "subtitle_cache"
        temp_root.mkdir(parents=True, exist_ok=True)
        wav_path = temp_root / f"{self._sanitize_name(clip_path.stem)}_audio_16k.wav"
        cmd = [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(clip_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(wav_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size <= 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise SubtitleGenerationError(f"Não foi possível extrair áudio do clipe.\n{detail[:1000]}")
        if wav_path.stat().st_size > 18 * 1024 * 1024:
            raise SubtitleGenerationError(
                "O áudio do clipe ficou grande demais para enviar com segurança. "
                "Tente um clipe menor ou gere legenda a partir da legenda embutida."
            )
        return wav_path

    def _gemini_generate(self, api_key: str, model: str, payload: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
        api_key = self._clean_api_key(api_key, purpose="usar a Gemini API")
        safe_model = urllib.parse.quote(self._clean_model_name(model), safe="-_.~")
        url = f"{self.gemini_base_url}/models/{safe_model}:generateContent?key={urllib.parse.quote(api_key)}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(30, int(timeout_seconds or self.timeout_seconds))) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = self._read_http_error_body(exc)
            raise SubtitleGenerationError(self._friendly_http_error(exc, detail)) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise SubtitleGenerationError(f"Não foi possível conectar à Gemini API: {exc}") from exc
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise SubtitleGenerationError(f"A Gemini API respondeu algo que não era JSON válido: {raw[:500]}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise SubtitleGenerationError(f"Gemini API retornou erro: {data.get('error')}")
        return data

    def _friendly_http_error(self, exc: urllib.error.HTTPError, detail: str) -> str:
        text = detail or str(exc)
        if exc.code in {400, 404}:
            return (
                "A Gemini API recusou a requisição. Verifique o modelo usado para legendas. "
                "Sugestão: gemini-3.1-flash-lite ou gemini-2.5-flash-lite. "
                f"Detalhe: {text[:900]}"
            )
        if exc.code in {401, 403}:
            return f"API Key inválida ou sem permissão. Detalhe: {text[:900]}"
        if exc.code == 429:
            return f"Limite gratuito da Gemini API atingido. Aguarde e tente novamente. Detalhe: {text[:900]}"
        return f"Gemini API retornou erro HTTP {exc.code}. Detalhe: {text[:900]}"

    def _read_http_error_body(self, exc: urllib.error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _extract_response_text(self, data: Dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        chunks: List[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if isinstance(part, dict) and part.get("text"):
                    chunks.append(str(part.get("text")))
        return "\n".join(chunks).strip()

    def _parse_json_array(self, text: str) -> List[str]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except Exception as exc:
            raise SubtitleGenerationError(f"A Gemini API não retornou JSON de tradução válido. Resposta: {text[:900]}") from exc
        raise SubtitleGenerationError(f"A Gemini API não retornou uma lista de traduções. Resposta: {text[:900]}")

    def _parse_srt(self, text: str) -> List[SrtCue]:
        cleaned = re.sub(r"^```(?:srt)?\s*", "", text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\n\s*\n+", cleaned)
        cues: List[SrtCue] = []
        time_re = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")
        for block in blocks:
            lines = [line.strip("\ufeff ") for line in block.split("\n") if line.strip()]
            if not lines:
                continue
            time_line_index = next((idx for idx, line in enumerate(lines) if time_re.search(line)), -1)
            if time_line_index < 0:
                continue
            match = time_re.search(lines[time_line_index])
            if not match:
                continue
            start = self._parse_srt_time(match.group(1))
            end = self._parse_srt_time(match.group(2))
            cue_text = "\n".join(lines[time_line_index + 1 :]).strip()
            cue_text = self._clean_subtitle_text(cue_text)
            if cue_text and end > start:
                cues.append(SrtCue(start=start, end=end, text=cue_text))
        return self._merge_and_clean_cues(cues)

    def _format_srt(self, cues: Sequence[SrtCue]) -> str:
        blocks: List[str] = []
        for idx, cue in enumerate(cues, start=1):
            blocks.append(
                f"{idx}\n{self._format_srt_time(cue.start)} --> {self._format_srt_time(cue.end)}\n{self._clean_subtitle_text(cue.text)}"
            )
        return "\n\n".join(blocks).strip() + "\n"

    def _format_ass(self, cues: Sequence[SrtCue], title: str = "TEDVHS") -> str:
        header = f"""[Script Info]
Title: {title} - PT-BR
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AnimePTBR,Arial,52,&H00FFFFFF,&H000000FF,&H00000000,&H7F000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [header.rstrip()]
        for cue in cues:
            text = self._escape_ass_text(cue.text)
            lines.append(
                f"Dialogue: 0,{self._format_ass_time(cue.start)},{self._format_ass_time(cue.end)},AnimePTBR,,0,0,0,,{text}"
            )
        return "\n".join(lines).strip() + "\n"

    def _merge_and_clean_cues(self, cues: Sequence[SrtCue]) -> List[SrtCue]:
        clean: List[SrtCue] = []
        for cue in sorted(cues, key=lambda item: (item.start, item.end)):
            text = self._clean_subtitle_text(cue.text)
            if not text or cue.end <= cue.start:
                continue
            clean.append(SrtCue(max(0.0, cue.start), max(cue.start + 0.2, cue.end), text))
        return clean

    def _clean_subtitle_text(self, text: str) -> str:
        value = html.unescape(str(text or ""))
        value = re.sub(r"\{[^{}]*\}", "", value)  # tags ASS
        value = re.sub(r"<[^>]+>", "", value)      # tags HTML
        value = value.replace("\\N", "\n")
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()

    def _parse_srt_time(self, text: str) -> float:
        text = text.strip().replace(",", ".")
        match = re.match(r"(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", text)
        if not match:
            return 0.0
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        ms_text = (match.group(4) or "0").ljust(3, "0")[:3]
        return hours * 3600 + minutes * 60 + seconds + int(ms_text) / 1000.0

    def _format_srt_time(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        total_ms = int(round(seconds * 1000))
        ms = total_ms % 1000
        total_seconds = total_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    def _format_ass_time(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        total_cs = int(round(seconds * 100))
        cs = total_cs % 100
        total_seconds = total_cs // 100
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"

    def _escape_ass_text(self, text: str) -> str:
        value = self._clean_subtitle_text(text)
        value = value.replace("{", "").replace("}", "")
        value = value.replace("\n", r"\N")
        return value

    def _find_existing_ass(self, output_path: Path) -> Path:
        direct = output_path.with_name(f"{output_path.stem}.pt-BR.ass")
        if direct.exists():
            return direct
        alt = output_path.with_suffix(".ass")
        return alt

    def _escape_subtitle_filter_path(self, path: Path) -> str:
        value = str(path.resolve()).replace("\\", "/")
        value = value.replace(":", r"\:")
        value = value.replace("'", r"\'")
        return value

    def _clean_api_key(self, api_key: str, purpose: str = "usar a API") -> str:
        value = str(api_key or "").strip()
        if not value:
            raise SubtitleGenerationError(
                f"API Key do Gemini necessária para {purpose}. Cole a chave no campo API Key da Biblioteca de Clipes."
            )
        return value

    def _clean_model_name(self, model: str) -> str:
        value = str(model or DEFAULT_GEMINI_SUBTITLE_MODEL).strip()
        if value.startswith("models/"):
            value = value.split("/", 1)[1]
        aliases = {
            "gemini-2.5-flash": DEFAULT_GEMINI_SUBTITLE_MODEL,
            "models/gemini-2.5-flash": DEFAULT_GEMINI_SUBTITLE_MODEL,
            "flash": DEFAULT_GEMINI_SUBTITLE_MODEL,
            "gemini-flash": DEFAULT_GEMINI_SUBTITLE_MODEL,
        }
        return aliases.get(value, value or DEFAULT_GEMINI_SUBTITLE_MODEL)

    def _float_or_none(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    def _sanitize_name(self, value: str) -> str:
        text = re.sub(r"[<>:\"/\\|?*]+", "-", str(value or "").strip())
        text = re.sub(r"\s+", " ", text).strip(" .")
        return text or "clipe"

    def _unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        counter = 1
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

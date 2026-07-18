"""Serviço leve para gerar áudio de narração de clipes.

Sprint 4.7.7:
- gera MP3 com edge-tts;
- quando possível, salva também um JSON de sincronização palavra por palavra;
- esse JSON é usado pelo editor para criar legenda dinâmica realmente alinhada ao áudio.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_TTS_VOICE = "pt-BR-AntonioNeural"
DEFAULT_TTS_RATE = "+0%"
DEFAULT_BACKGROUND_VOLUME = 0.25


class NarrationAudioError(RuntimeError):
    """Erro amigável para geração/exportação de áudio de narração."""


class NarrationAudioService:
    """Gera MP3 de narração e exporta vídeo com a narração mixada."""

    def __init__(self, timeout_seconds: int = 180):
        self.timeout_seconds = max(60, int(timeout_seconds or 180))
        self.ffmpeg_binary = os.environ.get("FFMPEG_BINARY", "ffmpeg")
        self.ffprobe_binary = os.environ.get("FFPROBE_BINARY", self._guess_ffprobe_binary(self.ffmpeg_binary))

    def generate_audio(
        self,
        clip: Dict[str, Any],
        script: str,
        voice: str = DEFAULT_TTS_VOICE,
        rate: str = DEFAULT_TTS_RATE,
    ) -> Dict[str, Any]:
        """Gerar MP3 de narração e, quando possível, sync REAL palavra por palavra.

        Regra desta versão: Narração dinâmica não usa mais sync estimado.
        Se o edge-tts não entregar WordBoundary/SRT de palavras, o app mantém o
        áudio, mas marca a dinâmica como indisponível para evitar resultado meia-boca.
        """
        script = self._clean_script(script)
        voice = str(voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
        rate = self._normalize_rate(rate)
        output_path = self._audio_path_for_clip(clip)
        sync_path = self._sync_path_for_audio(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_old_sync_files(output_path, sync_path)

        errors: List[str] = []

        # 1) Caminho mais confiável no Windows/PySide: roda o edge-tts em um
        # processo Python isolado e captura WordBoundary direto do stream.
        try:
            result = self._generate_with_subprocess_word_boundaries(script, output_path, sync_path, voice, rate)
            if result.get("sync_available"):
                return result
            if output_path.exists() and output_path.stat().st_size > 0:
                errors.append(str(result.get("sync_warning") or "subprocess não retornou WordBoundary"))
        except Exception as exc:
            errors.append(f"subprocess WordBoundary: {exc}")
            self._cleanup_empty_audio(output_path)

        # 2) Caminho direto por biblioteca no mesmo processo.
        try:
            result = asyncio.run(self._generate_with_word_boundaries(script, output_path, sync_path, voice, rate))
            if result.get("sync_available"):
                return result
            if output_path.exists() and output_path.stat().st_size > 0:
                errors.append("stream direto gerou áudio, mas sem WordBoundary real")
        except Exception as exc:
            errors.append(f"stream direto: {exc}")
            self._cleanup_empty_audio(output_path)

        # 3) Fallback real: CLI do edge-tts com --write-subtitles. Só aceitamos
        # como dinâmica se o SRT vier com cue de UMA palavra por vez.
        try:
            result = self._generate_with_cli_subtitles(script, output_path, sync_path, voice, rate, direct_error="\n".join(errors))
            if result.get("sync_available"):
                return result
            if output_path.exists() and output_path.stat().st_size > 0:
                return self._mark_audio_without_real_sync(
                    result,
                    sync_path,
                    reason="O edge-tts gerou o MP3, mas não retornou timestamps reais por palavra."
                )
        except Exception as exc:
            errors.append(f"CLI subtitles: {exc}")
            self._cleanup_empty_audio(output_path)

        # 4) Último caso: gera/garante áudio normal, mas SEM fingir sync.
        result = self._generate_with_cli(script, output_path, voice, rate, direct_error="\n".join(errors))
        return self._mark_audio_without_real_sync(
            result,
            sync_path,
            reason="Não foi possível obter WordBoundary/SRT real por palavra do edge-tts."
        )

    def _generate_with_subprocess_word_boundaries(
        self,
        script: str,
        output_path: Path,
        sync_path: Path,
        voice: str,
        rate: str,
    ) -> Dict[str, Any]:
        """Captura WordBoundary em processo isolado.

        Isso evita problemas do asyncio dentro do app Qt e usa a mesma fonte real
        do áudio. O sync gerado aqui é aceito como verdadeiro para Narração dinâmica.
        """
        import tempfile

        helper_code = '''
import asyncio, json, sys
from pathlib import Path

async def main():
    text_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    sync_path = Path(sys.argv[3])
    voice = sys.argv[4]
    rate = sys.argv[5]
    script = text_path.read_text(encoding="utf-8")
    import edge_tts

    words = []
    event_counts = {}
    communicate = edge_tts.Communicate(script, voice=voice, rate=rate)
    with output_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            chunk_type = str(chunk.get("type") or chunk.get("Type") or "").strip()
            event_counts[chunk_type] = event_counts.get(chunk_type, 0) + 1
            low = chunk_type.lower()
            if low == "audio" and chunk.get("data"):
                audio_file.write(chunk["data"])
                continue
            if low == "wordboundary" or low == "word_boundary" or low == "word":
                raw_text = str(chunk.get("text") or chunk.get("Text") or chunk.get("word") or chunk.get("Word") or "").strip()
                if not raw_text:
                    continue
                try:
                    offset = float(chunk.get("offset", chunk.get("Offset", 0)) or 0.0) / 10000000.0
                except Exception:
                    offset = 0.0
                try:
                    duration = float(chunk.get("duration", chunk.get("Duration", 0)) or 0.0) / 10000000.0
                except Exception:
                    duration = 0.0
                if duration <= 0:
                    duration = max(0.04, min(0.30, len(raw_text) * 0.035))
                words.append({
                    "word": raw_text,
                    "start": round(max(0.0, offset), 4),
                    "end": round(max(offset + 0.04, offset + duration), 4),
                    "duration": round(max(0.04, duration), 4),
                })

    if words:
        payload = {
            "engine": "edge-tts",
            "voice": voice,
            "rate": rate,
            "source": "edge-tts WordBoundary subprocess",
            "estimated": False,
            "script": script,
            "event_counts": event_counts,
            "words": words,
        }
        sync_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        debug_path = sync_path.with_suffix(".sync_debug.json")
        debug_path.write_text(json.dumps({"event_counts": event_counts, "word_count": 0}, ensure_ascii=False, indent=2), encoding="utf-8")

asyncio.run(main())
'''
        with tempfile.TemporaryDirectory(prefix="tedvhs_tts_") as temp_dir:
            temp = Path(temp_dir)
            text_path = temp / "script.txt"
            helper_path = temp / "edge_sync_helper.py"
            text_path.write_text(script, encoding="utf-8")
            helper_path.write_text(helper_code, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(helper_path), str(text_path), str(output_path), str(sync_path), voice, rate],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise NarrationAudioError(f"Falha no helper de sync real do edge-tts. Detalhe: {detail[:1200]}")
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise NarrationAudioError("O edge-tts terminou, mas o arquivo de áudio não foi criado.")
        words = self._load_sync_payload_words(sync_path)
        if words:
            payload = json.loads(sync_path.read_text(encoding="utf-8"))
            payload["words"] = self._normalize_word_boundaries(words)
            payload["estimated"] = False
            sync_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "audio_path": str(output_path),
                "sync_path": str(sync_path),
                "sync_available": True,
                "sync_word_count": len(payload["words"]),
                "voice": voice,
                "rate": rate,
                "engine": "edge-tts",
                "sync_source": "edge-tts WordBoundary subprocess",
                "sync_estimated": False,
            }
        return {
            "audio_path": str(output_path),
            "sync_path": "",
            "sync_available": False,
            "sync_word_count": 0,
            "voice": voice,
            "rate": rate,
            "engine": "edge-tts",
            "sync_source": "",
            "sync_estimated": False,
            "sync_warning": "O edge-tts não enviou eventos WordBoundary no subprocesso.",
        }

    async def _generate_with_word_boundaries(
        self,
        script: str,
        output_path: Path,
        sync_path: Path,
        voice: str,
        rate: str,
    ) -> Dict[str, Any]:
        try:
            import edge_tts  # type: ignore
        except Exception as exc:
            raise NarrationAudioError(
                "O pacote edge-tts não está instalado no ambiente virtual.\n\n"
                "No CMD do projeto, rode:\n"
                "pip install edge-tts\n\n"
                "Depois abra o app novamente e tente gerar o áudio."
            ) from exc

        words: List[Dict[str, Any]] = []
        communicate = edge_tts.Communicate(script, voice=voice, rate=rate)
        with output_path.open("wb") as audio_file:
            async for chunk in communicate.stream():
                chunk_type = str(chunk.get("type") or chunk.get("Type") or "").strip().lower()
                if chunk_type == "audio" and chunk.get("data"):
                    audio_file.write(chunk["data"])
                elif (
                    "wordboundary" in chunk_type
                    or "word_boundary" in chunk_type
                    or chunk_type == "word"
                    or (chunk.get("offset") is not None and (chunk.get("text") or chunk.get("Text")))
                ):
                    raw_text = str(
                        chunk.get("text")
                        or chunk.get("Text")
                        or chunk.get("word")
                        or chunk.get("Word")
                        or ""
                    ).strip()
                    if not raw_text:
                        continue
                    start = self._ticks_to_seconds(chunk.get("offset", chunk.get("Offset")))
                    dur = self._ticks_to_seconds(chunk.get("duration", chunk.get("Duration")))
                    if dur <= 0:
                        dur = max(0.08, len(raw_text) * 0.045)
                    words.append({
                        "word": raw_text,
                        "start": round(start, 4),
                        "end": round(start + dur, 4),
                        "duration": round(dur, 4),
                    })

        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise NarrationAudioError("O edge-tts terminou, mas o arquivo de áudio não foi criado.")

        sync_available = bool(words)
        if sync_available:
            sync_payload = {
                "engine": "edge-tts",
                "voice": voice,
                "rate": rate,
                "source": "WordBoundary",
                "script": script,
                "words": self._normalize_word_boundaries(words),
            }
            sync_path.write_text(json.dumps(sync_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            try:
                if sync_path.exists():
                    sync_path.unlink()
            except Exception:
                pass

        return {
            "audio_path": str(output_path),
            "sync_path": str(sync_path) if sync_available else "",
            "sync_available": sync_available,
            "sync_word_count": len(words),
            "voice": voice,
            "rate": rate,
            "engine": "edge-tts",
            "sync_source": "edge-tts WordBoundary" if sync_available else "",
        }

    def _generate_with_cli(
        self,
        script: str,
        output_path: Path,
        voice: str,
        rate: str,
        direct_error: str = "",
    ) -> Dict[str, Any]:
        cmd_module = [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            voice,
            "--rate",
            rate,
            "--text",
            script,
            "--write-media",
            str(output_path),
        ]
        completed = subprocess.run(
            cmd_module,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        detail = (completed.stderr or completed.stdout or "").strip()

        # Algumas versões expõem CLI como edge-tts.exe em vez de python -m edge_tts.
        if completed.returncode != 0 and ("__main__" in detail or "No module named edge_tts" not in detail):
            cmd_cli = [
                "edge-tts",
                "--voice",
                voice,
                "--rate",
                rate,
                "--text",
                script,
                "--write-media",
                str(output_path),
            ]
            try:
                completed = subprocess.run(
                    cmd_cli,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
                detail = (completed.stderr or completed.stdout or "").strip()
            except FileNotFoundError as exc:
                detail = str(exc)
                completed = subprocess.CompletedProcess(cmd_cli, 1, "", detail)

        if completed.returncode != 0:
            combined = f"{detail}\n{direct_error}".strip()
            if "No module named edge_tts" in combined or "edge-tts" in combined or "not recognized" in combined or "não é reconhecido" in combined:
                raise NarrationAudioError(
                    "O pacote edge-tts não está instalado no ambiente virtual.\n\n"
                    "No CMD do projeto, rode:\n"
                    "pip install edge-tts\n\n"
                    "Depois abra o app novamente e tente gerar o áudio."
                )
            raise NarrationAudioError(f"Falha ao gerar narração com edge-tts. Detalhe: {combined[:1200]}")
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise NarrationAudioError("O edge-tts terminou, mas o arquivo de áudio não foi criado.")
        return {
            "audio_path": str(output_path),
            "voice": voice,
            "rate": rate,
            "engine": "edge-tts",
        }


    def _generate_with_cli_subtitles(
        self,
        script: str,
        output_path: Path,
        sync_path: Path,
        voice: str,
        rate: str,
        direct_error: str = "",
    ) -> Dict[str, Any]:
        """Gerar áudio pela CLI e converter SRT palavra-a-palavra em sync real.

        Importante: esta função NÃO transforma frases em palavras por estimativa.
        Só aceita SRT se cada cue tiver uma única palavra com início/fim próprios.
        """
        srt_path = sync_path.with_suffix(".srt")
        for candidate in (output_path, sync_path, srt_path):
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception:
                pass

        cmd_module = [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            voice,
            "--rate",
            rate,
            "--text",
            script,
            "--write-media",
            str(output_path),
            "--write-subtitles",
            str(srt_path),
        ]
        completed = subprocess.run(cmd_module, capture_output=True, text=True, timeout=self.timeout_seconds)
        detail = (completed.stderr or completed.stdout or "").strip()
        if completed.returncode != 0:
            cmd_cli = [
                "edge-tts",
                "--voice",
                voice,
                "--rate",
                rate,
                "--text",
                script,
                "--write-media",
                str(output_path),
                "--write-subtitles",
                str(srt_path),
            ]
            try:
                completed = subprocess.run(cmd_cli, capture_output=True, text=True, timeout=self.timeout_seconds)
                detail = (completed.stderr or completed.stdout or "").strip()
            except FileNotFoundError as exc:
                detail = str(exc)
                completed = subprocess.CompletedProcess(cmd_cli, 1, "", detail)

        if completed.returncode != 0:
            combined = f"{detail}\n{direct_error}".strip()
            raise NarrationAudioError(f"Falha ao gerar narração com SRT do edge-tts. Detalhe: {combined[:1200]}")
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise NarrationAudioError("O edge-tts terminou, mas o arquivo de áudio não foi criado.")

        words = self._words_from_srt_strict(srt_path)
        if words:
            sync_payload = {
                "engine": "edge-tts",
                "voice": voice,
                "rate": rate,
                "source": "edge-tts CLI SRT WordBoundary",
                "estimated": False,
                "script": script,
                "words": self._normalize_word_boundaries(words),
            }
            sync_path.write_text(json.dumps(sync_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "audio_path": str(output_path),
                "sync_path": str(sync_path),
                "sync_available": True,
                "sync_word_count": len(sync_payload["words"]),
                "voice": voice,
                "rate": rate,
                "engine": "edge-tts",
                "sync_source": "edge-tts CLI SRT WordBoundary",
                "sync_estimated": False,
            }

        return {
            "audio_path": str(output_path),
            "sync_path": "",
            "sync_available": False,
            "sync_word_count": 0,
            "voice": voice,
            "rate": rate,
            "engine": "edge-tts",
            "sync_source": "",
            "sync_estimated": False,
            "sync_warning": "O SRT do edge-tts não veio com uma palavra por cue.",
        }

    def _words_from_srt_strict(self, srt_path: Path) -> List[Dict[str, Any]]:
        """Ler SRT gerado pelo edge-tts aceitando apenas sync real por palavra."""
        if not srt_path.exists() or srt_path.stat().st_size <= 0:
            return []
        raw = srt_path.read_text(encoding="utf-8", errors="replace")
        lines = [line.strip("\ufeff ") for line in raw.splitlines()]
        words: List[Dict[str, Any]] = []
        seen = set()
        i = 0
        rejected_phrase_cues = 0
        while i < len(lines):
            line = lines[i].strip()
            if "-->" not in line:
                i += 1
                continue
            left, right = line.split("-->", 1)
            start = self._vtt_time_to_seconds(left.strip())
            end = self._vtt_time_to_seconds(right.strip().split()[0])
            i += 1
            text_parts: List[str] = []
            while i < len(lines) and lines[i].strip():
                text_parts.append(lines[i].strip())
                i += 1
            text = self._clean_vtt_text(" ".join(text_parts))
            tokens = [p for p in re.split(r"\s+", text) if p]
            if len(tokens) == 1 and end > start:
                token = tokens[0]
                key = (round(start, 3), round(end, 3), token.lower())
                if key not in seen:
                    seen.add(key)
                    words.append({
                        "word": token,
                        "start": round(start, 4),
                        "end": round(max(start + 0.04, end), 4),
                        "duration": round(max(0.04, end - start), 4),
                    })
            elif len(tokens) > 1:
                rejected_phrase_cues += 1
            i += 1
        # Se vieram poucas palavras ou muitas frases, provavelmente é sentence-level.
        if len(words) < 3 or rejected_phrase_cues > len(words):
            return []
        words.sort(key=lambda item: float(item.get("start") or 0.0))
        return words

    def _words_from_vtt(self, vtt_path: Path) -> List[Dict[str, Any]]:
        if not vtt_path.exists() or vtt_path.stat().st_size <= 0:
            return []
        raw = vtt_path.read_text(encoding="utf-8", errors="replace")
        lines = [line.strip("\ufeff ") for line in raw.splitlines()]
        words: List[Dict[str, Any]] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if "-->" not in line:
                i += 1
                continue
            left, right = line.split("-->", 1)
            start = self._vtt_time_to_seconds(left.strip())
            end = self._vtt_time_to_seconds(right.strip().split()[0])
            i += 1
            text_parts: List[str] = []
            while i < len(lines) and lines[i].strip():
                text_parts.append(lines[i].strip())
                i += 1
            text = self._clean_vtt_text(" ".join(text_parts))
            parts = [p for p in re.split(r"\s+", text) if p]
            if parts and end > start:
                total_weight = max(1, sum(max(1, len(re.sub(r"\W+", "", p))) for p in parts))
                cursor = start
                for index, word in enumerate(parts):
                    weight = max(1, len(re.sub(r"\W+", "", word)))
                    if index == len(parts) - 1:
                        word_end = end
                    else:
                        word_end = cursor + (end - start) * (weight / total_weight)
                    words.append({
                        "word": word,
                        "start": round(cursor, 4),
                        "end": round(max(cursor + 0.04, word_end), 4),
                        "duration": round(max(0.04, word_end - cursor), 4),
                    })
                    cursor = word_end
            i += 1
        return words

    @staticmethod
    def _clean_vtt_text(text: str) -> str:
        value = str(text or "")
        value = re.sub(r"<[^>]+>", "", value)
        value = value.replace("&nbsp;", " ").replace("&amp;", "&")
        value = value.replace("&lt;", "<").replace("&gt;", ">")
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _vtt_time_to_seconds(value: str) -> float:
        clean = str(value or "").strip().replace(",", ".")
        try:
            parts = clean.split(":")
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            if len(parts) == 2:
                minutes, seconds = parts
                return int(minutes) * 60 + float(seconds)
            return float(clean)
        except Exception:
            return 0.0

    def export_video_with_narration(
        self,
        clip: Dict[str, Any],
        audio_path: Optional[str] = None,
        background_volume: float = DEFAULT_BACKGROUND_VOLUME,
    ) -> Dict[str, Any]:
        """Gerar uma cópia MP4 com a narração por cima do áudio original."""
        input_video = Path(str(clip.get("output_path") or ""))
        if not input_video.exists():
            raise NarrationAudioError(f"Arquivo do clipe não encontrado: {input_video}")
        narration_audio = Path(str(audio_path or self._saved_audio_path(clip) or self._audio_path_for_clip(clip)))
        if not narration_audio.exists():
            raise NarrationAudioError("Gere o áudio da narração antes de exportar o vídeo com narração.")
        output_path = input_video.with_name(f"{input_video.stem} com narração.mp4")
        background_volume = max(0.0, min(float(background_volume or DEFAULT_BACKGROUND_VOLUME), 1.0))

        cmd = [
            self.ffmpeg_binary,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_video),
            "-i",
            str(narration_audio),
            "-filter_complex",
            f"[0:a]volume={background_volume:.2f}[base];[1:a]volume=1.0[nar];[base][nar]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(60, self.timeout_seconds),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise NarrationAudioError(f"Falha ao exportar vídeo com narração. Detalhe: {detail[:1200]}")
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise NarrationAudioError("O FFmpeg terminou, mas o MP4 com narração não foi criado.")
        return {
            "narrated_video_path": str(output_path),
            "audio_path": str(narration_audio),
            "background_volume": background_volume,
            "engine": "ffmpeg_mix",
        }

    def _clean_script(self, script: str) -> str:
        text = str(script or "").strip()
        if not text:
            raise NarrationAudioError("Gere ou cole um roteiro de narração antes de criar o áudio.")
        text = re.sub(r"\s+", " ", text)
        text = text.replace("#", "")
        return text.strip()

    def _audio_path_for_clip(self, clip: Dict[str, Any]) -> Path:
        output_path = Path(str(clip.get("output_path") or ""))
        if not output_path.name:
            raise NarrationAudioError("Não foi possível localizar o arquivo do clipe selecionado.")
        return output_path.with_name(f"{output_path.stem} narração.mp3")

    def _mark_audio_without_real_sync(self, result: Dict[str, Any], sync_path: Path, reason: str) -> Dict[str, Any]:
        """Marcar áudio como gerado, mas sem sync real. Não cria sync estimado."""
        for candidate in (sync_path, sync_path.with_suffix(".srt"), sync_path.with_suffix(".vtt")):
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception:
                pass
        result.update({
            "sync_path": "",
            "sync_available": False,
            "sync_word_count": 0,
            "sync_source": "",
            "sync_estimated": False,
            "sync_warning": reason + " A Narração dinâmica ficará bloqueada para evitar legenda fora de sincronia.",
        })
        return result

    def _remove_old_sync_files(self, output_path: Path, sync_path: Path) -> None:
        """Remover sync antigo para não reutilizar arquivo estimado/desatualizado."""
        for candidate in (sync_path, sync_path.with_suffix(".srt"), sync_path.with_suffix(".vtt"), sync_path.with_suffix(".sync_debug.json")):
            try:
                if candidate.exists():
                    candidate.unlink()
            except Exception:
                pass
        try:
            if output_path.exists() and output_path.stat().st_size <= 0:
                output_path.unlink()
        except Exception:
            pass

    def _cleanup_empty_audio(self, output_path: Path) -> None:
        try:
            if output_path.exists() and output_path.stat().st_size <= 0:
                output_path.unlink()
        except Exception:
            pass

    def _load_sync_payload_words(self, sync_path: Path) -> List[Dict[str, Any]]:
        if not sync_path.exists():
            return []
        try:
            data = json.loads(sync_path.read_text(encoding="utf-8"))
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
            word = str(item.get("word") or item.get("text") or "").strip()
            if not word:
                continue
            try:
                start = max(0.0, float(item.get("start") or 0.0))
                end = max(start + 0.04, float(item.get("end") or start + float(item.get("duration") or 0.12)))
            except Exception:
                continue
            words.append({"word": word, "start": start, "end": end, "duration": max(0.04, end - start)})
        words.sort(key=lambda value: float(value.get("start") or 0.0))
        return words

    def _attach_estimated_sync(
        self,
        result: Dict[str, Any],
        script: str,
        audio_path: Path,
        sync_path: Path,
        voice: str,
        rate: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Criar um .sync.json de emergência pela duração real do áudio.

        O ideal é WordBoundary real do edge-tts. Porém algumas instalações do
        pacote/CLI geram apenas o MP3. Nesse caso, este fallback evita o estado
        "sem sync" e usa a duração do MP3 para distribuir as palavras com pausas
        em pontuação. Não é tão preciso quanto WordBoundary, mas fica muito mais
        estável do que dividir pelo tempo do vídeo ou deixar a dinâmica quebrada.
        """
        words = self._estimated_words_from_script_and_audio(script, audio_path)
        if not words:
            result.update({
                "sync_path": "",
                "sync_available": False,
                "sync_word_count": 0,
                "sync_source": "",
                "sync_estimated": False,
                "sync_warning": (
                    "A narração foi gerada, mas não foi possível criar dados de sincronização. "
                    "Use legenda estável por frases ou tente gerar o áudio novamente."
                ),
            })
            return result
        sync_payload = {
            "engine": "edge-tts",
            "voice": voice,
            "rate": rate,
            "source": "estimated_audio_duration",
            "estimated": True,
            "reason": reason,
            "script": script,
            "words": self._normalize_word_boundaries(words),
        }
        sync_path.write_text(json.dumps(sync_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        result.update({
            "sync_path": str(sync_path),
            "sync_available": True,
            "sync_word_count": len(sync_payload["words"]),
            "sync_source": "estimado pela duração real do áudio",
            "sync_estimated": True,
            "sync_warning": (
                "Sync criado por estimativa usando a duração real do MP3. "
                "Se quiser tentar o sync perfeito, gere o áudio novamente ou atualize o edge-tts."
            ),
        })
        return result

    def _estimated_words_from_script_and_audio(self, script: str, audio_path: Path) -> List[Dict[str, Any]]:
        duration = self._probe_media_duration_seconds(audio_path)
        tokens = [token for token in re.findall(r"\S+", str(script or "")) if token.strip()]
        if not tokens:
            return []
        if duration <= 0:
            duration = max(1.0, sum(max(1, len(re.sub(r"\W+", "", t))) * 0.055 for t in tokens))
        start_offset = min(0.18, duration * 0.02)
        usable = max(0.5, duration - start_offset - 0.08)
        weighted: List[tuple[str, float, float]] = []
        total_weight = 0.0
        for token in tokens:
            clean = token.strip()
            letters = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", "", clean)
            if not letters:
                continue
            word_weight = max(1.0, len(letters) * 0.75)
            pause_weight = 0.0
            if clean.endswith((".", "!", "?", "…")):
                pause_weight = 3.8
            elif clean.endswith((",", ";", ":")):
                pause_weight = 1.8
            weighted.append((clean, word_weight, pause_weight))
            total_weight += word_weight + pause_weight
        if not weighted or total_weight <= 0:
            return []
        cursor = start_offset
        words: List[Dict[str, Any]] = []
        for index, (word, word_weight, pause_weight) in enumerate(weighted):
            word_duration = max(0.055, usable * (word_weight / total_weight))
            end = min(duration, cursor + word_duration)
            if end <= cursor:
                end = min(duration, cursor + 0.06)
            words.append({
                "word": word,
                "start": round(cursor, 4),
                "end": round(end, 4),
                "duration": round(max(0.04, end - cursor), 4),
            })
            cursor = end
            if pause_weight > 0 and index < len(weighted) - 1:
                cursor = min(duration, cursor + usable * (pause_weight / total_weight))
            if cursor >= duration:
                break
        return words

    def _probe_media_duration_seconds(self, media_path: Path) -> float:
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

    @staticmethod
    def _guess_ffprobe_binary(ffmpeg_binary: str) -> str:
        value = str(ffmpeg_binary or "ffmpeg")
        base = os.path.basename(value).lower()
        if base.startswith("ffmpeg"):
            suffix = ".exe" if base.endswith(".exe") else ""
            directory = os.path.dirname(value)
            return os.path.join(directory, f"ffprobe{suffix}") if directory else f"ffprobe{suffix}"
        return "ffprobe"

    def _sync_path_for_audio(self, audio_path: Path) -> Path:
        return Path(audio_path).with_suffix(".sync.json")

    def _saved_audio_path(self, clip: Dict[str, Any]) -> str:
        for key in ("narration_audio_path", "audio_narration_path"):
            if clip.get(key):
                return str(clip.get(key))
        metadata = clip.get("metadata_json") if isinstance(clip.get("metadata_json"), dict) else {}
        for key in ("narration_audio_path", "audio_narration_path"):
            if metadata.get(key):
                return str(metadata.get(key))
        metadata_path = Path(str(clip.get("metadata_path") or ""))
        if metadata_path.exists():
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    for key in ("narration_audio_path", "audio_narration_path"):
                        if payload.get(key):
                            return str(payload.get(key))
            except Exception:
                return ""
        return ""

    def _normalize_rate(self, rate: str) -> str:
        value = str(rate or DEFAULT_TTS_RATE).strip()
        aliases = {
            "Normal": "+0%",
            "Mais lenta": "-10%",
            "Lenta": "-10%",
            "Mais rápida": "+10%",
            "Rapida": "+10%",
            "Rápida": "+10%",
        }
        value = aliases.get(value, value)
        if re.fullmatch(r"[+-]?\d+%", value):
            if not value.startswith(('+', '-')):
                value = "+" + value
            return value
        return DEFAULT_TTS_RATE

    @staticmethod
    def _ticks_to_seconds(value: Any) -> float:
        try:
            return max(0.0, float(value or 0.0) / 10_000_000.0)
        except Exception:
            return 0.0

    def _normalize_word_boundaries(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        last_end = 0.0
        for item in words:
            word = str(item.get("word") or "").strip()
            if not word:
                continue
            start = max(0.0, float(item.get("start") or 0.0))
            end = max(start + 0.04, float(item.get("end") or start + 0.12))
            # Garante monotonicidade sem destruir pausas naturais.
            if start < last_end - 0.05:
                shift = (last_end - 0.03) - start
                start += shift
                end += shift
            cleaned.append({
                "word": word,
                "start": round(start, 4),
                "end": round(end, 4),
                "duration": round(max(0.04, end - start), 4),
            })
            last_end = max(last_end, end)
        return cleaned

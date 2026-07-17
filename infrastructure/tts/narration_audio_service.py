"""Serviço leve para gerar áudio de narração de clipes.

A primeira implementação usa edge-tts por subprocesso. É online, gratuito para uso pessoal,
leve para o PC e não exige carregar modelo local pesado. O app só envia texto do roteiro.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

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

    def generate_audio(
        self,
        clip: Dict[str, Any],
        script: str,
        voice: str = DEFAULT_TTS_VOICE,
        rate: str = DEFAULT_TTS_RATE,
    ) -> Dict[str, Any]:
        """Gerar arquivo MP3 de narração a partir do roteiro."""
        script = self._clean_script(script)
        voice = str(voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
        rate = self._normalize_rate(rate)
        output_path = self._audio_path_for_clip(clip)
        output_path.parent.mkdir(parents=True, exist_ok=True)

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

        # Algumas versões do pacote expõem CLI como edge-tts.exe em vez de python -m edge_tts.
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
            if "No module named edge_tts" in detail or "edge-tts" in detail or "not recognized" in detail or "não é reconhecido" in detail:
                raise NarrationAudioError(
                    "O pacote edge-tts não está instalado no ambiente virtual.\n\n"
                    "No CMD do projeto, rode:\n"
                    "pip install edge-tts\n\n"
                    "Depois abra o app novamente e tente gerar o áudio."
                )
            raise NarrationAudioError(f"Falha ao gerar narração com edge-tts. Detalhe: {detail[:1200]}")
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise NarrationAudioError("O edge-tts terminou, mas o arquivo de áudio não foi criado.")
        return {
            "audio_path": str(output_path),
            "voice": voice,
            "rate": rate,
            "engine": "edge-tts",
        }

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

        # Mistura áudio original reduzido + narração. Mantém o vídeo copiado sem reencodar.
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
        # Remove marcações muito comuns que atrapalham leitura em voz alta.
        text = re.sub(r"\s+", " ", text)
        text = text.replace("#", "")
        return text.strip()

    def _audio_path_for_clip(self, clip: Dict[str, Any]) -> Path:
        output_path = Path(str(clip.get("output_path") or ""))
        if not output_path.name:
            raise NarrationAudioError("Não foi possível localizar o arquivo do clipe selecionado.")
        return output_path.with_name(f"{output_path.stem} narração.mp3")

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

"""Detecção, miniaturas e catalogação inicial de cenas usando FFmpeg.

Esta etapa ainda não cria clipes finais em .mp4. Ela detecta intervalos de
cena, gera miniaturas/frames de apoio e cria uma descrição automática inicial
baseada em análise visual local. A integração com IA multimodal real fica
preparada para uma próxima sprint.
"""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from infrastructure.config.configuration_service import ConfigurationService


logger = logging.getLogger(__name__)


class SceneDetector:
    """Detecta cenas e gera ativos visuais de preview/catálogo."""

    def __init__(self, config: ConfigurationService):
        self._config = config
        self._ffmpeg_path = config.get("ffmpeg.ffmpeg_path", "ffmpeg")
        self._timeout_seconds = int(config.get("processing.timeout_seconds", 300) or 300)
        logger.info("SceneDetector inicializado com FFmpeg: %s", self._ffmpeg_path)

    def detect_scenes(
        self,
        file_path: str,
        duration_seconds: float,
        threshold: float = 0.35,
        min_scene_seconds: float = 2.0,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, float]]:
        """Detectar cenas de um vídeo.

        Args:
            file_path: caminho do vídeo original.
            duration_seconds: duração total do vídeo em segundos.
            threshold: sensibilidade do corte. Menor = mais cenas.
            min_scene_seconds: cenas menores que isso são mescladas.
            progress_callback: callback textual opcional.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

        duration = max(float(duration_seconds or 0.0), 0.0)
        if duration <= 0:
            raise ValueError("Duração do vídeo inválida ou não encontrada.")

        threshold = max(0.05, min(float(threshold), 0.95))
        min_scene_seconds = max(0.0, float(min_scene_seconds or 0.0))

        if progress_callback:
            progress_callback("Analisando mudanças de cena com FFmpeg...")

        command = [
            self._ffmpeg_path,
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            f"select=gt(scene\\,{threshold}),showinfo",
            "-f",
            "null",
            "-",
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(self._timeout_seconds, 600),
            )
        except FileNotFoundError as exc:
            raise RuntimeError("FFmpeg não encontrado. Instale o FFmpeg ou configure o caminho.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Tempo limite excedido durante a detecção de cenas.") from exc

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou na detecção de cenas: {result.stderr[-1000:]}")

        cut_points = self._parse_cut_points(result.stderr, duration)
        scenes = self._build_scenes(cut_points, duration, min_scene_seconds)

        if progress_callback:
            progress_callback(f"{len(scenes)} cena(s) detectada(s).")

        return scenes

    def enrich_scenes_with_visual_catalog(
        self,
        file_path: str,
        media_id: object,
        scenes: List[Dict[str, float]],
        output_root: str | Path = "data/scene_assets",
        frames_per_scene: int = 5,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, object]]:
        """Gerar miniaturas, frames de análise e descrição automática inicial.

        A descrição desta sprint é uma catalogação visual local, sem IA externa.
        Ela usa frames distribuídos pela cena para estimar iluminação, movimento
        e tipo provável. O usuário pode editar depois na interface.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

        base_dir = Path(output_root) / f"media_{self._safe_name(str(media_id))}"
        base_dir.mkdir(parents=True, exist_ok=True)

        enriched: List[Dict[str, object]] = []
        total = len(scenes)
        for index, scene in enumerate(scenes, start=1):
            scene_number = int(scene.get("scene_number") or index)
            start = float(scene.get("start_seconds") or 0.0)
            end = float(scene.get("end_seconds") or start)
            duration = max(end - start, 0.0)
            midpoint = start + (duration / 2.0)

            if progress_callback:
                progress_callback(f"Gerando miniatura e descrição inicial da cena {scene_number}/{total}...")

            scene_dir = base_dir / f"scene_{scene_number:03d}"
            scene_dir.mkdir(parents=True, exist_ok=True)

            thumbnail_path = scene_dir / "thumbnail.jpg"
            self.extract_thumbnail(str(path), midpoint, thumbnail_path)

            sample_times = self._sample_times(start, end, frames_per_scene)
            analysis = self._analyze_sampled_frames(str(path), sample_times)
            catalog = self._build_auto_catalog(scene_number, start, end, duration, analysis)

            item = dict(scene)
            item.update(
                {
                    "thumbnail_path": str(thumbnail_path),
                    "analysis_frames_json": json.dumps(analysis, ensure_ascii=False),
                    "description": catalog["description"],
                    "tags": ", ".join(catalog["tags"]),
                    "scene_type": catalog["scene_type"],
                    "ai_status": "auto_local",
                    "is_favorite": 0,
                }
            )
            enriched.append(item)

        return enriched

    def extract_thumbnail(self, file_path: str, timestamp_seconds: float, output_path: str | Path) -> Optional[str]:
        """Extrair uma imagem parada do vídeo."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        timestamp = max(float(timestamp_seconds or 0.0), 0.0)

        command = [
            self._ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(file_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:-1",
            str(output),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.warning("Falha ao gerar miniatura: %s", result.stderr[-500:])
                return None
            return str(output)
        except Exception as exc:
            logger.warning("Erro ao gerar miniatura: %s", exc)
            return None

    def _parse_cut_points(self, stderr: str, duration_seconds: float) -> List[float]:
        """Extrair pts_time do log do showinfo."""
        points = []
        for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr or ""):
            value = float(match.group(1))
            if 0.25 < value < duration_seconds - 0.25:
                points.append(value)

        unique = []
        for point in sorted(points):
            if not unique or abs(point - unique[-1]) >= 0.5:
                unique.append(point)
        return unique

    def _build_scenes(
        self,
        cut_points: List[float],
        duration_seconds: float,
        min_scene_seconds: float,
    ) -> List[Dict[str, float]]:
        """Converter pontos de corte em intervalos de cena."""
        boundaries = [0.0] + sorted(cut_points) + [duration_seconds]
        scenes = []

        for index in range(len(boundaries) - 1):
            start = boundaries[index]
            end = boundaries[index + 1]
            if end <= start:
                continue

            if scenes and (end - start) < min_scene_seconds:
                scenes[-1]["end_seconds"] = end
                scenes[-1]["duration_seconds"] = scenes[-1]["end_seconds"] - scenes[-1]["start_seconds"]
                continue

            scenes.append({
                "scene_number": len(scenes) + 1,
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": end - start,
            })

        if not scenes:
            scenes.append({
                "scene_number": 1,
                "start_seconds": 0.0,
                "end_seconds": duration_seconds,
                "duration_seconds": duration_seconds,
            })

        for number, scene in enumerate(scenes, start=1):
            scene["scene_number"] = number
            scene["start_seconds"] = round(float(scene["start_seconds"]), 3)
            scene["end_seconds"] = round(float(scene["end_seconds"]), 3)
            scene["duration_seconds"] = round(float(scene["duration_seconds"]), 3)
        return scenes

    def _sample_times(self, start: float, end: float, count: int) -> List[float]:
        """Distribuir timestamps dentro da cena, evitando exatamente as bordas."""
        duration = max(end - start, 0.0)
        count = max(1, min(int(count or 1), 8))
        if duration <= 0.2:
            return [max(start, 0.0)]
        if count == 1:
            return [start + duration / 2.0]
        margin = min(0.25, duration / 5.0)
        usable_start = start + margin
        usable_end = end - margin
        if usable_end <= usable_start:
            return [start + duration / 2.0]
        step = (usable_end - usable_start) / (count - 1)
        return [round(usable_start + i * step, 3) for i in range(count)]

    def _analyze_sampled_frames(self, file_path: str, sample_times: Sequence[float]) -> Dict[str, object]:
        """Analisar frames pequenos via FFmpeg rawvideo, sem depender de OpenCV/Pillow."""
        frames = []
        previous_pixels: Optional[bytes] = None
        diffs = []

        for timestamp in sample_times:
            raw = self._extract_raw_rgb_frame(file_path, timestamp, width=32, height=18)
            if not raw:
                continue
            stats = self._frame_stats(raw)
            stats["timestamp"] = float(timestamp)
            frames.append(stats)

            if previous_pixels is not None:
                diffs.append(self._mean_abs_diff(previous_pixels, raw))
            previous_pixels = raw

        brightness_values = [float(frame["brightness"]) for frame in frames]
        avg_brightness = sum(brightness_values) / len(brightness_values) if brightness_values else 0.0
        avg_motion = sum(diffs) / len(diffs) if diffs else 0.0

        avg_r = sum(float(frame["avg_r"]) for frame in frames) / len(frames) if frames else 0.0
        avg_g = sum(float(frame["avg_g"]) for frame in frames) / len(frames) if frames else 0.0
        avg_b = sum(float(frame["avg_b"]) for frame in frames) / len(frames) if frames else 0.0

        return {
            "method": "local_frame_sampling",
            "frames_sampled": len(frames),
            "sample_times": list(sample_times),
            "avg_brightness": round(avg_brightness, 2),
            "avg_motion": round(avg_motion, 2),
            "avg_rgb": [round(avg_r, 2), round(avg_g, 2), round(avg_b, 2)],
            "frames": frames,
        }

    def _extract_raw_rgb_frame(self, file_path: str, timestamp: float, width: int, height: int) -> Optional[bytes]:
        command = [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(float(timestamp), 0.0):.3f}",
            "-i",
            str(file_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:{height}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=45)
            expected = width * height * 3
            if result.returncode != 0 or len(result.stdout) < expected:
                return None
            return result.stdout[:expected]
        except Exception:
            return None

    def _frame_stats(self, raw: bytes) -> Dict[str, float]:
        pixels = len(raw) // 3
        if pixels <= 0:
            return {"brightness": 0.0, "avg_r": 0.0, "avg_g": 0.0, "avg_b": 0.0}
        total_r = total_g = total_b = 0
        for i in range(0, len(raw), 3):
            total_r += raw[i]
            total_g += raw[i + 1]
            total_b += raw[i + 2]
        avg_r = total_r / pixels
        avg_g = total_g / pixels
        avg_b = total_b / pixels
        brightness = (0.2126 * avg_r) + (0.7152 * avg_g) + (0.0722 * avg_b)
        return {
            "brightness": round(brightness, 2),
            "avg_r": round(avg_r, 2),
            "avg_g": round(avg_g, 2),
            "avg_b": round(avg_b, 2),
        }

    def _mean_abs_diff(self, previous: bytes, current: bytes) -> float:
        if not previous or not current:
            return 0.0
        length = min(len(previous), len(current))
        if length == 0:
            return 0.0
        return sum(abs(previous[i] - current[i]) for i in range(length)) / length

    def _build_auto_catalog(self, scene_number: int, start: float, end: float, duration: float, analysis: Dict[str, object]) -> Dict[str, object]:
        brightness = float(analysis.get("avg_brightness") or 0.0)
        motion = float(analysis.get("avg_motion") or 0.0)
        avg_rgb = analysis.get("avg_rgb") or [0.0, 0.0, 0.0]
        r, g, b = [float(value or 0.0) for value in avg_rgb[:3]]

        if duration < 5:
            duration_label = "curta"
        elif duration < 25:
            duration_label = "média"
        else:
            duration_label = "longa"

        if brightness < 65:
            light_label = "escura"
            light_tag = "cena escura"
        elif brightness > 175:
            light_label = "clara"
            light_tag = "cena clara"
        else:
            light_label = "com iluminação equilibrada"
            light_tag = "iluminação equilibrada"

        if motion > 38:
            motion_label = "movimento visual alto"
            motion_tag = "movimento alto"
        elif motion > 18:
            motion_label = "movimento visual moderado"
            motion_tag = "movimento moderado"
        else:
            motion_label = "movimento visual baixo"
            motion_tag = "movimento baixo"

        if b > r + 12 and b > g + 8:
            color_label = "tons azulados/frios"
            color_tag = "tons frios"
        elif r > b + 12 and r > g + 4:
            color_label = "tons quentes"
            color_tag = "tons quentes"
        elif g > r + 12 and g > b + 12:
            color_label = "tons esverdeados"
            color_tag = "tons esverdeados"
        else:
            color_label = "cores neutras"
            color_tag = "cores neutras"

        if motion > 38:
            scene_type = "Ação/Movimento"
        elif duration >= 25 and motion <= 18:
            scene_type = "Diálogo/Construção"
        elif brightness < 65:
            scene_type = "Drama/Suspense"
        elif duration < 5:
            scene_type = "Transição"
        else:
            scene_type = "Geral"

        tags = [duration_label, light_tag, motion_tag, color_tag, scene_type.lower()]
        # remove duplicados preservando ordem
        tags = list(dict.fromkeys(tags))

        description = (
            f"Cena {scene_number:03d} {duration_label}, com {light_label}, {color_label} "
            f"e {motion_label}. Descrição automática inicial gerada pela análise visual dos frames; "
            "revise manualmente se a ação/personagens não estiverem bem representados."
        )

        return {
            "description": description,
            "tags": tags,
            "scene_type": scene_type,
        }

    def _safe_name(self, value: str) -> str:
        value = str(value or "unknown")
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
        return safe or "unknown"

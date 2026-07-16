"""Serviço de descrição de cenas usando Gemini API em modo seguro.

Objetivo desta sprint:
- tirar a IA visual pesada do PC do usuário;
- enviar apenas 1 frame comprimido por cena;
- usar API online gratuita quando houver chave configurada;
- manter cache/controle no app e evitar processar dezenas de cenas sem aviso.

A implementação usa apenas a biblioteca padrão do Python para não adicionar
novas dependências ao projeto neste momento.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Sequence

logger = logging.getLogger(__name__)


DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
FALLBACK_GEMINI_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]


class GeminiSceneAIError(RuntimeError):
    """Erro amigável da integração com Gemini."""


class GeminiSceneAIService:
    """Cliente mínimo para Gemini API focado em descrição visual de cenas."""

    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = max(30, int(timeout_seconds or 120))
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def test_connection(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> Dict[str, Any]:
        """Testar chave/modelo com uma chamada pequena de texto."""
        api_key = self._clean_api_key(api_key)
        model = self._clean_model_name(model)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "Responda apenas com a palavra: funcionando"}
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 20,
            },
        }
        data = self._generate_content(api_key=api_key, model=model, payload=payload, timeout_seconds=45)
        text = self._extract_response_text(data).strip()
        if not text:
            raise GeminiSceneAIError("A API respondeu, mas não retornou texto no teste.")
        return {"model": model, "response": text}

    def describe_scene(
        self,
        frame_paths: Sequence[str | Path],
        context: Dict[str, Any],
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
    ) -> Dict[str, Any]:
        """Gerar descrição/tags/tipo usando 1 frame representativo da cena."""
        api_key = self._clean_api_key(api_key)
        model = self._clean_model_name(model)
        frames = [Path(path) for path in frame_paths if path and Path(path).exists() and Path(path).stat().st_size > 0]
        if not frames:
            raise GeminiSceneAIError("Nenhum frame válido foi gerado para enviar à API.")

        selected_frame = self._select_representative_frame(frames)
        prompt = self._build_prompt(context)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": self._guess_mime_type(selected_frame),
                                "data": self._encode_image(selected_frame),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.9,
                "maxOutputTokens": 700,
            },
        }

        data = self._generate_content(api_key=api_key, model=model, payload=payload, timeout_seconds=self.timeout_seconds)
        raw_response = self._extract_response_text(data).strip()
        if not raw_response:
            raise GeminiSceneAIError("A API retornou uma resposta vazia.")

        parsed = self._parse_ai_json(raw_response)
        parsed["modelo"] = model
        parsed["resposta_bruta"] = raw_response
        parsed["frames_usados"] = [str(selected_frame)]
        return parsed

    def describe_clip(
        self,
        frame_paths: Sequence[str | Path],
        context: Dict[str, Any],
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
    ) -> Dict[str, Any]:
        """Gerar descrição/tags/tipo usando frames de um clipe exportado.

        Diferente da cena isolada, o clipe pode juntar vários trechos. Por isso,
        o prompt pede uma descrição geral do clipe final e usa até 3 frames
        comprimidos. Continua leve para o PC: o processamento pesado fica na API.
        """
        api_key = self._clean_api_key(api_key)
        model = self._clean_model_name(model)
        frames = [Path(path) for path in frame_paths if path and Path(path).exists() and Path(path).stat().st_size > 0]
        if not frames:
            raise GeminiSceneAIError("Nenhum frame válido foi gerado para enviar à API.")

        selected_frames = self._select_clip_frames(frames, limit=3)
        prompt = self._build_clip_prompt(context)
        parts: List[Dict[str, Any]] = [{"text": prompt}]
        for frame in selected_frames:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": self._guess_mime_type(frame),
                        "data": self._encode_image(frame),
                    }
                }
            )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": {
                "temperature": 0.25,
                "topP": 0.9,
                "maxOutputTokens": 900,
            },
        }

        data = self._generate_content(api_key=api_key, model=model, payload=payload, timeout_seconds=self.timeout_seconds)
        raw_response = self._extract_response_text(data).strip()
        if not raw_response:
            raise GeminiSceneAIError("A API retornou uma resposta vazia.")

        parsed = self._parse_ai_json(raw_response)
        parsed["modelo"] = model
        parsed["resposta_bruta"] = raw_response
        parsed["frames_usados"] = [str(frame) for frame in selected_frames]
        return parsed

    def format_description(self, result: Dict[str, Any]) -> str:
        """Formatar resultado para o campo descrição da cena."""
        curta = str(result.get("descricao_curta") or "").strip()
        detalhada = str(result.get("descricao_detalhada") or "").strip()
        potencial = str(result.get("potencial_video") or "").strip()
        uso = str(result.get("sugestao_uso") or "").strip()
        motivo = str(result.get("motivo_potencial") or "").strip()

        parts: List[str] = []
        if curta:
            parts.append(curta)
        if detalhada and detalhada.lower() != curta.lower():
            parts.append(f"Detalhes: {detalhada}")
        if potencial:
            linha = f"Potencial para vídeo curto: {potencial}"
            if motivo:
                linha += f" — {motivo}"
            parts.append(linha)
        if uso:
            parts.append(f"Sugestão de uso: {uso}")
        return "\n\n".join(parts).strip() or str(result.get("resposta_bruta") or "").strip()

    def normalize_tags(self, result: Dict[str, Any]) -> str:
        tags = result.get("tags") or []
        if isinstance(tags, str):
            raw_items = re.split(r"[,;\n]+", tags)
        else:
            raw_items = [str(item) for item in tags]
        clean: List[str] = []
        for item in raw_items:
            value = str(item or "").strip().lower()
            value = re.sub(r"\s+", " ", value)
            if value and value not in clean:
                clean.append(value)
        return ", ".join(clean[:12])

    def normalize_scene_type(self, result: Dict[str, Any]) -> str:
        value = str(result.get("tipo") or result.get("scene_type") or "Geral").strip()
        return value or "Geral"

    def _generate_content(
        self,
        api_key: str,
        model: str,
        payload: Dict[str, Any],
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        safe_model = urllib.parse.quote(model, safe="-_.~")
        url = f"{self.base_url}/models/{safe_model}:generateContent?key={urllib.parse.quote(api_key)}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(15, int(timeout_seconds or self.timeout_seconds))) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = self._read_http_error_body(exc)
            raise GeminiSceneAIError(self._friendly_http_error(exc, detail)) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise GeminiSceneAIError(
                "Não foi possível conectar à Gemini API. Verifique internet, API Key e tente novamente. "
                f"Detalhe: {exc}"
            ) from exc
        except Exception as exc:
            raise GeminiSceneAIError(f"Erro inesperado ao chamar Gemini API: {exc}") from exc

        try:
            data = json.loads(raw)
        except Exception as exc:
            raise GeminiSceneAIError(f"A API respondeu, mas o retorno não era JSON válido: {raw[:500]}") from exc
        if isinstance(data, dict) and data.get("error"):
            error = data.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise GeminiSceneAIError(f"Gemini API retornou erro: {message}")
        return data

    def _friendly_http_error(self, exc: urllib.error.HTTPError, detail: str) -> str:
        text = detail or str(exc)
        if exc.code in {400, 404}:
            return (
                "A Gemini API recusou a requisição. Verifique se o modelo está correto. "
                "Sugestão: gemini-3.1-flash-lite. Alternativa: gemini-2.5-flash-lite. "
                f"Detalhe: {text[:800]}"
            )
        if exc.code in {401, 403}:
            return (
                "API Key inválida, sem permissão ou com API não habilitada no Google AI Studio. "
                f"Detalhe: {text[:800]}"
            )
        if exc.code == 429:
            return (
                "Limite gratuito da Gemini API atingido ou muitas chamadas em pouco tempo. "
                "Aguarde um pouco e tente novamente com menos cenas. "
                f"Detalhe: {text[:800]}"
            )
        return f"Gemini API retornou erro HTTP {exc.code}. Detalhe: {text[:800]}"

    def _read_http_error_body(self, exc: urllib.error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _extract_response_text(self, data: Dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        texts: List[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                if isinstance(part, dict) and part.get("text"):
                    texts.append(str(part.get("text")))
        return "\n".join(texts).strip()

    def _parse_ai_json(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            logger.warning("Gemini retornou texto não JSON: %s", text[:800])
        return {
            "descricao_curta": text[:300].strip(),
            "descricao_detalhada": text.strip(),
            "tags": [],
            "tipo": "Geral",
            "potencial_video": "Médio",
            "sugestao_uso": "Revise manualmente antes de usar no vídeo.",
        }

    def _build_prompt(self, context: Dict[str, Any]) -> str:
        anime = str(context.get("anime") or "Anime não informado").strip()
        season = str(context.get("season") or "Temporada não informada").strip()
        episode = str(context.get("episode") or "Episódio não informado").strip()
        display_name = str(context.get("display_name") or "Cena").strip()
        start = str(context.get("start") or "").strip()
        end = str(context.get("end") or "").strip()
        duration = str(context.get("duration") or "").strip()

        return f"""
Analise o frame anexado de uma cena de anime e responda em português do Brasil.

Contexto:
- Anime/Pasta: {anime}
- Temporada: {season}
- Episódio/Arquivo: {episode}
- Cena: {display_name}
- Trecho: {start} até {end}
- Duração: {duration}

Regras:
- Descreva apenas o que é visualmente provável.
- Não invente nomes de personagens se não estiver claro.
- Não invente falas.
- Seja útil para criador de TikTok/Reels/Shorts.
- Retorne somente JSON válido, sem markdown.

Formato obrigatório:
{{
  "descricao_curta": "uma frase curta sobre a cena",
  "descricao_detalhada": "2 a 3 frases objetivas sobre o que parece acontecer visualmente",
  "tags": ["tag1", "tag2", "tag3"],
  "tipo": "Ação | Luta | Diálogo | Comédia | Drama | Suspense | Romance | Transformação | Poder/Habilidade | Revelação | Cena épica | Outro",
  "potencial_video": "Baixo | Médio | Alto | Muito alto",
  "motivo_potencial": "motivo curto",
  "sugestao_uso": "como essa cena poderia ser usada em vídeo curto"
}}
""".strip()

    def _build_clip_prompt(self, context: Dict[str, Any]) -> str:
        anime = str(context.get("anime") or "Anime não informado").strip()
        season = str(context.get("season") or "Temporada não informada").strip()
        episode = str(context.get("episode") or "Episódio não informado").strip()
        clip_name = str(context.get("clip_name") or "Clipe exportado").strip()
        duration = str(context.get("duration") or "").strip()
        source_range = str(context.get("source_range") or "").strip()
        segments = str(context.get("segments_summary") or "").strip()
        existing_scene_notes = str(context.get("scene_notes") or "").strip()

        return f"""
Analise os frames anexados de um clipe exportado de anime e responda em português do Brasil.

Contexto do clipe:
- Anime/Pasta: {anime}
- Temporada de origem: {season}
- Episódio/Arquivo de origem: {episode}
- Nome do clipe: {clip_name}
- Duração do clipe: {duration}
- Trecho(s) de origem: {source_range}
- Segmentos usados: {segments}
- Observações já existentes das cenas: {existing_scene_notes}

Regras:
- Descreva o clipe final como um todo, não apenas um frame isolado.
- Não invente nomes de personagens se não estiver claro.
- Não invente falas.
- Seja útil para criador de TikTok/Reels/Shorts.
- Foque em conteúdo, clima, possível uso e gancho visual.
- Retorne somente JSON válido, sem markdown.

Formato obrigatório:
{{
  "descricao_curta": "uma frase curta sobre o clipe",
  "descricao_detalhada": "2 a 4 frases objetivas sobre o que o clipe parece mostrar",
  "tags": ["tag1", "tag2", "tag3"],
  "tipo": "Ação | Luta | Diálogo | Comédia | Drama | Suspense | Romance | Transformação | Poder/Habilidade | Revelação | Cena épica | Exploração | Introdução | Outro",
  "potencial_video": "Baixo | Médio | Alto | Muito alto",
  "motivo_potencial": "motivo curto",
  "sugestao_uso": "como esse clipe poderia ser usado em vídeo curto"
}}
""".strip()

    def _select_clip_frames(self, frames: Sequence[Path], limit: int = 3) -> List[Path]:
        valid = [Path(frame) for frame in frames if Path(frame).exists()]
        if not valid:
            raise GeminiSceneAIError("Nenhum frame válido encontrado.")
        if len(valid) <= limit:
            return valid
        if limit <= 1:
            return [valid[len(valid) // 2]]
        indexes = [0, len(valid) // 2, len(valid) - 1]
        selected: List[Path] = []
        for index in indexes:
            frame = valid[max(0, min(index, len(valid) - 1))]
            if frame not in selected:
                selected.append(frame)
            if len(selected) >= limit:
                break
        return selected

    def _select_representative_frame(self, frames: Sequence[Path]) -> Path:
        valid = [Path(frame) for frame in frames if Path(frame).exists()]
        if not valid:
            raise GeminiSceneAIError("Nenhum frame válido encontrado.")
        return valid[len(valid) // 2]

    def _encode_image(self, path: Path) -> str:
        try:
            return base64.b64encode(path.read_bytes()).decode("ascii")
        except Exception as exc:
            raise GeminiSceneAIError(f"Não foi possível ler o frame para enviar à API: {path}") from exc

    def _guess_mime_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".webp":
            return "image/webp"
        return "image/jpeg"

    def _clean_api_key(self, api_key: str) -> str:
        value = str(api_key or "").strip()
        if not value:
            raise GeminiSceneAIError(
                "Informe sua API Key do Gemini. Crie uma chave gratuita no Google AI Studio e cole no campo API Key."
            )
        return value

    def _clean_model_name(self, model: str) -> str:
        """Normaliza o nome do modelo Gemini.

        O gemini-2.5-flash passou a ser recusado para algumas chaves novas.
        Por isso, o padrão seguro do TEDVHS Studio passa a ser
        gemini-3.1-flash-lite, que é multimodal e tem Free Tier.
        """
        value = str(model or DEFAULT_GEMINI_MODEL).strip()
        if value.startswith("models/"):
            value = value.split("/", 1)[1]

        aliases = {
            "gemini-2.5-flash": DEFAULT_GEMINI_MODEL,
            "models/gemini-2.5-flash": DEFAULT_GEMINI_MODEL,
            "gemini-flash": DEFAULT_GEMINI_MODEL,
            "flash": DEFAULT_GEMINI_MODEL,
        }
        return aliases.get(value, value or DEFAULT_GEMINI_MODEL)

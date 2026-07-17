"""Serviço Gemini para gerar roteiro de narração e pacote de postagem de clipes.

Esta sprint usa somente texto: descrição, tags e legenda PT-BR já geradas.
Não envia vídeo nem frames, então não pesa no PC do usuário.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_NARRATION_MODEL = "gemini-3.1-flash-lite"


class GeminiNarrationError(RuntimeError):
    """Erro amigável da geração de roteiro com Gemini."""


class GeminiNarrationService:
    """Cliente mínimo para gerar roteiros de narração e textos para TikTok."""

    def __init__(self, timeout_seconds: int = 120):
        self.timeout_seconds = max(30, int(timeout_seconds or 120))
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def generate_clip_narration(self, context: Dict[str, Any], api_key: str, model: str = DEFAULT_NARRATION_MODEL) -> Dict[str, Any]:
        api_key = self._clean_api_key(api_key)
        model = self._clean_model_name(model)
        prompt = self._build_prompt(context)
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.65,
                "topP": 0.9,
                "maxOutputTokens": 2200,
            },
        }
        data = self._generate_content(api_key=api_key, model=model, payload=payload, timeout_seconds=self.timeout_seconds)
        raw_response = self._extract_response_text(data).strip()
        if not raw_response:
            raise GeminiNarrationError("A API respondeu, mas não retornou texto para o roteiro.")
        parsed = self._parse_ai_json(raw_response)
        parsed["modelo"] = model
        parsed["resposta_bruta"] = raw_response
        return self._normalize_result(parsed)

    def _build_prompt(self, context: Dict[str, Any]) -> str:
        anime = str(context.get("anime") or "Anime não informado").strip()
        season = str(context.get("season") or "Temporada não informada").strip()
        episode = str(context.get("episode") or "Episódio não informado").strip()
        clip_name = str(context.get("clip_name") or "Clipe exportado").strip()
        duration = str(context.get("duration") or "").strip()
        duration_seconds = self._safe_float(context.get("duration_seconds") or 0.0)
        scene_type = str(context.get("scene_type") or "Geral").strip()
        tags = self._tags_to_text(context.get("tags") or "")
        description = str(context.get("description") or "").strip()
        subtitle_text = str(context.get("subtitle_text") or "").strip()
        style = str(context.get("style") or "Empolgado").strip()
        length = str(context.get("length") or "Acompanhar clipe inteiro").strip()
        duration_instruction = self._duration_instruction(length, duration_seconds)

        if not description:
            description = "Sem descrição detalhada salva. Use as demais informações sem inventar demais."
        if not subtitle_text:
            subtitle_text = "Sem legenda PT-BR disponível. Não invente falas específicas."

        return f"""
Você é roteirista de vídeos curtos sobre animes para o canal TEDVHS.
Gere um pacote em português do Brasil para narrador e postagem.

Contexto do clipe:
- Anime/Pasta: {anime}
- Temporada: {season}
- Episódio: {episode}
- Nome do clipe: {clip_name}
- Duração do clipe: {duration}
- Tipo: {scene_type}
- Tags: {tags}
- Estilo desejado: {style}
- Tamanho/duração desejada da narração: {length}
- Instrução de duração: {duration_instruction}

Descrição já gerada do clipe:
{description[:3500]}

Legenda PT-BR/transcrição disponível do clipe:
{subtitle_text[:5000]}

Regras importantes:
- Não finja certeza sobre nomes de personagens se o contexto não informar.
- Não cite falas literais se elas não aparecem na legenda.
- Crie um texto de narrador natural, com cara de vídeo de TikTok/Reels/Shorts.
- A duração solicitada se refere à NARRAÇÃO em áudio, não à legenda do anime.
- Se a instrução pedir para acompanhar o clipe inteiro, não faça só uma introdução curta; crie falas suficientes para chegar perto do final do vídeo.
- Use uma abertura forte nos primeiros segundos.
- Não use linguagem robótica.
- Não coloque mais de 5 hashtags.
- Não use markdown.
- Retorne somente JSON válido.

Formato obrigatório:
{{
  "gancho": "frase inicial forte para prender atenção",
  "roteiro_narracao": "texto completo para o narrador ler, no tamanho solicitado",
  "resumo_apresentacao": "resumo curto do anime/clipe em 1 ou 2 frases",
  "titulo_tiktok": "título curto e chamativo",
  "texto_tiktok": "texto pronto para publicação, com chamada para comentar/salvar/seguir quando fizer sentido",
  "hashtags": ["#anime", "#otaku", "#animes", "#tedvhs", "#isekai"],
  "cta": "chamada final curta para o vídeo"
}}
""".strip()

    def _duration_instruction(self, length: str, duration_seconds: float) -> str:
        text = str(length or "").lower()
        if "acompanhar" in text or "inteiro" in text or "todo" in text:
            if duration_seconds > 0:
                target_words = max(45, int(round(duration_seconds * 2.25)))
                return (
                    f"A narração deve cobrir quase todo o clipe. Duração-alvo: {duration_seconds:.0f} segundos. "
                    f"Gere aproximadamente {target_words} palavras, mantendo ritmo natural para voz TTS em português do Brasil."
                )
            return "A narração deve cobrir quase todo o clipe, não apenas uma introdução curta."
        if "curto" in text:
            return "Gere uma narração curta, com cerca de 20 a 30 segundos."
        if "longo" in text:
            return "Gere uma narração longa, com cerca de 75 a 90 segundos."
        return "Gere uma narração média, com cerca de 45 a 60 segundos."

    def _safe_float(self, value: Any) -> float:
        try:
            return max(float(value or 0.0), 0.0)
        except Exception:
            return 0.0

    def _generate_content(self, api_key: str, model: str, payload: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
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
            raise GeminiNarrationError(self._friendly_http_error(exc, detail)) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise GeminiNarrationError(
                "Não foi possível conectar à Gemini API para gerar roteiro. Verifique internet, API Key e tente novamente. "
                f"Detalhe: {exc}"
            ) from exc
        except Exception as exc:
            raise GeminiNarrationError(f"Erro inesperado ao chamar Gemini API para roteiro: {exc}") from exc

        try:
            data = json.loads(raw)
        except Exception as exc:
            raise GeminiNarrationError(f"A API respondeu, mas o retorno não era JSON válido: {raw[:500]}") from exc
        if isinstance(data, dict) and data.get("error"):
            error = data.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise GeminiNarrationError(f"Gemini API retornou erro: {message}")
        return data

    def _friendly_http_error(self, exc: urllib.error.HTTPError, detail: str) -> str:
        text = detail or str(exc)
        if exc.code in {400, 404}:
            return (
                "A Gemini API recusou a requisição de roteiro. Verifique se o modelo está correto. "
                "Use o mesmo modelo que funcionou nas descrições/legendas. "
                f"Detalhe: {text[:800]}"
            )
        if exc.code in {401, 403}:
            return "API Key inválida, sem permissão ou API não habilitada. " + f"Detalhe: {text[:800]}"
        if exc.code == 429:
            return "Limite gratuito da Gemini API atingido. Aguarde um pouco e tente novamente. " + f"Detalhe: {text[:800]}"
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
            cleaned = cleaned[start:end + 1]
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            logger.warning("Gemini retornou roteiro não JSON: %s", text[:800])
        return {
            "gancho": "Esse anime pode te surpreender.",
            "roteiro_narracao": text.strip(),
            "resumo_apresentacao": "Resumo gerado pela IA. Revise antes de publicar.",
            "titulo_tiktok": "Esse anime merece atenção",
            "texto_tiktok": "Você assistiria esse anime? Comenta aí e salva para ver depois.",
            "hashtags": ["#anime", "#otaku", "#animes", "#tedvhs", "#recomendacao"],
            "cta": "Segue o TEDVHS para mais recomendações de anime.",
        }

    def _normalize_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        hashtags = result.get("hashtags") or []
        if isinstance(hashtags, str):
            items = re.split(r"[,;\s]+", hashtags)
        else:
            items = [str(item) for item in hashtags]
        clean_tags: List[str] = []
        for item in items:
            tag = str(item or "").strip()
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = "#" + tag.lstrip("#")
            tag = re.sub(r"[^#\wÀ-ÿ]", "", tag)
            if tag and tag not in clean_tags:
                clean_tags.append(tag)
            if len(clean_tags) >= 5:
                break
        if not clean_tags:
            clean_tags = ["#anime", "#otaku", "#animes", "#tedvhs", "#recomendacao"]

        normalized = dict(result)
        normalized["gancho"] = str(result.get("gancho") or "").strip()
        normalized["roteiro_narracao"] = str(result.get("roteiro_narracao") or result.get("roteiro") or "").strip()
        normalized["resumo_apresentacao"] = str(result.get("resumo_apresentacao") or "").strip()
        normalized["titulo_tiktok"] = str(result.get("titulo_tiktok") or result.get("titulo") or "").strip()
        normalized["texto_tiktok"] = str(result.get("texto_tiktok") or result.get("texto_publicacao") or "").strip()
        normalized["hashtags"] = clean_tags
        normalized["cta"] = str(result.get("cta") or "").strip()
        return normalized

    def _clean_api_key(self, api_key: str) -> str:
        value = str(api_key or "").strip()
        if not value:
            raise GeminiNarrationError("Informe sua API Key do Gemini antes de gerar roteiro.")
        return value

    def _clean_model_name(self, model: str) -> str:
        value = str(model or DEFAULT_NARRATION_MODEL).strip()
        if value.startswith("models/"):
            value = value.split("/", 1)[1]
        aliases = {
            "gemini-2.5-flash": DEFAULT_NARRATION_MODEL,
            "models/gemini-2.5-flash": DEFAULT_NARRATION_MODEL,
            "gemini-flash": DEFAULT_NARRATION_MODEL,
            "flash": DEFAULT_NARRATION_MODEL,
        }
        return aliases.get(value, value or DEFAULT_NARRATION_MODEL)

    def _tags_to_text(self, tags: Any) -> str:
        if isinstance(tags, list):
            return ", ".join(str(tag) for tag in tags)
        return str(tags or "")

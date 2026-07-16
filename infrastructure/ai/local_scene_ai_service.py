"""Serviço de IA local gratuita para descrever cenas por frames.

Integração com Ollama local, sem API paga. Esta versão usa o endpoint
/api/chat para modelos de visão porque ele tende a tratar imagens anexadas de
forma mais consistente do que /api/generate em alguns builds do Ollama/LLaVA.
Também evita respostas do tipo "a imagem não está disponível" quando o frame
foi enviado corretamente.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Sequence

logger = logging.getLogger(__name__)


class LocalSceneAIError(RuntimeError):
    """Erro amigável da IA local."""


class LocalSceneAIService:
    """Cliente mínimo para Ollama local usando apenas biblioteca padrão."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout_seconds: int = 900):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(30, int(timeout_seconds or 900))

    def is_available(self) -> bool:
        """Retornar True se o Ollama local responder."""
        try:
            self.list_models(timeout_seconds=4)
            return True
        except Exception:
            return False

    def list_model_infos(self, timeout_seconds: int = 8) -> List[Dict[str, Any]]:
        """Listar modelos instalados no Ollama local com metadados."""
        try:
            data = self._request_json("GET", "/api/tags", timeout_seconds=timeout_seconds)
        except Exception as exc:
            raise LocalSceneAIError(
                "Ollama não respondeu em http://127.0.0.1:11434. "
                "Abra o Ollama no Windows e instale/execute um modelo de visão, exemplo: llava."
            ) from exc
        models = data.get("models", []) if isinstance(data, dict) else []
        return [item for item in models if isinstance(item, dict)]

    def list_models(self, timeout_seconds: int = 8) -> List[str]:
        """Listar nomes dos modelos instalados no Ollama local."""
        names: List[str] = []
        for item in self.list_model_infos(timeout_seconds=timeout_seconds):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                names.append(name)
        return names

    def resolve_model_name(self, requested_model: str = "llava") -> str:
        """Resolver llava -> llava:latest quando esse for o modelo instalado."""
        requested = (requested_model or "llava").strip() or "llava"
        try:
            installed = self.list_models(timeout_seconds=8)
        except LocalSceneAIError:
            raise
        except Exception as exc:
            raise LocalSceneAIError(f"Não foi possível listar os modelos do Ollama: {exc}") from exc

        if not installed:
            raise LocalSceneAIError(
                "Ollama respondeu, mas nenhum modelo foi encontrado. "
                "Instale um modelo de visão, por exemplo: ollama run llava"
            )

        if requested in installed:
            return requested

        requested_base = requested.split(":", 1)[0].lower()
        for name in installed:
            if name.lower() == f"{requested_base}:latest":
                return name
        for name in installed:
            if name.split(":", 1)[0].lower() == requested_base:
                return name

        preferred = next((name for name in installed if "llava" in name.lower() or "vision" in name.lower()), None)
        if preferred:
            return preferred

        raise LocalSceneAIError(
            f"Modelo '{requested}' não encontrado no Ollama. Modelos instalados: {', '.join(installed[:10])}"
        )

    def model_has_vision(self, model_name: str) -> bool:
        """Verificar se o modelo listado informa suporte a visão."""
        resolved = self.resolve_model_name(model_name)
        for item in self.list_model_infos(timeout_seconds=8):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name != resolved:
                continue
            capabilities = item.get("capabilities") or []
            if isinstance(capabilities, list):
                return any(str(capability).lower() == "vision" for capability in capabilities)
        return True

    def describe_scene(
        self,
        frame_paths: Sequence[str | Path],
        context: Dict[str, Any],
        model: str = "llava",
    ) -> Dict[str, Any]:
        """Gerar descrição/tags/tipo usando frames da cena."""
        frames = [Path(path) for path in frame_paths if path and Path(path).exists() and Path(path).stat().st_size > 0]
        if not frames:
            raise LocalSceneAIError("Nenhum frame válido foi gerado para enviar à IA local.")

        model_name = self.resolve_model_name(model or "llava")
        if not self.model_has_vision(model_name):
            raise LocalSceneAIError(
                f"O modelo '{model_name}' está instalado, mas não informa suporte a visão. "
                "Use um modelo com capacidade de imagem, exemplo: llava:latest."
            )

        # Para o llava padrão, 1 frame costuma ser mais estável e evita limite de contexto.
        selected_frames = self._select_representative_frames(frames, max_images=1)
        prompt = self._build_prompt(context)

        try:
            data = self._chat_with_images(
                model_name=model_name,
                prompt=prompt,
                frames=selected_frames,
                num_ctx=4096,
                num_predict=320,
            )
        except urllib.error.HTTPError as exc:
            body = self._read_http_error_body(exc)
            if self._is_context_error(body):
                try:
                    data = self._chat_with_images(
                        model_name=model_name,
                        prompt=self._build_ultra_compact_prompt(context),
                        frames=self._select_representative_frames(frames, max_images=1),
                        num_ctx=2048,
                        num_predict=220,
                    )
                except urllib.error.HTTPError as retry_exc:
                    retry_body = self._read_http_error_body(retry_exc)
                    raise LocalSceneAIError(
                        f"O modelo '{model_name}' recusou a análise porque o contexto visual ficou grande demais. "
                        "Tente uma cena menor ou outro modelo de visão local. "
                        f"Detalhe: {retry_body or retry_exc}"
                    ) from retry_exc
            else:
                raise LocalSceneAIError(
                    f"Ollama recusou a análise com o modelo '{model_name}'. "
                    f"Detalhe: {body or exc}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise LocalSceneAIError(
                f"Ollama foi encontrado, mas o modelo '{model_name}' demorou demais ou não respondeu. "
                "Na primeira análise o modelo pode levar alguns minutos para carregar. "
                "Tente novamente com uma cena curta."
            ) from exc
        except Exception as exc:
            raise LocalSceneAIError(f"Erro ao chamar a IA local: {exc}") from exc

        raw_response = self._extract_response_text(data).strip()
        if not raw_response:
            raise LocalSceneAIError("A IA local retornou uma resposta vazia.")

        # Alguns modelos dizem que a imagem não está disponível mesmo quando ela foi enviada.
        # Nesses casos, fazemos uma segunda tentativa com prompt direto e em inglês, que costuma
        # ativar melhor a leitura visual do LLaVA, mantendo a saída em português.
        if self._looks_like_missing_image_response(raw_response):
            try:
                retry_data = self._chat_with_images(
                    model_name=model_name,
                    prompt=self._build_visual_retry_prompt(context),
                    frames=selected_frames,
                    num_ctx=4096,
                    num_predict=280,
                )
                retry_response = self._extract_response_text(retry_data).strip()
                if retry_response and not self._looks_like_missing_image_response(retry_response):
                    raw_response = retry_response
            except Exception as exc:
                logger.warning("Retry visual do Ollama falhou: %s", exc)

        parsed = self._parse_ai_json(raw_response)
        parsed["modelo"] = model_name
        parsed["resposta_bruta"] = raw_response
        parsed["frames_usados"] = [str(path) for path in selected_frames]
        return parsed

    def format_description(self, result: Dict[str, Any]) -> str:
        """Formatar o resultado para o campo descrição da cena."""
        curta = str(result.get("descricao_curta") or "").strip()
        detalhada = str(result.get("descricao_detalhada") or "").strip()
        potencial = str(result.get("potencial_video") or "").strip()
        uso = str(result.get("sugestao_uso") or "").strip()

        parts = []
        if curta:
            parts.append(curta)
        if detalhada and detalhada.lower() != curta.lower():
            parts.append(f"Detalhes: {detalhada}")
        if potencial:
            parts.append(f"Potencial para vídeo curto: {potencial}")
        if uso:
            parts.append(f"Sugestão de uso: {uso}")
        return "\n\n".join(parts).strip() or str(result.get("resposta_bruta") or "").strip()

    def normalize_tags(self, result: Dict[str, Any]) -> str:
        tags = result.get("tags") or []
        if isinstance(tags, str):
            raw_items = re.split(r"[,;\n]+", tags)
        else:
            raw_items = [str(item) for item in tags]
        clean = []
        for item in raw_items:
            value = str(item or "").strip().lower()
            value = re.sub(r"\s+", " ", value)
            if value and value not in clean:
                clean.append(value)
        return ", ".join(clean[:12])

    def normalize_scene_type(self, result: Dict[str, Any]) -> str:
        value = str(result.get("tipo") or result.get("scene_type") or "Geral").strip()
        return value or "Geral"

    def _chat_with_images(
        self,
        model_name: str,
        prompt: str,
        frames: Sequence[Path],
        num_ctx: int = 4096,
        num_predict: int = 320,
    ) -> Dict[str, Any]:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [self._encode_image(path) for path in frames],
                }
            ],
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0.1,
                "top_p": 0.85,
                "num_ctx": max(2048, int(num_ctx or 4096)),
                "num_predict": max(160, int(num_predict or 280)),
            },
        }
        return self._request_json("POST", "/api/chat", payload=payload, timeout_seconds=self.timeout_seconds)

    def _generate_with_images(
        self,
        model_name: str,
        prompt: str,
        frames: Sequence[Path],
        num_ctx: int = 4096,
        num_predict: int = 320,
    ) -> Dict[str, Any]:
        payload = {
            "model": model_name,
            "prompt": prompt,
            "images": [self._encode_image(path) for path in frames],
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0.1,
                "top_p": 0.85,
                "num_ctx": max(2048, int(num_ctx or 4096)),
                "num_predict": max(160, int(num_predict or 280)),
            },
        }
        return self._request_json("POST", "/api/generate", payload=payload, timeout_seconds=self.timeout_seconds)

    def _select_representative_frames(self, frames: Sequence[Path], max_images: int = 1) -> List[Path]:
        clean = [Path(path) for path in frames if path and Path(path).exists() and Path(path).stat().st_size > 0]
        if not clean:
            return []
        max_images = max(1, min(int(max_images or 1), 2))
        if len(clean) <= max_images:
            return clean
        # Para descrição inicial, o frame do meio costuma ser mais informativo que início/fim.
        if max_images == 1:
            return [clean[len(clean) // 2]]
        return [clean[0], clean[len(clean) // 2]]

    def _read_http_error_body(self, exc: urllib.error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            return ""

    def _is_context_error(self, body: str) -> bool:
        value = (body or "").lower()
        return "exceed_context" in value or "context size" in value or ("context" in value and "token" in value)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        with urllib.request.urlopen(request, timeout=timeout_seconds or self.timeout_seconds) as response:
            text = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise LocalSceneAIError(f"Ollama respondeu, mas não retornou JSON válido: {text[:500]}") from exc

    def _encode_image(self, path: Path) -> str:
        with open(path, "rb") as file:
            return base64.b64encode(file.read()).decode("ascii")

    def _extract_response_text(self, data: Dict[str, Any]) -> str:
        if not isinstance(data, dict):
            return ""
        message = data.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if content:
                return str(content)
        return str(data.get("response") or "")

    def _build_prompt(self, context: Dict[str, Any]) -> str:
        anime = str(context.get("anime") or "não informado")[:60]
        episode = str(context.get("episode") or "não informado")[:70]
        start = str(context.get("start") or "")
        end = str(context.get("end") or "")

        return (
            "Você recebeu 1 imagem/frame de uma cena de anime. A imagem está anexada nesta mensagem.\n"
            "Tarefa: descreva apenas o que aparece visualmente no frame, em português do Brasil.\n"
            "Nunca responda que a imagem não está disponível. Se a imagem estiver escura, borrada ou simples, descreva isso.\n"
            "Não invente nomes, falas, poderes, relações ou fatos que não estejam visíveis.\n"
            f"Contexto opcional: anime={anime}; episódio={episode}; trecho={start}-{end}.\n"
            "Responda SOMENTE JSON válido neste formato:\n"
            '{"descricao_curta":"uma frase visual objetiva",'
            '"descricao_detalhada":"uma ou duas frases sobre personagens, ambiente, ação e clima visual",'
            '"tags":["tag1","tag2","tag3","tag4"],'
            '"tipo":"Ação/Luta/Diálogo/Comédia/Drama/Suspense/Romance/Revelação/Cena épica/Outro",'
            '"potencial_video":"Baixo/Médio/Alto/Muito alto",'
            '"sugestao_uso":"como usar esta cena em vídeo curto"}'
        )

    def _build_ultra_compact_prompt(self, context: Dict[str, Any]) -> str:
        return (
            "A imagem está anexada. Descreva visualmente em PT-BR. "
            "Não diga que a imagem não está disponível. Só JSON: "
            '{"descricao_curta":"...","descricao_detalhada":"...","tags":["..."],'
            '"tipo":"Outro","potencial_video":"Médio","sugestao_uso":"..."}'
        )

    def _build_visual_retry_prompt(self, context: Dict[str, Any]) -> str:
        return (
            "An image frame is attached to this message. You can see it. "
            "Do not apologize and do not say the image is unavailable. "
            "If the image is dark or unclear, describe it as dark/unclear. "
            "Return the answer in Brazilian Portuguese as valid JSON only with keys: "
            "descricao_curta, descricao_detalhada, tags, tipo, potencial_video, sugestao_uso."
        )

    def _looks_like_missing_image_response(self, text: str) -> bool:
        value = (text or "").lower()
        patterns = [
            "imagem não está disponível",
            "imagem nao esta disponivel",
            "não posso fornecer uma descrição",
            "nao posso fornecer uma descricao",
            "não consigo ver a imagem",
            "nao consigo ver a imagem",
            "image is not available",
            "image unavailable",
            "cannot see the image",
            "can't see the image",
            "no image provided",
        ]
        return any(pattern in value for pattern in patterns)

    def _parse_ai_json(self, text: str) -> Dict[str, Any]:
        """Extrair JSON mesmo quando o modelo devolve texto extra."""
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

        candidates = [cleaned]
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first >= 0 and last > first:
            candidates.append(cleaned[first:last + 1])

        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return self._normalize_result(data)
            except Exception:
                continue

        # Fallback seguro: salva a resposta como descrição curta.
        return self._normalize_result({
            "descricao_curta": cleaned[:500],
            "descricao_detalhada": cleaned,
            "tags": [],
            "tipo": "Geral",
            "potencial_video": "Médio",
            "sugestao_uso": "Revisar manualmente a resposta da IA local.",
        })

    def _normalize_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        tags = data.get("tags") or []
        if isinstance(tags, str):
            tags = [item.strip() for item in re.split(r"[,;\n]+", tags) if item.strip()]
        elif not isinstance(tags, list):
            tags = []

        return {
            "descricao_curta": str(data.get("descricao_curta") or data.get("short_description") or "").strip(),
            "descricao_detalhada": str(data.get("descricao_detalhada") or data.get("description") or "").strip(),
            "tags": [str(item).strip() for item in tags if str(item).strip()][:12],
            "tipo": str(data.get("tipo") or data.get("scene_type") or "Geral").strip() or "Geral",
            "potencial_video": str(data.get("potencial_video") or data.get("potencial") or "Médio").strip() or "Médio",
            "sugestao_uso": str(data.get("sugestao_uso") or data.get("uso") or "").strip(),
        }

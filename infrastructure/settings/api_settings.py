"""Armazenamento local simples de configurações de API do TEDVHS Studio.

A chave é salva localmente em JSON dentro de data/settings.
Isto evita digitar a chave a cada abertura do app, mas não é criptografia.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"


class ApiSettingsStore:
    """Salvar e carregar API Key/modelo do Gemini em arquivo local."""

    def __init__(self, settings_path: str | Path | None = None) -> None:
        self.settings_path = Path(settings_path or Path("data") / "settings" / "api_settings.json")

    def get_gemini_api_key(self) -> str:
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        if env_key.strip():
            return env_key.strip()
        return str(self._read().get("gemini_api_key") or "").strip()

    def get_gemini_model(self, default: str = DEFAULT_GEMINI_MODEL) -> str:
        env_model = os.environ.get("GEMINI_MODEL") or ""
        if env_model.strip():
            return env_model.strip()
        return str(self._read().get("gemini_model") or default or DEFAULT_GEMINI_MODEL).strip()

    def save_gemini(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> None:
        api_key = str(api_key or "").strip()
        model = str(model or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        if not api_key:
            raise ValueError("API Key vazia não pode ser salva.")
        data = self._read()
        data["gemini_api_key"] = api_key
        data["gemini_model"] = model
        self._write(data)

    def save_gemini_model(self, model: str = DEFAULT_GEMINI_MODEL) -> None:
        model = str(model or DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        data = self._read()
        data["gemini_model"] = model
        self._write(data)

    def clear_gemini_api_key(self) -> None:
        data = self._read()
        data.pop("gemini_api_key", None)
        self._write(data)

    def _read(self) -> Dict[str, Any]:
        try:
            if not self.settings_path.exists():
                return {}
            raw = self.settings_path.read_text(encoding="utf-8")
            data = json.loads(raw or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write(self, data: Dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(dict(data or {}), ensure_ascii=False, indent=2)
        self.settings_path.write_text(text, encoding="utf-8")
        try:
            os.chmod(self.settings_path, 0o600)
        except Exception:
            # Windows pode ignorar chmod POSIX; o arquivo ainda fica local no PC do usuário.
            pass

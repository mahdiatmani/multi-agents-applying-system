import os
from typing import Any

import httpx

# Back-compat alias. The system now thinks in *roles* (REASONING_MODEL /
# CODING_MODEL — see tools/model_router.py); DEFAULT_LLM_MODEL maps to the
# reasoning role so older call sites that pass no explicit model keep working.
DEFAULT_LLM_MODEL = os.getenv("REASONING_MODEL", os.getenv("DEFAULT_LLM_MODEL", "gpt-oss:120b-cloud"))


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def _model_name(model: Any) -> str:
    if isinstance(model, dict):
        return str(model.get("name") or model.get("model") or "")
    return str(model or "")


def fetch_ollama_models(base_url: str | None = None, timeout: float = 4.0) -> list[dict]:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{base_url or get_ollama_base_url()}/api/tags")
            response.raise_for_status()
            payload = response.json() or {}
            raw = payload.get("models")
            return raw if isinstance(raw, list) else []
    except Exception as exc:
        print(f"Error fetching Ollama models: {exc}")
        return []


async def fetch_ollama_models_async(base_url: str | None = None, timeout: float = 4.0) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url or get_ollama_base_url()}/api/tags")
            response.raise_for_status()
            payload = response.json() or {}
            raw = payload.get("models")
            return raw if isinstance(raw, list) else []
    except Exception as exc:
        print(f"Error fetching Ollama models: {exc}")
        return []


def local_model_names(model_infos: list[Any]) -> list[str]:
    names = [_model_name(model) for model in model_infos if _model_name(model)]
    if DEFAULT_LLM_MODEL in names:
        names = [DEFAULT_LLM_MODEL] + [name for name in names if name != DEFAULT_LLM_MODEL]
    return names


def resolve_model(requested_model: str | None) -> str:
    requested = (requested_model or "").strip()
    return requested or DEFAULT_LLM_MODEL

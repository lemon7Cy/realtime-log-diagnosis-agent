"""Small LLM adapter for model listing and connection tests."""

from __future__ import annotations

from typing import Any

import anthropic
import httpx

try:
    from .llm_config import LLMConfig
except ImportError:
    from llm_config import LLMConfig


def openai_base_url(config: LLMConfig) -> str:
    base_url = (config.base_url or "").rstrip("/")
    if config.provider in {"deepseek", "newapi"} and base_url and not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def use_openai_compatible(config: LLMConfig) -> bool:
    return config.provider in {"deepseek", "newapi"}


async def list_models(config: LLMConfig) -> list[str]:
    if not config.api_key:
        raise RuntimeError("LLM API key is not configured")

    if not use_openai_compatible(config):
        client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url or None,
            timeout=config.timeout,
        )
        models = await client.models.list()
        return sorted(model.id for model in models.data if getattr(model, "id", None))

    base_url = openai_base_url(config)
    if not base_url:
        raise RuntimeError("OpenAI-compatible base_url is not configured")

    candidate_urls = [f"{base_url}/models"]
    raw_base = (config.base_url or "").rstrip("/")
    if raw_base and raw_base != base_url:
        candidate_urls.append(f"{raw_base}/models")

    last_error = ""
    async with httpx.AsyncClient(timeout=config.timeout) as client:
        for url in candidate_urls:
            try:
                response = await client.get(url, headers={"Authorization": f"Bearer {config.api_key}"})
                response.raise_for_status()
                payload = response.json()
                return _model_ids(payload)
            except Exception as exc:
                preview = ""
                try:
                    preview = response.text[:200].replace("\n", " ")  # type: ignore[name-defined]
                except Exception:
                    pass
                last_error = f"{url}: {exc}; response={preview}"
    raise RuntimeError(last_error or "failed to fetch models")


async def test_model(config: LLMConfig) -> str:
    if not config.api_key:
        raise RuntimeError("LLM API key is not configured")
    if not config.model:
        raise RuntimeError("LLM model is not configured")

    if not use_openai_compatible(config):
        client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url or None,
            timeout=config.timeout,
        )
        response = await client.messages.create(
            model=config.model,
            max_tokens=16,
            temperature=0,
            messages=[{"role": "user", "content": "Reply with OK only."}],
        )
        return "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()

    async with httpx.AsyncClient(timeout=config.timeout) as client:
        response = await client.post(
            f"{openai_base_url(config)}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            json={
                "model": config.model,
                "messages": [{"role": "user", "content": "Reply with OK only."}],
                "temperature": 0,
                "max_tokens": 16,
            },
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"].get("content") or ""


def _model_ids(payload: Any) -> list[str]:
    raw_models = payload.get("data", payload) if isinstance(payload, dict) else payload
    model_ids: list[str] = []
    if isinstance(raw_models, list):
        for item in raw_models:
            if isinstance(item, str):
                model_ids.append(item)
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("model") or item.get("name")
                if model_id:
                    model_ids.append(str(model_id))
    return sorted(set(model_ids))

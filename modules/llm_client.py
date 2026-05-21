from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


class LLMConfigurationError(RuntimeError):
    """Raised when Qwen/DashScope configuration is incomplete."""


class LLMResponseError(RuntimeError):
    """Raised when the model response cannot be used."""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    enable_thinking: bool


def load_config() -> LLMConfig:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)

    enabled = os.getenv("ENABLE_LLM", "1").strip()
    if enabled not in {"1", "true", "True", "yes", "YES"}:
        raise LLMConfigurationError("ENABLE_LLM is disabled. Set ENABLE_LLM=1.")

    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise LLMConfigurationError("Missing QWEN_API_KEY or DASHSCOPE_API_KEY.")

    configured_max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8192"))
    max_tokens = max(8192, configured_max_tokens)
    enable_thinking = os.getenv("QWEN_ENABLE_THINKING", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    return LLMConfig(
        api_key=api_key,
        model=os.getenv("QWEN_MODEL", "qwen-plus"),
        base_url=os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        max_tokens=max_tokens,
        timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "180")),
        enable_thinking=enable_thinking,
    )


def model_name() -> str:
    return load_config().model


def call_qwen_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    config = load_config()
    url = f"{config.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
        "enable_thinking": config.enable_thinking,
    }

    try:
        response = requests.post(
            url, headers=headers, json=payload, timeout=(10, config.timeout_seconds)
        )
    except requests.RequestException as exc:
        raise LLMResponseError(f"Qwen API request failed: {exc}") from exc

    if response.status_code >= 400:
        raise LLMResponseError(
            f"Qwen API returned HTTP {response.status_code}: {response.text}"
        )

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMResponseError(f"Unexpected Qwen response shape: {response.text}") from exc

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        preview = content[:1200]
        if len(content) > 1200:
            preview += "... [truncated]"
        raise LLMResponseError(f"Qwen did not return valid JSON: {preview}") from exc


def smoke_test() -> dict[str, Any]:
    return call_qwen_json(
        "You are a JSON-only API. Return exactly valid JSON.",
        'Return {"status":"ok","provider":"qwen"} as JSON.',
    )

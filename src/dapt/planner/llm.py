"""Planner-side LLM provider configuration and OpenAI-compatible transport."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, Protocol
from urllib import error, request

PlannerProviderName = Literal["deepseek", "kimi", "glm", "qwen", "openai"]
_ALLOWED_PROVIDERS = {"deepseek", "kimi", "glm", "qwen", "openai"}


class PlannerLLMError(RuntimeError):
    """Base error for planner-side LLM configuration and transport failures."""


class PlannerLLMConfigurationError(PlannerLLMError):
    """Raised when planner-side LLM configuration is incomplete or invalid."""


class PlannerLLMTransportError(PlannerLLMError):
    """Raised when a provider request fails or returns an unusable payload."""


@dataclass(frozen=True, slots=True)
class PlannerLLMConfig:
    """Normalized repo-visible config contract for planner hypothesis generation."""

    provider: PlannerProviderName
    model: str
    api_base_url: str
    api_key_env_var: str = "DAPT_PLANNER_API_KEY"
    api_key: str | None = None
    temperature: float = 0.2
    max_output_tokens: int = 1200
    timeout_seconds: float = 30.0
    enabled: bool = True
    extra_headers: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def without_secret(self) -> PlannerLLMConfig:
        """Return a redacted view suitable for artifact persistence."""

        return replace(self, api_key=None)


class PlannerLLM(Protocol):
    """Protocol for one-shot planner hypothesis generation."""

    def complete(
        self,
        *,
        config: PlannerLLMConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Return the raw text response for the given prompt."""


def normalize_planner_llm_config(
    config: PlannerLLMConfig | Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> PlannerLLMConfig | None:
    """Normalize repo-visible config and environment boundaries."""

    resolved_env = env or {}
    if isinstance(config, PlannerLLMConfig):
        if config.api_key is not None:
            return config
        return replace(config, api_key=resolved_env.get(config.api_key_env_var))

    raw = dict(config or {})
    provider_value = raw.get("provider", resolved_env.get("DAPT_PLANNER_PROVIDER"))
    if provider_value is None:
        return None
    provider = str(provider_value).strip().lower()
    if provider not in _ALLOWED_PROVIDERS:
        raise PlannerLLMConfigurationError(
            f"Unsupported planner provider {provider_value!r}; expected one of {sorted(_ALLOWED_PROVIDERS)}."
        )

    enabled = _coerce_bool(raw.get("enabled", resolved_env.get("DAPT_PLANNER_ENABLED", "true")))
    api_key_env_var = str(raw.get("api_key_env_var", resolved_env.get("DAPT_PLANNER_API_KEY_ENV", "DAPT_PLANNER_API_KEY")))
    api_key = raw.get("api_key")
    if api_key is None:
        api_key = resolved_env.get(api_key_env_var)
    normalized = PlannerLLMConfig(
        provider=provider,
        model=str(raw.get("model", resolved_env.get("DAPT_PLANNER_MODEL", ""))).strip(),
        api_base_url=str(raw.get("api_base_url", resolved_env.get("DAPT_PLANNER_API_BASE_URL", ""))).strip(),
        api_key_env_var=api_key_env_var,
        api_key=str(api_key).strip() if api_key is not None else None,
        temperature=_coerce_float(raw.get("temperature", resolved_env.get("DAPT_PLANNER_TEMPERATURE", 0.2))),
        max_output_tokens=_coerce_int(
            raw.get("max_output_tokens", resolved_env.get("DAPT_PLANNER_MAX_OUTPUT_TOKENS", 1200))
        ),
        timeout_seconds=_coerce_float(
            raw.get("timeout_seconds", resolved_env.get("DAPT_PLANNER_TIMEOUT_SECONDS", 30.0))
        ),
        enabled=enabled,
        extra_headers=_normalize_extra_headers(raw.get("extra_headers", ())),
    )
    if not normalized.enabled:
        return normalized
    missing = []
    if not normalized.model:
        missing.append("model")
    if not normalized.api_base_url:
        missing.append("api_base_url")
    if not normalized.api_key:
        missing.append(f"api_key/{normalized.api_key_env_var}")
    if missing:
        raise PlannerLLMConfigurationError(
            "Planner LLM config is incomplete; missing " + ", ".join(missing) + "."
        )
    return normalized


class OpenAICompatiblePlannerLLM:
    """Small stdlib client for OpenAI-compatible chat-completions endpoints."""

    def complete(
        self,
        *,
        config: PlannerLLMConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if not config.enabled:
            raise PlannerLLMConfigurationError("Planner LLM config is disabled.")
        if not config.api_key:
            raise PlannerLLMConfigurationError("Planner LLM config is missing an API key.")
        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_output_tokens,
        }
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        for key, value in config.extra_headers:
            headers[key] = value
        request_url = _chat_completions_url(config.api_base_url)
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            request_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PlannerLLMTransportError(f"Planner provider HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise PlannerLLMTransportError(f"Planner provider request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise PlannerLLMTransportError("Planner provider request timed out.") from exc
        try:
            return _extract_message_content(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise PlannerLLMTransportError("Planner provider returned an unexpected response payload.") from exc


def _chat_completions_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload["choices"]
    if not isinstance(choices, list) or not choices:
        raise ValueError("No choices present")
    message = choices[0]["message"]
    content = message["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_segments = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text"}
        ]
        if text_segments:
            return "".join(text_segments)
    raise ValueError("Unsupported content payload")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise PlannerLLMConfigurationError(f"Invalid boolean value {value!r}.")


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PlannerLLMConfigurationError(f"Invalid float value {value!r}.") from exc


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PlannerLLMConfigurationError(f"Invalid integer value {value!r}.") from exc


def _normalize_extra_headers(raw_headers: Any) -> tuple[tuple[str, str], ...]:
    if raw_headers in (None, ""):
        return ()
    if isinstance(raw_headers, Mapping):
        return tuple((str(key), str(value)) for key, value in sorted(raw_headers.items()))
    normalized: list[tuple[str, str]] = []
    for entry in raw_headers:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise PlannerLLMConfigurationError("extra_headers entries must be two-item pairs.")
        normalized.append((str(entry[0]), str(entry[1])))
    normalized.sort()
    return tuple(normalized)

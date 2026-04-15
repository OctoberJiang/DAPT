"""Planner-side LLM provider configuration and OpenAI-compatible transport."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
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
class PlannerLLMUsage:
    """Provider-reported token usage for one completion call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class PlannerLLMPricing:
    """Repo-visible token pricing used for CNY cost accounting."""

    input_cost_cny_per_1k_tokens: float = 0.0
    output_cost_cny_per_1k_tokens: float = 0.0

    def estimate_cost_cny(self, usage: PlannerLLMUsage) -> float:
        input_cost = (usage.prompt_tokens / 1000.0) * self.input_cost_cny_per_1k_tokens
        output_cost = (usage.completion_tokens / 1000.0) * self.output_cost_cny_per_1k_tokens
        return round(input_cost + output_cost, 6)


@dataclass(frozen=True, slots=True)
class PlannerLLMCompletion:
    """One planner LLM completion plus optional usage metadata."""

    content: str
    usage: PlannerLLMUsage | None = None


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
    pricing: PlannerLLMPricing | None = None

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
    ) -> str | PlannerLLMCompletion:
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
        pricing=_normalize_pricing(raw, resolved_env),
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
    ) -> PlannerLLMCompletion:
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
            return PlannerLLMCompletion(
                content=_extract_message_content(payload),
                usage=_extract_usage(payload),
            )
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
    if isinstance(raw_headers, MappingABC):
        return tuple((str(key), str(value)) for key, value in sorted(raw_headers.items()))
    normalized: list[tuple[str, str]] = []
    for entry in raw_headers:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise PlannerLLMConfigurationError("extra_headers entries must be two-item pairs.")
        normalized.append((str(entry[0]), str(entry[1])))
    normalized.sort()
    return tuple(normalized)


def _normalize_pricing(raw: Mapping[str, Any], env: Mapping[str, str]) -> PlannerLLMPricing | None:
    pricing_payload = raw.get("pricing")
    if pricing_payload is None:
        input_value = raw.get(
            "input_cost_cny_per_1k_tokens",
            env.get("DAPT_PLANNER_INPUT_COST_CNY_PER_1K_TOKENS"),
        )
        output_value = raw.get(
            "output_cost_cny_per_1k_tokens",
            env.get("DAPT_PLANNER_OUTPUT_COST_CNY_PER_1K_TOKENS"),
        )
    else:
        if not isinstance(pricing_payload, MappingABC):
            raise PlannerLLMConfigurationError("pricing must be a mapping when provided.")
        input_value = pricing_payload.get("input_cost_cny_per_1k_tokens")
        output_value = pricing_payload.get("output_cost_cny_per_1k_tokens")

    if input_value in (None, "") and output_value in (None, ""):
        return None

    input_cost = _coerce_float(input_value if input_value not in (None, "") else 0.0)
    output_cost = _coerce_float(output_value if output_value not in (None, "") else 0.0)
    if input_cost < 0 or output_cost < 0:
        raise PlannerLLMConfigurationError("pricing values must be non-negative.")
    return PlannerLLMPricing(
        input_cost_cny_per_1k_tokens=input_cost,
        output_cost_cny_per_1k_tokens=output_cost,
    )


def _extract_usage(payload: dict[str, Any]) -> PlannerLLMUsage | None:
    usage_payload = payload.get("usage")
    if not isinstance(usage_payload, MappingABC):
        return None

    prompt_tokens = _coerce_optional_int(usage_payload.get("prompt_tokens"))
    completion_tokens = _coerce_optional_int(usage_payload.get("completion_tokens"))
    total_tokens = _coerce_optional_int(usage_payload.get("total_tokens"))
    if total_tokens is None:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    return PlannerLLMUsage(
        prompt_tokens=prompt_tokens or 0,
        completion_tokens=completion_tokens or 0,
        total_tokens=total_tokens,
    )


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return _coerce_int(value)

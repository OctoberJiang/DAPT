# 2_6_llm-driven-hypothesis-and-provider-config

## Status

Completed, implemented and awaiting audit.

## Goal

Replace the current rule-bounded planner hypothesis synthesis with an LLM-driven hypothesis generator that remains grounded in repo-local knowledge and current planner state, while allowing the user to configure the LLM provider and API credentials.

This sub-plan should make the planner capable of proposing broader attack paths than the current fixed playbook mapping, without abandoning the search-tree and dependency-graph discipline already implemented.

## Repo Facts

1. `src/dapt/planner/synthesis.py` currently generates candidates through deterministic rule mapping from observations to a bounded playbook set.
2. The user explicitly wants an LLM-driven hypothesis generator and configurable providers.
3. The allowed providers are: `deepseek`, `kimi`, `glm`, `qwen`, and `openai`.
4. `AGENTS.md` still requires repo-local inspectability and forbids hidden memory or external assumptions.
5. The current planner already has:
  - search-tree state,
  - dependency-graph state,
  - repo-local pentest knowledge retrieval,
  - deterministic candidate registration and scoring.

## Planned Work

- Define planner-side LLM contracts covering:
  - provider selection,
  - model configuration,
  - API credential sourcing,
  - prompt input shape,
  - structured hypothesis output shape,
  - failure and fallback behavior.
- Implement a provider abstraction layer supporting:
  - `deepseek`,
  - `kimi`,
  - `glm`,
  - `qwen`,
  - `openai`.
- Define how provider and credential configuration enters the system, including repo-visible config contracts and environment-variable boundaries.
- Replace or augment the current deterministic candidate synthesis with an LLM-driven generator that consumes:
  - recent observations,
  - dependency-graph state,
  - relevant repo-local knowledge hits,
  - current campaign objective and mode.
- Constrain the LLM output through typed parsing/validation so every generated hypothesis still has:
  - prerequisites,
  - expected effects,
  - action target,
  - supporting evidence references,
  - contradiction-sensitive fields.
- Persist hypothesis-generation prompts, structured outputs, and validation outcomes as repo-local planner artifacts so the reasoning remains auditable.
- Add deterministic tests for:
  - provider config normalization,
  - structured LLM output validation,
  - grounded candidate insertion into the tree and graph,
  - safe failure behavior when the model output is malformed or unavailable.

## Boundaries

- No hidden provider-specific prompt state.
- No unstructured free-form LLM output directly mutating planner state.
- No removal of the existing dependency-aware graph evaluation layer.
- No fallback to external knowledge sources outside the repo-local corpus unless separately planned later.

## Deliverables

- Provider/config contracts and runtime helpers.
- LLM-backed hypothesis-generation module under `src/dapt/planner/`.
- Repo-local planner artifacts for hypothesis-generation traces.
- Deterministic tests for provider handling and structured candidate generation.

## Dependencies

- Builds on `2_3_candidate-synthesis-and-graph-ingestion`.
- Should remain compatible with `2_4_dependency-aware-selection-and-execution-requests` and `2_5_planner-orchestration-loop-and-stop-conditions`.

## Implementation Notes

- Added planner-side LLM provider/config normalization and an OpenAI-compatible transport under `src/dapt/planner/llm.py`.
- Extended candidate synthesis to build grounded prompts from planner state plus repo-local knowledge excerpts, validate structured outputs, and persist per-observation hypothesis traces.
- Kept safe fallback to the prior deterministic synthesis path when the LLM is disabled, malformed, or unavailable.
- Added tests for config normalization, grounded LLM candidate validation, malformed-output fallback, and retained planner-runtime coverage.

## Audit Request

Please audit the implemented planner-side LLM synthesis, provider config boundaries, and hypothesis trace artifacts.

# 2_9_planner-budget-and-cost-control

## Status

Completed, awaiting user audit before any repository push.

## Goal

Add a repo-visible usage tracker and hard budget limits for planner sessions, including CNY-denominated LLM cost accounting and explicit stop behavior when configured limits are reached.

## Repo Facts

1. The planner owns session lifecycle, turn orchestration, and termination in `src/dapt/planner/service.py`.
2. The executor runs tools and skills and now reports usage metadata for real tool/skill invocations.
3. The planner LLM transport can now return generated text together with provider usage metadata.
4. `docs/references/mapta_cost_control_summary.md` recommends real-time usage tracking plus hard caps for time, tool calls, and token/cost.
5. Project rules in `AGENTS.md` require repo-local configuration and grounded behavior instead of external lookups or hidden assumptions.

## Planned Work

- Add typed planner-session budget and usage models that can track:
  - runtime seconds,
  - executor tool/skill invocations,
  - LLM prompt/completion token usage,
  - accumulated LLM monetary cost in CNY,
  - configured hard limits and limit-hit state.
- Extend the planner LLM layer so OpenAI-compatible responses can return both generated text and usage metadata, then compute CNY cost from repo-local pricing configuration instead of external pricing data.
- Add executor-side usage reporting for each execution request so the planner can aggregate tool-call count and execution elapsed time without inferring from artifacts after the fact.
- Persist budget snapshots as planner artifacts and include the current tracker state in session snapshots so budget decisions are auditable.
- Enforce hard limits in planner orchestration with an explicit termination path when a session exceeds configured budget caps.
- Cover the new behavior with deterministic tests for:
  - usage aggregation,
  - CNY cost calculation,
  - budget-limit termination,
  - persisted snapshot shape.

## Boundaries

- No external provider pricing lookup or currency conversion.
- No heuristic token estimation from prompt length when provider usage metadata is missing.
- No empirical early-stop policy in this slice beyond configured hard limits.

## Deliverables

- Typed budget and usage tracking contracts in the runtime code.
- Planner-session limit enforcement with an explicit budget-stop outcome.
- Repo-visible CNY pricing support for planner LLM accounting.
- Planner artifacts and tests that make cost-control behavior inspectable.

## Completed Work

- Added planner budget models in `src/dapt/planner/budget.py` for:
  - configurable hard limits,
  - cumulative runtime/tool/LLM usage tracking,
  - deterministic first-hit limit recording.
- Extended planner LLM contracts in `src/dapt/planner/llm.py` to support:
  - provider-reported token usage,
  - repo-visible CNY pricing,
  - structured completion payloads.
- Extended hypothesis synthesis tracing in `src/dapt/planner/synthesis.py` to persist:
  - prompt/completion token counts,
  - LLM latency,
  - computed CNY cost.
- Extended executor results in `src/dapt/executor/` to report:
  - real tool invocation counts,
  - elapsed execution time for tools and skills.
- Integrated planner-session budget tracking in `src/dapt/planner/service.py` so the planner:
  - records LLM usage during synthesis,
  - records executor usage after each action,
  - persists `budget.json`,
  - stops with `budget-limit-reached` when a configured cap is reached.
- Added deterministic tests covering:
  - executor usage accounting,
  - planner LLM pricing normalization,
  - synthesis trace cost recording,
  - planner stop behavior for tool-call and LLM-cost caps.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_planner`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_executor`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before any repository push.

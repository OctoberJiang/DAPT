# 1_1_perceptor-contracts-and-artifacts

## Status

Completed, awaiting user audit before any repository push.

## Goal

Define the Perceptor package layout and typed contracts required by:

- `AGENTS.md`
- `docs/design-docs/0_OVERALL_DESIGN.md`
- `docs/design-docs/1_ARCHITECTURE.md`
- `docs/references/pentestgpt_parsing_module_reference.md`

This sub-plan covers the Perceptor-side data model and storage conventions only. It does not implement planner reasoning, memory mutation logic, or LLM-backed summarization yet.

## Repo Facts

1. The executor already returns `ExecutionResult` objects and persists raw outputs under `artifacts/executor/`.
2. The repository does not yet contain a `src/dapt/perceptor/` package.
3. `docs/design-docs/4_MEMORY.md` is still a placeholder, so Perceptor memory work must stay append-only and forward-compatible.
4. `AGENTS.md` requires repo-local state and forbids hidden memory or external assumptions.

## Planned Work

- Create the base Perceptor package layout under `src/dapt/perceptor/`.
- Define core Perceptor models, likely including:
  - a perception input envelope rooted in executor outputs and artifacts,
  - source-type and artifact-type classifications,
  - chunk trace records for summarization,
  - planner-facing feedback objects,
  - append-only memory-entry candidates,
  - Perceptor artifact metadata.
- Define repo-local storage conventions for Perceptor outputs so planner feedback and memory staging stay inspectable in-repo.
- Define explicit boundaries between:
  - raw executor artifacts,
  - Perceptor summaries,
  - planner-consumable observations,
  - memory-ready append records.

## Boundaries

- No attack-path selection or planner-side hypothesis generation.
- No in-place mutation or rewriting of prior memory content.
- No concrete LLM runtime behavior beyond interfaces and contracts.

## Deliverables

- `src/dapt/perceptor/` package skeleton.
- Typed contracts and models for Perceptor inputs, summaries, and handoff outputs.
- Repo-local artifact naming and storage convention for Perceptor products.

## Dependencies

- Depends on `3_1_contracts-and-layout` and `3_2_executor-runtime`.
- Should land before `1_2_reference-aligned-parsing-runtime`.

## Completed Work

- Added a new `src/dapt/perceptor/` package.
- Added typed Perceptor-side models for:
  - executor-result ingestion,
  - parser prompts and config,
  - planner feedback,
  - append-only memory staging,
  - Perceptor-produced artifacts.
- Added a dedicated repo-local Perceptor artifact store rooted at `artifacts/perceptor/`.
- Added package exports so the Perceptor layer is importable alongside executor and knowledge.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before any repository push.

# 1_3_planner-feedback-and-memory-staging

## Status

Completed, awaiting user audit before any repository push.

## Goal

Define and implement the handoff from Perceptor summaries into planner-facing feedback and append-only memory staging, without overstepping into planner reasoning or a full mutable memory subsystem.

## Repo Facts

1. `docs/design-docs/1_ARCHITECTURE.md` assigns the Perceptor two outputs: planner feedback and memory writes.
2. `docs/design-docs/2_PLAN.md` expects the Planner to prune or extend paths based on Perceptor feedback.
3. `docs/design-docs/4_MEMORY.md` does not yet define a concrete memory model, so the Perceptor must stage memory-safe outputs rather than invent one implicitly.

## Planned Work

- Define a planner-feedback envelope that packages:
  - summarized observation text,
  - execution status,
  - evidence and artifact references,
  - extracted factual fields suitable for later planner reasoning.
- Define an append-only memory staging record for observations produced by the Perceptor.
- Persist planner-feedback and memory-staging artifacts in repo-local storage with clear provenance back to executor outputs.
- Document the contract boundary between:
  - executor raw results,
  - Perceptor summaries,
  - planner-consumable observations,
  - future memory-layer ingestion.

## Boundaries

- No search-tree pruning, node selection, or attack dependency updates inside the Perceptor.
- No deletion, overwrite, or retrospective editing of previously written memory content.
- No planner implementation bundled into the Perceptor handoff layer.

## Deliverables

- Planner-feedback model and serialization contract.
- Append-only memory-staging model and storage convention.
- Perceptor handoff wiring from parsing outputs into planner and memory-ready artifacts.

## Dependencies

- Depends on `1_1_perceptor-contracts-and-artifacts`.
- Should land after or alongside `1_2_reference-aligned-parsing-runtime`.
- Should stay forward-compatible with future `2_X_...` planner work and `4_X_...` memory work.

## Completed Work

- Added a planner-feedback envelope carrying:
  - summarized observation text,
  - execution status,
  - evidence fields,
  - source-artifact provenance.
- Added an append-only memory staging record that mirrors Perceptor observations without mutating prior state.
- Wired the Perceptor runtime to emit both planner feedback and memory-staging outputs on every perception run.
- Persisted planner-feedback and memory-staging artifacts under `artifacts/perceptor/` with provenance back to executor artifacts.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before any repository push.

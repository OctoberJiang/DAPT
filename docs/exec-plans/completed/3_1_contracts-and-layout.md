# 3_1_contracts-and-layout

## Status

Completed, awaiting user audit before `3_2_executor-runtime`.

## Goal

Define the executor package layout and the typed contracts required by:

- `AGENTS.md`
- `docs/design-docs/3_EXECUTION.md`
- `docs/references/pentestgpt_v2_tool_skill_layer.md`

This sub-plan covers the execution-side data model only. It does not implement planning logic, output summarization, or full tool coverage.

## Repo Facts

1. `DAPT/` is now the Git repository root.
2. `src/` no longer has a nested `.git/` directory.
3. `docs/design-docs/index.md` is still effectively empty and should be updated as work lands.
4. `docs/exec-plans/index.md` has been initialized and should be updated as plan state changes.

## Planned Work

- Create the base executor package layout under `src/`.
- Define core execution models:
  - planner-issued execution request,
  - tool spec,
  - skill spec,
  - execution result,
  - persisted artifact metadata.
- Define typed tool contracts aligned with the reference:
  - input schema,
  - validators,
  - preconditions,
  - executor function boundary,
  - output parser,
  - postconditions.
- Define skill contracts aligned with the reference:
  - goal,
  - required state,
  - preferred tools,
  - fallback tools,
  - step sequence,
  - result aggregation contract,
  - success conditions,
  - produced effects.
- Define a repo-local storage convention for raw execution outputs so the Perceptor can consume them later without hidden state.

## Boundaries

- No attack-path selection.
- No planning-level mutation.
- No output summarization.
- No broad tool inventory yet beyond what later proof plans need.

## Deliverables

- Executor package skeleton in `src/`.
- Contract and model definitions for tools, skills, requests, and results.
- Artifact storage path and naming convention.

## Completed Work

- Added a Python `src/` package layout rooted at `src/dapt/`.
- Added executor request, output, artifact, and result models.
- Added typed tool and skill contract definitions matching the design intent from the reference.
- Added a repo-local artifact storage helper rooted at `artifacts/executor/`.
- Initialized `artifacts/executor/` in the repository.
- Initialized `docs/design-docs/index.md`.

## Verification

- `python3 -m compileall src`

## Dependencies

- This plan should land before `3_2_executor-runtime` and `3_3_reference-aligned-proofs`.

## Audit Request

Please audit this completed sub-plan before implementation continues.

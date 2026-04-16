# 6_1_xbow-ctf-evaluation-runner

## Status

Completed, awaiting user audit before any repository push.

## Goal

Add the repo-local evaluation slice for CTF mode by wiring DAPT to run against XBOW benchmarks with user-selectable benchmark scope and benchmark-root path.

This slice should make the evaluation design operational without introducing hidden benchmark logic or external services.

## Repo Facts

1. `docs/design-docs/6_EVALUATION.md` now defines CTF-mode evaluation around XBOW benchmarks and explicitly requires benchmark selection by:
   - one benchmark number,
   - all benchmarks, or
   - an array of benchmark numbers.
2. `docs/design-docs/6_EVALUATION.md` also requires the benchmark directory path to be user-configurable, with a repo-local default when available.
3. `docs/references/XBOW-benchmark-readme.md` defines the benchmark structure, build/run expectations, and per-benchmark metadata such as:
   - `docker-compose.yml`,
   - `benchmark/benchmark-config.json`,
   - challenge name, description, level, and win condition.
4. The repository currently has no `src/dapt/evaluation/` package, no benchmark runner, and no user-facing evaluation entrypoint.
5. The planner already supports `ctf` objective mode, explicit flag-based success detection, repo-local artifact persistence, and budget-aware stop conditions.

## Planned Work

- Define typed evaluation contracts for:
  - benchmark selection,
  - benchmark discovery results,
  - one benchmark run request,
  - one benchmark run outcome,
  - aggregated evaluation summary.
- Add a repo-local benchmark discovery and validation layer that:
  - enumerates benchmarks from a selected root directory,
  - resolves one/all/list selection deterministically,
  - validates required benchmark metadata files before execution.
- Add an evaluation runtime that orchestrates each benchmark run by:
  - preparing benchmark-local lifecycle commands from repo-visible conventions,
  - resolving the target benchmark to a DAPT planner session,
  - running DAPT in `ctf` mode,
  - capturing run status, objective outcome, termination reason, and artifact references.
- Define a repo-visible target-resolution boundary for benchmarks so benchmark-specific connection details remain explicit and auditable rather than hidden in code paths.
- Persist evaluation artifacts and summaries under a dedicated repo-local layout so per-benchmark outcomes and aggregate results remain inspectable.
- Add a user-facing evaluation entrypoint that accepts:
  - benchmark selector mode,
  - benchmark ids where applicable,
  - benchmark root override,
  - any required DAPT runtime options needed for reproducible evaluation runs.
- Add deterministic tests covering:
  - selector parsing,
  - benchmark discovery and validation,
  - artifact snapshot shape,
  - command planning and planner handoff boundaries,
  - aggregate summary generation.

## Boundaries

- No external benchmark download or syncing.
- No live Docker-based benchmark execution in unit tests; command execution boundaries should be mocked or fixture-driven.
- No real-world evaluation framework in this slice until the design specifies datasets, targets, and win conditions for that mode.
- No hidden per-benchmark exploit heuristics outside repo-visible configuration or artifacts.

## Deliverables

- A new evaluation runtime under `src/dapt/evaluation/`.
- A repo-local evaluation entrypoint for running XBOW benchmark subsets.
- Repo-local evaluation artifacts and aggregate summaries for benchmark runs.
- Deterministic tests for selection, validation, orchestration boundaries, and result summarization.

## Dependencies

- Builds on `2_5_planner-orchestration-loop-and-stop-conditions`.
- Builds on `2_8_mode-aware-objectives-and-success-termination`.
- Builds on `2_9_planner-budget-and-cost-control`.
- Should remain compatible with future real-world evaluation work once that design is specified.

## Approval Gate

## Completed Work

- Added a new evaluation package under `src/dapt/evaluation/` with:
  - benchmark-selection contracts,
  - XBOW benchmark discovery and validation,
  - repo-visible target-resolution via `benchmark/dapt-target.json`,
  - lifecycle command execution boundaries,
  - aggregate evaluation summary models.
- Added repo-local evaluation artifact persistence under `artifacts/evaluation/`.
- Added a user-facing evaluation entrypoint via `python -m dapt.evaluation` that supports:
  - `all`,
  - one benchmark id,
  - comma-separated benchmark id lists,
  - benchmark-root override,
  - planner max-turn control,
  - optional lifecycle skipping.
- Added a deterministic local campaign runner path that builds the current planner/executor/perceptor stack without requiring hidden online dependencies.
- Added automated tests covering:
  - selector parsing,
  - zero-padded benchmark-id resolution,
  - per-benchmark lifecycle/result persistence,
  - aggregate summary persistence,
  - CLI output behavior.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_evaluation`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit the implemented XBOW evaluation contracts, benchmark target boundary, lifecycle orchestration, and persisted evaluation artifacts.

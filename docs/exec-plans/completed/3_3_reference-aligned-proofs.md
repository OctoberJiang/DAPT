# 3_3_reference-aligned-proofs

## Status

Completed, awaiting user audit before repository push.

## Goal

Prove the executor architecture with minimal but concrete reference-aligned implementations and tests.

## Planned Work

- Add at least one concrete typed tool adapter that exercises the tool contract system.
- Add at least one concrete skill that executes a multi-step procedure through the runtime.
- Use these proofs to validate the PentestGPT-v2-inspired tool/skill split rather than to maximize tool coverage.
- Add automated tests for:
  - input validation,
  - precondition enforcement,
  - retry behavior,
  - raw artifact persistence,
  - skill step execution,
  - failure propagation.
- Update `docs/exec-plans/index.md` and any relevant design indexes once implementation work completes.

## Boundaries

- Minimal proof coverage only.
- No attempt to implement the full paper’s tool inventory at this stage.

## Deliverables

- One or more concrete tool adapters.
- One or more concrete skills.
- Test coverage for executor behavior.
- Updated plan and design indexes after implementation.

## Completed Work

- Added a concrete typed tool adapter, `run-local-command`, built on structured subprocess execution.
- Added a concrete multi-step skill, `workspace-recon`, built from tool invocations through the executor runtime.
- Added a registry helper that registers the proof tool and skill together.
- Added automated `unittest` coverage for:
  - input validation,
  - precondition enforcement,
  - retry behavior,
  - raw artifact persistence,
  - successful skill execution,
  - skill failure propagation.
- Added a repository `.gitignore` so generated cache files and local-only files are not pushed.

## Verification

- `python3 -m compileall src tests`
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Dependencies

- Depends on `3_1_contracts-and-layout`.
- Depends on `3_2_executor-runtime`.

## Audit Request

Please audit this completed sub-plan before repository push.

# 7_1_structured-report-generation

## Status

Completed, awaiting user audit before any repository push.

## Goal

Add the final report slice so DAPT can turn repo-local campaign artifacts into a structured deliverable with user-selectable output format and output path.

This slice should make the final-output contract concrete while keeping every reported claim traceable back to repo-local evidence.

## Repo Facts

1. `docs/design-docs/7_REPORT.md` now requires a structured final report that includes vulnerabilities, the complete attack chain, severity, and related findings.
2. `docs/design-docs/7_REPORT.md` also requires the user to be able to choose:
   - the report file format, and
   - the path where the report is stored.
3. `docs/design-docs/0_OVERALL_DESIGN.md` defines the system output as the complete exploit path and the report.
4. The planner already persists rich repo-local artifacts, including:
   - search-tree snapshots,
   - dependency-graph snapshots,
   - candidate rankings,
   - turn records,
   - objective progress,
   - budget state.
5. The repository currently has no report package, no formatter abstraction, and no user-facing report-generation entrypoint.

## Planned Work

- Define typed report contracts covering:
  - campaign metadata,
  - findings,
  - evidence references,
  - attack-chain steps,
  - severity values,
  - formatter output metadata.
- Add a report-assembly layer that loads planner, perceptor, executor, and memory artifacts for one session and converts them into a normalized report model.
- Define a deterministic finding-extraction boundary so reported vulnerabilities and attack-chain steps are grounded in:
  - planner observations,
  - candidate/effect state,
  - execution outputs,
  - persisted artifact references.
- Define a repo-visible severity contract for the first report slice so severity labels are explicit and auditable rather than implied by hidden heuristics.
- Add formatter support for user-selectable report output, with at least:
  - one machine-readable format, and
  - one human-readable format.
- Add a user-facing report entrypoint that accepts:
  - the target session or artifact set,
  - the output format,
  - the output path.
- Persist report outputs in a predictable repo-local default location when the user does not override the path.
- Add deterministic tests covering:
  - report-model assembly from stored artifacts,
  - attack-chain ordering,
  - evidence-reference preservation,
  - format selection,
  - rendered output shape.

## Boundaries

- No external CVE enrichment, vulnerability lookups, or hosted severity services.
- No hidden narrative synthesis that cannot be traced back to repo-local artifacts.
- No assumption that every session has a successful exploit chain; the report layer must also support incomplete or failed campaigns.
- No high-fidelity office/PDF publishing requirements in the first slice unless they are directly required by the chosen formatter set.

## Deliverables

- A new report runtime under `src/dapt/report/`.
- A normalized structured report model assembled from repo-local artifacts.
- User-selectable report rendering and output-path control.
- Deterministic tests for report assembly, formatting, and artifact-backed evidence preservation.

## Dependencies

- Builds on `2_5_planner-orchestration-loop-and-stop-conditions`.
- Builds on `4_1_structured-and-retrieval-memory`.
- Should remain compatible with future evaluation outputs so benchmark runs can emit reports through the same contract.

## Approval Gate

## Completed Work

- Added a new report package under `src/dapt/report/` with:
  - normalized report models,
  - planner-session artifact loading,
  - deterministic finding extraction,
  - attack-chain assembly,
  - JSON and Markdown rendering.
- Added repo-local report persistence under `artifacts/report/`.
- Added a user-facing report entrypoint via `python -m dapt.report` with:
  - session-directory selection,
  - format selection,
  - optional output-path override.
- Implemented a first-pass explicit severity contract based on repo-visible target/action categories rather than hidden enrichment.
- Added automated tests covering:
  - report assembly from real planner artifacts,
  - machine-readable and human-readable rendering,
  - CLI-backed default output generation.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_report`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit the implemented report assembly rules, severity contract, renderers, and artifact-backed evidence preservation.

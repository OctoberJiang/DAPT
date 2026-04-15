# 3_5_recon-web-skills

## Status

Completed, awaiting user audit before `3_6_credential-ad-privesc-catalog`.

## Goal

Implement reusable reconnaissance and web-exploitation skills on top of the typed tool catalog so the planner can delegate standard attack procedures instead of only isolated tool invocations.

## Repo Facts

1. The runtime already supports multi-step `SkillSpec` execution with per-step failure handling.
2. The only current concrete skill is the proof-only `workspace-recon`.
3. The PentestGPT-v2 reference explicitly separates tool wrappers from higher-level reusable skills.
4. The planned tool adapters in `3_4_cli-pentest-tool-catalog` are the minimum foundation for the first real pentest skills.

## Planned Work

- Add a dedicated skill package under `src/dapt/executor/` for pentest procedures.
- Implement concrete skills for the first web-focused operating set:
  - `service-enumeration` to run targeted port/service discovery and normalize scan artifacts,
  - `web-surface-mapping` to confirm HTTP exposure and collect baseline scan outputs,
  - `content-discovery` to enumerate paths or vhosts with fallback from `gobuster` to `ffuf`,
  - `sqli-verification` to run a constrained SQL injection validation workflow around `sqlmap`.
- For each skill, define:
  - required context state,
  - preferred tools and fallback tools,
  - step sequence and per-step preconditions,
  - success conditions,
  - produced effects for downstream planner/perceptor consumption.
- Add result aggregators that combine step-level outputs into structured skill effects without replacing the raw artifacts.
- Add automated tests for:
  - required-state enforcement,
  - step ordering,
  - fallback behavior,
  - stop-vs-continue failure policy,
  - aggregate effect construction.

## Boundaries

- No credential, Active Directory, or privilege-escalation workflows in this plan.
- No planner-driven dynamic branch selection inside the skill layer.
- No exploit execution beyond constrained validation and surface mapping.

## Deliverables

- A web-focused skill library with concrete multi-step procedures.
- Skill registry wiring and execution tests.
- Structured skill effect outputs aligned with the existing executor result model.

## Dependencies

- Depends on `3_4_cli-pentest-tool-catalog`.
- Builds on `3_2_executor-runtime` skill execution semantics.
- Can share reference patterns from `3_3_reference-aligned-proofs`.

## Completed Work

- Extended the skill runtime with structured step records and conditional step execution so skills can support:
  - guarded follow-up steps,
  - fallback paths,
  - clearer aggregated effects.
- Added a dedicated pentest skill package under `src/dapt/executor/pentest/skills/`.
- Implemented concrete web-focused skills for:
  - `service-enumeration`,
  - `web-surface-mapping`,
  - `content-discovery`,
  - `sqli-verification`.
- Added pentest skill registry wiring and a combined pentest registry builder for tool-plus-skill execution.
- Added automated tests covering:
  - required-state enforcement,
  - step ordering,
  - conditional execution,
  - fallback behavior,
  - stop-vs-continue failure policy,
  - aggregate effect construction.
- Improved executor normalization so optional parameters set to `None` are treated as absent instead of failing type checks.
- Improved skill failure handling so missing required context now returns a failed `ExecutionResult` with persisted artifacts instead of raising directly.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_executor`

## Audit Request

Please audit this completed sub-plan before `3_6_credential-ad-privesc-catalog` starts.

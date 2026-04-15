# 2_7_recon-bootstrap-from-minimal-input

## Status

Completed, implemented and awaiting audit.

## Goal

Make the planner capable of starting from nothing but a target URL and autonomously bootstrapping the missing context it needs through reconnaissance and iterative state collection.

This sub-plan should remove the current practical dependence on pre-supplied context such as host, wordlists, credentials, platform hints, or service metadata.

## Repo Facts

1. The user explicitly wants the target URL to be sufficient input.
2. The current planner works best when additional context is already present in `initial_context`.
3. The repo already has executor-side recon and web skills that can serve as early bootstrap actions:
  - `service-enumeration`,
  - `web-surface-mapping`,
  - `content-discovery`,
  - related supporting tools such as `nmap`, `gobuster`, `ffuf`, and `zap-baseline`.
4. The current planner session state can accumulate evidence and inferred conditions, but it does not yet own a bootstrap policy for acquiring missing context.

## Planned Work

- Define a bootstrap-planning contract for campaigns that begin with only:
  - target URL,
  - selected objective mode,
  - optional user-supplied overrides.
- Implement planner logic for identifying missing required context and scheduling bootstrap reconnaissance to acquire it instead of assuming it exists.
- Define deterministic state-derivation rules for early recon outputs, including:
  - hostname extraction,
  - target host resolution boundaries,
  - HTTP exposure confirmation,
  - candidate parameter discovery,
  - default wordlist/resource selection policy.
- Extend candidate generation and selection so bootstrap recon candidates are:
  - automatically introduced when context is missing,
  - de-prioritized once the missing state has been collected,
  - not repeatedly reissued without new evidence.
- Persist planner artifacts showing:
  - missing-state analysis,
  - bootstrap candidate creation,
  - newly satisfied bootstrap conditions.
- Add deterministic tests covering:
  - start-from-URL-only initialization,
  - recon-first planning behavior,
  - state acquisition from recon outputs,
  - duplicate-bootstrap suppression.

## Boundaries

- No implicit network discovery outside the current executor tool/skill catalog.
- No hidden global defaults that are not captured in planner artifacts or config.
- No credentials or platform assumptions before evidence supports them.

## Deliverables

- Bootstrap context and missing-state contracts.
- Planner runtime updates for recon-first autonomous initialization.
- Deterministic tests for URL-only campaign startup and bootstrap progression.

## Dependencies

- Builds on `2_5_planner-orchestration-loop-and-stop-conditions`.
- Should remain compatible with `2_6_llm-driven-hypothesis-and-provider-config`.

## Implementation Notes

- Added a planner bootstrap policy that derives `target_host` from the URL, assigns a repo-local default wordlist, and records missing-state analysis.
- Persisted bootstrap-analysis artifacts at session start and per synthesized observation so recon-first initialization stays inspectable.
- Added a repo-local bootstrap wordlist under `docs/references/pentest/wordlists/`.
- Extended planner tests to cover URL-only startup, recon-first execution, and bootstrap artifact persistence.

## Audit Request

Please audit the implemented URL-first bootstrap policy, repo-local default resource boundary, and bootstrap-analysis artifacts.

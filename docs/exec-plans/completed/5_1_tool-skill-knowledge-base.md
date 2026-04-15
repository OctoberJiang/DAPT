# 5_1_tool-skill-knowledge-base

## Status

Completed, awaiting user audit before any repository push.

## Goal

Create the repo-local knowledge layer that supports the planned pentest tool and skill catalog with grounded operational references instead of hidden assumptions.

## Repo Facts

1. `docs/design-docs/5_KNOWLEDGE.md` is still only a placeholder.
2. `docs/references/` currently contains only the PentestGPT-v2 tool/skill layer summary.
3. The project rules in `AGENTS.md` require repo-local knowledge rather than unstated memory or external assumptions.
4. The PentestGPT-v2 reference explicitly treats tool documentation, exploit knowledge, and attack playbooks as part of the tool/skill layer.

## Planned Work

- Define a repo-local knowledge layout for executor-facing operational references, likely split into:
  - tool notes,
  - attack playbooks,
  - exploit or version-match notes.
- Add structured knowledge entries for the planned concrete tool catalog, including:
  - safe/default flag guidance,
  - required inputs and common pitfalls,
  - expected output signatures,
  - environment assumptions and dependencies.
- Add playbooks aligned with the planned concrete skills, including:
  - web surface mapping,
  - content discovery,
  - SQL injection verification,
  - password spraying,
  - Kerberos roasting,
  - local privilege-escalation enumeration.
- Define the retrieval contract that the planner and executor can eventually use to ask grounded questions such as:
  - which tool fits a goal,
  - what parameters are required,
  - what prerequisites or caveats apply.
- Add tests or validation scripts for knowledge entry shape and index consistency.

## Boundaries

- No external vector database or hosted retrieval service in this phase.
- No automatic syncing from the public internet.
- No attempt to implement planner reasoning inside the knowledge layer.

## Deliverables

- A repo-local knowledge corpus structure under `docs/references/` and/or `src/`.
- Initial tool notes and attack playbooks for the planned executor catalog.
- A documented retrieval contract for later planner/executor integration.

## Dependencies

- Should be planned alongside `3_4_cli-pentest-tool-catalog`.
- Should remain aligned with the concrete skills in `3_5_recon-web-skills` and `3_6_credential-ad-privesc-catalog`.

## Completed Work

- Added a repo-local knowledge corpus under `docs/references/pentest/` with:
  - `manifest.json`,
  - `index.md`,
  - `retrieval-contract.md`,
  - tool-note indexes and per-tool notes,
  - playbook indexes and per-skill playbooks,
  - an exploit-note file for shared version and artifact signatures.
- Added a lightweight typed knowledge loader under `src/dapt/knowledge/` so later runtime code can consume the manifest directly.
- Added structured tool notes for every currently implemented pentest tool:
  - web and recon tools,
  - credential tools,
  - Active Directory and Kerberos tools,
  - privilege-escalation enumeration tools.
- Added structured playbooks for every currently implemented pentest skill:
  - web-focused procedures,
  - credential validation procedures,
  - Kerberos roast collection procedures,
  - local privilege-escalation enumeration.
- Added automated validation tests that ensure:
  - manifest documents exist,
  - retrieval contract exists,
  - every registered pentest tool has a tool note,
  - every registered pentest skill has a playbook,
  - related tool and skill references stay consistent with the executor registry.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test*.py'`

## Audit Request

Please audit this completed sub-plan before any repository push.

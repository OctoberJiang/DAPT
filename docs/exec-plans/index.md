# Execution Plans Index

## Active

## Failed

- `8_3_run-xbow-benchmark-1-and-fix-runtime-issues`: repo-local evaluation/runtime issues were fixed, but the benchmark run remains blocked because the planner process cannot see `DAPT_PLANNER_API_KEY` in the agent-visible environment.

## Completed

- `1_1_perceptor-contracts-and-artifacts`: audited and completed Perceptor package layout, typed contracts, and repo-local artifact conventions.
- `1_2_reference-aligned-parsing-runtime`: audited and completed reference-aligned parsing runtime for executor raw outputs.
- `1_3_planner-feedback-and-memory-staging`: audited and completed planner feedback and append-only memory staging flow.
- `1_4_perceptor-reference-aligned-proofs`: audited and completed deterministic Perceptor tests and proof fixtures.
- `2_1_search-tree-contracts-and-state`: audited and completed planner search-tree contracts, transitions, Perceptor-feedback ingestion, and repo-local state snapshots.
- `2_2_attack-dependency-graph-and-candidate-evaluation`: audited and completed dependency-graph models, deterministic candidate scoring, and planner ranking snapshots.
- `2_3_candidate-synthesis-and-graph-ingestion`: audited and completed grounded observation-to-hypothesis synthesis, graph ingestion, and deduplicated candidate generation.
- `2_4_dependency-aware-selection-and-execution-requests`: audited and completed deterministic candidate selection, action-node creation, and planner-to-executor request emission.
- `2_5_planner-orchestration-loop-and-stop-conditions`: audited and completed top-level planner runtime, stop conditions, and end-to-end orchestration.
- `2_6_llm-driven-hypothesis-and-provider-config`: audited and completed LLM-backed hypothesis generation, provider/config normalization, auditable hypothesis traces, and deterministic validation/fallback tests.
- `2_7_recon-bootstrap-from-minimal-input`: audited and completed URL-only planner startup, repo-local bootstrap defaults, recon-first missing-state analysis, and deterministic bootstrap tests.
- `2_8_mode-aware-objectives-and-success-termination`: audited and completed objective-mode contracts, explicit CTF/root success tracking, objective-progress artifacts, and deterministic objective-aware termination tests.
- `2_9_planner-budget-and-cost-control`: audited and completed planner-session budget tracking, CNY-denominated LLM cost accounting, hard budget-stop limits, and deterministic budget tests.
- `3_1_contracts-and-layout`: audited and completed executor package layout, typed contracts, and artifact storage conventions.
- `3_2_executor-runtime`: audited and completed executor dispatch, retry policy, and raw-output persistence.
- `3_3_reference-aligned-proofs`: audited and completed concrete tool/skill proofs and executor tests.
- `3_4_cli-pentest-tool-catalog`: audited and completed typed pentest tool adapters, shared CLI helpers, and catalog tests.
- `3_5_recon-web-skills`: audited and completed reusable reconnaissance and web-exploitation skills.
- `3_6_credential-ad-privesc-catalog`: audited and completed credential, AD, and privilege-escalation tools and skills.
- `4_1_structured-and-retrieval-memory`: audited and completed structured planner memory, retrieval indexing, planner/Perceptor ingestion, and deterministic memory tests.
- `5_1_tool-skill-knowledge-base`: audited and completed repo-local tool notes, playbooks, retrieval contract, and manifest validation.
- `6_1_xbow-ctf-evaluation-runner`: audited and completed repo-local XBOW benchmark discovery, selection, lifecycle orchestration, and evaluation artifact generation.
- `6_2_ctf-benchmark-metadata-planner-bootstrap`: completed explicit XBOW benchmark-metadata handoff into CTF planner bootstrap and surfaced the metadata in the initial planner prompt.
- `7_1_structured-report-generation`: audited and completed repo-local finding extraction, attack-chain summarization, format-specific rendering, and output-path selection.
- `8_1_audit-closeout-and-runbook-alignment`: audited and completed audit closeout for exec-plan documents and index alignment.
- `8_2_mutable-runtime-configuration`: audited and completed repo-visible mutable runtime configuration, evaluation/report config loading, and planner budget wiring.
- `8_4_executor-tool-fallbacks-for-missing-binaries`: completed bounded repo-local native fallbacks for missing recon binaries, benchmark-style dynamic-port web recon, and executor regression coverage.
- `8_5_rerun-benchmark-01-evaluation`: completed a fresh benchmark-01 rerun, confirmed the former API-key blocker is gone, and captured the new frontier-blocked campaign artifacts.
- `8_6_rerun-benchmark-01-and-inspect-final-output`: completed a fresh benchmark-01 rerun, captured both sandbox-blocked and escalated outcomes, and inspected the final frontier-blocked planner output.
- `8_7_trace-benchmark-01-frontier-block`: completed a cross-layer trace of the benchmark-01 frontier block and identified the primary planner/perceptor and secondary executor fix points.
- `8_8_primary-fix-sqli-candidate-reconstruction`: completed the planner/perceptor SQLi-candidate reconstruction fix so relative web-path discoveries now yield executable SQLi verification targets.
- `8_9_rerun-benchmark-01-after-sqli-candidate-fix`: completed a post-fix benchmark-01 rerun and confirmed the planner now executes SQLi verification before stopping on missing `sqlmap` and no further actionable candidates.

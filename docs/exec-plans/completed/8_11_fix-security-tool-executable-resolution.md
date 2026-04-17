# 8_11_fix-security-tool-executable-resolution

## Status

Completed.

## Goal

Fix the repo-wide pentest executable resolution model so DAPT no longer depends on a single hardcoded PATH name per security tool, and so benchmark/runtime failures surface the real underlying availability problem instead of a brittle `Executable not found` check.

## Repo Facts

1. The original non-recon tool adapters hard-required `require_executable_exists()` in `src/dapt/executor/pentest/cli.py`, which only checked one literal executable name through `shutil.which(...)`.
2. The executor already supports per-tool `default_parameters`, so repo-visible command overrides can be injected without changing planner contracts.
3. The evaluation runtime executes pentest tools on the controller host, not inside the benchmark target container, so controller-host resolution and controller-host platform are both material.
4. Local debugging on April 17, 2026 showed multiple distinct root causes behind the same `Executable not found` symptom:
   - several tools were genuinely absent from controller-host `PATH`,
   - several tools existed under alternate names (`sqlmap.py`, `nxc`, Impacket entrypoints),
   - several tools were installed repo-locally and needed extra runtime environment (`NXC_PATH`, `GEM_HOME`),
   - `linpeas` and `winpeas` are not ordinary controller-host binaries on this macOS host; their real issue is host/platform mismatch, not just PATH.
5. The fresh benchmark-01 rerun before the fix stopped at `sqli-verification` with `Executable not found on PATH: sqlmap`.

## Completed Work

- Added repo-visible pentest command configuration to `src/dapt/config.py` and `dapt.config.json`.
- Added a centralized pentest command resolver in `src/dapt/executor/pentest/cli.py` that now:
  - supports alias candidates per tool,
  - supports repo-configured command prefixes,
  - resolves repo-relative command paths,
  - emits explicit checked-candidate diagnostics when nothing is runnable.
- Updated `src/dapt/executor/pentest/registry.py` to inject per-tool configured commands from repo config and to normalize env-prefixed command tokens such as:
  - `env NXC_PATH=./.nxc .venv-tools/bin/netexec`
  - `env GEM_HOME=./.gem-tools .gem-tools/bin/evil-winrm`
- Applied the resolver across all registered security tools, including:
  - `sqlmap`
  - `hydra`
  - `john`
  - `netexec`
  - `evil-winrm`
  - `kerbrute`
  - `impacket-getnpusers`
  - `impacket-getuserspns`
  - `linpeas`
  - `winpeas`
- Tightened runtime diagnostics so host-incompatible binaries now fail with a concrete non-retryable reason instead of a generic retryable `OSError`.
- Added controller-host platform checks for `linpeas` and `winpeas` so they no longer misreport as PATH failures on this macOS controller host.
- Added regression coverage in `tests/test_config.py` and `tests/test_executor.py` for:
  - repo-visible tool command parsing,
  - alias fallback (`sqlmap` -> `sqlmap.py`),
  - env-prefixed configured commands,
  - clearer missing-executable messages,
  - host-platform mismatch handling for `winpeas`,
  - non-retryable reporting for host-incompatible binaries.
- Provisioned the controller host so the current repo config has runnable commands for the security-tool catalog where controller-host execution is valid:
  - Homebrew: `sqlmap`, `hydra`, `john`, `nmap`, `ffuf`, `gobuster`, `ruby`, `go`
  - repo-local venv: `netexec`, `GetNPUsers.py`, `GetUserSPNs.py`
  - repo-local gem: `evil-winrm`
  - repo-local Go build: `kerbrute`
- Updated `dapt.config.json` so repo-local commands are wired for:
  - `netexec`
  - `evil-winrm`
  - `kerbrute`
  - `impacket-getnpusers`
  - `impacket-getuserspns`

## Boundaries

- No revert of unrelated workspace changes.
- No false claim that a tool exists when the machine truly lacks a valid controller-host execution path.

## Outcome

- The original `sqlmap` blocker is fixed. Benchmark 01 no longer stops on `Executable not found` for `sqlmap`.
- The post-fix rerun `eval-20260417-bench-1-after-sqlmap-install-escalated` completed the `sqlmap` step successfully and still failed overall only because the planner chose the wrong candidate URL and then exhausted its frontier:
  - top-level result: `status: failed`
  - `objective_met: false`
  - `termination_reason: no-actionable-candidates`
  - `turn_count: 5`
- The rerun’s `sqlmap` artifact confirms the executable-resolution fix worked:
  - command: `/opt/homebrew/bin/sqlmap -u https://nmap.org/submit/ --level 1 --risk 1 --batch`
  - tool step status: `succeeded`
  - vulnerability result: `vulnerable: false`
- The real remaining issue in benchmark 01 is now planner targeting quality, not missing `sqlmap`.
- Current tool-resolution status after the fix:
  - Controller-host runnable through PATH or repo config:
    - `nmap`
    - `gobuster`
    - `ffuf`
    - `sqlmap`
    - `hydra`
    - `john`
    - `netexec`
    - `evil-winrm`
    - `kerbrute`
    - `impacket-getnpusers`
    - `impacket-getuserspns`
  - Handled through existing native fallback instead of controller-host binary:
    - `zap-baseline`
  - No longer misreported as PATH failures; now rejected for the real reason on this controller host:
    - `linpeas`
    - `winpeas`

## Dependencies

- Builds on `3_4_cli-pentest-tool-catalog`.
- Builds on `8_2_mutable-runtime-configuration`.
- Builds on `8_4_executor-tool-fallbacks-for-missing-binaries`.
- Informed by `8_10_audit-tool-executables-on-path`.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_config tests.test_executor tests.test_evaluation tests.test_report`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m dapt.evaluation --benchmarks 1 --run-id eval-20260417-bench-1-after-sqlmap-install-escalated`
- Manual command-path checks on this host:
  - `which sqlmap hydra john nmap ffuf gobuster`
  - `./.go-tools/bin/kerbrute --help`
  - `./.venv-tools/bin/GetNPUsers.py -h`
  - `./.venv-tools/bin/GetUserSPNs.py -h`

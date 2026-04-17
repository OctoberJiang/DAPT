# 8_10_audit-tool-executables-on-path

## Status

Completed.

## Goal

Audit the repo-visible pentest tool catalog and verify whether each configured executable can actually be resolved on the current machine `PATH`.

## Repo Facts

1. The pentest tool registry in `src/dapt/executor/pentest/registry.py` registers these repo-visible tools:
   - `nmap`
   - `gobuster`
   - `ffuf`
   - `sqlmap`
   - `zap-baseline`
   - `hydra`
   - `john`
   - `netexec`
   - `evil-winrm`
   - `kerbrute`
   - `impacket-getnpusers`
   - `impacket-getuserspns`
   - `linpeas`
   - `winpeas`
2. PATH resolution currently flows through `resolve_executable(...)` in `src/dapt/executor/pentest/cli.py`, which wraps `shutil.which(...)`.
3. Several recon tools already have bounded repo-local native fallbacks from `8_4_executor-tool-fallbacks-for-missing-binaries`, so a missing executable is not equally severe for every tool.
4. `sqlmap` still hard-requires a PATH-visible executable, and the latest benchmark-01 rerun showed `Executable not found on PATH: sqlmap`.
5. The current worktree contains many unrelated local modifications and generated artifacts, so this audit should avoid reverting or folding in unrelated changes.

## Planned Work

- Enumerate the registered pentest tools from repo-local code.
- Resolve the default executable name for each tool from its input schema/defaults.
- Check each executable against the current shell `PATH`.
- Produce a repo-local audit summary that distinguishes:
  - executable found,
  - executable missing but tool has a native fallback,
  - executable missing and tool will hard-fail.
- Record the audit in this plan and move it to `completed` or `failed`.
- Update `docs/exec-plans/index.md`.
- Commit and push only the exec-plan bookkeeping changes.

## Boundaries

- No code changes in this slice unless a follow-up task is explicitly requested.
- No package installation in this slice.
- Do not revert unrelated local changes.

## Deliverables

- A repo-local PATH audit for all registered pentest executables.
- A clear list of missing executables that currently block planner-executed skills.

## Dependencies

- Builds on `3_4_cli-pentest-tool-catalog`.
- Builds on `8_4_executor-tool-fallbacks-for-missing-binaries`.
- Informed by `8_9_rerun-benchmark-01-after-sqli-candidate-fix`.

## Completed Work

- Confirmed the repo-visible pentest tool registry in `src/dapt/executor/pentest/registry.py` still exposes 14 tools:
  - `nmap`
  - `gobuster`
  - `ffuf`
  - `sqlmap`
  - `zap-baseline`
  - `hydra`
  - `john`
  - `netexec`
  - `evil-winrm`
  - `kerbrute`
  - `impacket-getnpusers`
  - `impacket-getuserspns`
  - `linpeas`
  - `winpeas`
- Confirmed each tool's default executable name from its typed input schema in `src/dapt/executor/pentest/tools/`.
- Resolved every default executable against the current shell `PATH` using the same mechanism the repo uses at runtime:
  - `resolve_executable(...)` in `src/dapt/executor/pentest/cli.py`
  - `shutil.which(...)`
- Confirmed that all 14 default executables are currently missing from the agent-visible `PATH`.
- Classified each missing executable by observed runtime behavior:

| Tool | Default executable | PATH result | Runtime behavior when missing |
| --- | --- | --- | --- |
| `nmap` | `nmap` | missing | repo-local native fallback available |
| `gobuster` | `gobuster` | missing | repo-local native fallback for `dir` mode only; `vhost` enumeration is degraded |
| `ffuf` | `ffuf` | missing | repo-local native fallback available |
| `sqlmap` | `sqlmap` | missing | hard-fails with `Executable not found on PATH` |
| `zap-baseline` | `zap-baseline.py` | missing | repo-local native fallback available |
| `hydra` | `hydra` | missing | hard-fails with `Executable not found on PATH` |
| `john` | `john` | missing | hard-fails with `Executable not found on PATH` |
| `netexec` | `netexec` | missing | hard-fails with `Executable not found on PATH` |
| `evil-winrm` | `evil-winrm` | missing | hard-fails with `Executable not found on PATH` |
| `kerbrute` | `kerbrute` | missing | hard-fails with `Executable not found on PATH` |
| `impacket-getnpusers` | `GetNPUsers.py` | missing | hard-fails with `Executable not found on PATH` |
| `impacket-getuserspns` | `GetUserSPNs.py` | missing | hard-fails with `Executable not found on PATH` |
| `linpeas` | `linpeas.sh` | missing | hard-fails with `Executable not found on PATH` |
| `winpeas` | `winpeas.exe` | missing | hard-fails with `Executable not found on PATH` |

## Outcome

- Current web recon remains runnable on this machine despite missing binaries:
  - `service-enumeration` can still execute via the native `nmap` fallback.
  - `web-surface-mapping` can still execute via the native `nmap` and `zap-baseline` fallbacks.
  - `content-discovery` in `dir` mode can still execute via native `gobuster` behavior and the existing `ffuf` fallback path.
- Current planner-executed skill paths that are blocked by missing executables:
  - `sqli-verification` is blocked by missing `sqlmap`; this matches the benchmark-01 failure recorded in `8_9_rerun-benchmark-01-after-sqli-candidate-fix`.
  - `password-spray-validation` is blocked by missing `hydra`.
  - `credential-reuse-check` is blocked by missing `netexec`; the `winrm` follow-up path is also unavailable because `evil-winrm` is missing.
  - `asrep-roast-collection` loses its best-effort `kerbrute` enumeration step and is blocked on the required `GetNPUsers.py` step.
  - `kerberoast-collection` is blocked by missing `netexec` and `GetUserSPNs.py`.
  - `local-privesc-enum` is blocked on whichever platform-specific PEAS executable would be selected at runtime.
- `john` is also missing, but it is not currently referenced by a registered pentest skill; the impact is limited to direct tool execution until a skill uses it.

## Verification

- `python3 - <<'PY'`
  `import shutil`
  `for executable in ("nmap", "gobuster", "ffuf", "sqlmap", "zap-baseline.py", "hydra", "john", "netexec", "evil-winrm", "kerbrute", "GetNPUsers.py", "GetUserSPNs.py", "linpeas.sh", "winpeas.exe"):`
  `    print(executable, shutil.which(executable) or "MISSING")`
  `PY`

# 3_6_credential-ad-privesc-catalog

## Status

Completed, awaiting user audit before `5_1_tool-skill-knowledge-base`.

## Goal

Extend the tool and skill layer beyond web workflows into credential attacks, Active Directory operations, and local privilege-escalation enumeration using typed, auditable executor contracts.

## Repo Facts

1. The current executor code does not yet expose any credential, Windows, or AD-specific tool adapters.
2. The PentestGPT-v2 reference treats credential attacks, Active Directory attacks, and privilege escalation as first-class tool categories.
3. These areas introduce additional artifact shapes such as recovered hashes, loot files, and host-specific execution metadata.
4. Some representative reference tools are OS- or environment-sensitive, so the first implementation pass should stay CLI-first and explicitly bounded.

## Planned Work

- Add concrete typed tool adapters for a first credential/AD/privesc slice:
  - `hydra` for credential validation and password spraying,
  - `john` and/or `hashcat` for offline cracking workflows,
  - `netexec` or `crackmapexec` for authenticated service checks,
  - `evil-winrm` for WinRM session establishment checks,
  - selected `impacket` entrypoints for remote AD-related operations,
  - `kerbrute` for username and Kerberos pre-auth probing,
  - `linpeas` and `winpeas` for local privilege-escalation enumeration.
- Add concrete skills built from those tools:
  - `password-spray-validation`,
  - `credential-reuse-check`,
  - `asrep-roast-collection`,
  - `kerberoast-collection`,
  - `local-privesc-enum`.
- Extend artifact handling expectations for:
  - recovered credential material,
  - enumeration loot,
  - tool-specific structured metadata.
- Add tests for:
  - high-risk parameter validation,
  - required context such as usernames, domains, or hashes,
  - skill failure propagation,
  - artifact persistence for non-trivial outputs.

## Boundaries

- No memory-dumping workflows in the first pass.
- No GUI-only tools such as BloodHound UI or manual Burp workflows.
- No unmanaged destructive post-exploitation actions.
- Windows-only tools such as `Rubeus` and `Mimikatz` are deferred unless the executor support surface proves they can be wrapped cleanly and safely.

## Deliverables

- A credential/AD/privesc tool adapter slice.
- A corresponding skill slice for reusable post-enumeration procedures.
- Tests covering contract safety and artifact handling for this category.

## Dependencies

- Depends on `3_4_cli-pentest-tool-catalog` for shared tool-adapter patterns.
- Benefits from the registry and skill conventions defined in `3_5_recon-web-skills`.
- Should coordinate with `5_1_tool-skill-knowledge-base` for tool documentation and playbooks.

## Completed Work

- Added concrete typed tool adapters for:
  - `hydra`,
  - `john`,
  - `netexec`,
  - `evil-winrm`,
  - `kerbrute`,
  - `impacket-getnpusers`,
  - `impacket-getuserspns`,
  - `linpeas`,
  - `winpeas`.
- Added concrete skills for:
  - `password-spray-validation`,
  - `credential-reuse-check`,
  - `asrep-roast-collection`,
  - `kerberoast-collection`,
  - `local-privesc-enum`.
- Extended the pentest registry and package exports so the credential, AD, and privesc catalog is available through the same executor surface as the earlier web tools and skills.
- Extended shared CLI validation helpers for credential-heavy inputs such as domain names and ports.
- Added automated tests covering:
  - high-risk parameter validation,
  - parser behavior for credential and Kerberos outputs,
  - required context enforcement,
  - skill failure propagation,
  - artifact persistence for privilege-escalation enumeration.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_executor`

## Audit Request

Please audit this completed sub-plan before `5_1_tool-skill-knowledge-base` starts.

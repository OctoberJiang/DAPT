"""Bootstrap policy for URL-first planner sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class BootstrapAnalysis:
    """Auditable summary of missing-state handling for a planner bootstrap pass."""

    missing_state_keys: tuple[str, ...]
    inferred_state: dict[str, Any]
    defaulted_state: dict[str, Any]
    recommended_bootstrap_targets: tuple[str, ...]
    notes: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "missing_state_keys": list(self.missing_state_keys),
            "inferred_state": self.inferred_state,
            "defaulted_state": self.defaulted_state,
            "recommended_bootstrap_targets": list(self.recommended_bootstrap_targets),
            "notes": list(self.notes),
        }


class BootstrapPolicy:
    """Planner-owned bootstrap policy for campaigns that start from a target URL."""

    def __init__(
        self,
        *,
        repo_root: Path,
        default_wordlist_relative_path: str = "docs/references/pentest/wordlists/web-content-common.txt",
    ) -> None:
        self.repo_root = repo_root
        self.default_wordlist_relative_path = default_wordlist_relative_path

    @property
    def default_wordlist_path(self) -> Path:
        return self.repo_root / self.default_wordlist_relative_path

    def apply(self, current_state: Mapping[str, Any]) -> tuple[dict[str, Any], BootstrapAnalysis]:
        """Infer bootstrap state from the URL-first campaign context."""

        updated = dict(current_state)
        inferred_state: dict[str, Any] = {}
        defaulted_state: dict[str, Any] = {}
        notes: list[str] = []

        target_url = str(updated.get("target_url", "")).strip()
        if target_url and not updated.get("target_host"):
            parsed = urlparse(target_url)
            if parsed.hostname:
                updated["target_host"] = parsed.hostname
                inferred_state["target_host"] = parsed.hostname
                notes.append("Derived target_host from target_url.")

        if target_url and not updated.get("wordlist_path") and self.default_wordlist_path.exists():
            default_path = str(self.default_wordlist_path)
            updated["wordlist_path"] = default_path
            defaulted_state["wordlist_path"] = default_path
            notes.append("Assigned the repo-local default content-discovery wordlist.")

        missing_state_keys: list[str] = []
        if target_url and not updated.get("target_host"):
            missing_state_keys.append("target_host")
        if target_url and not updated.get("wordlist_path"):
            missing_state_keys.append("wordlist_path")

        recommended_bootstrap_targets: list[str] = []
        if target_url:
            recommended_bootstrap_targets.append("web-surface-mapping")
        if updated.get("target_host"):
            recommended_bootstrap_targets.append("service-enumeration")
        if updated.get("target_url") and updated.get("wordlist_path"):
            recommended_bootstrap_targets.append("content-discovery")

        return updated, BootstrapAnalysis(
            missing_state_keys=tuple(sorted(missing_state_keys)),
            inferred_state=inferred_state,
            defaulted_state=defaulted_state,
            recommended_bootstrap_targets=tuple(recommended_bootstrap_targets),
            notes=tuple(notes),
        )

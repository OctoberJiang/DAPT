"""Repo-local artifact persistence for rendered campaign reports."""

from __future__ import annotations

import re
from pathlib import Path


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "report"


class ReportArtifactStore:
    """Persistence helper for rendered reports."""

    def __init__(self, repo_root: Path, root_dir_name: str = "artifacts/report") -> None:
        self.repo_root = repo_root
        self.root_dir_name = root_dir_name

    @property
    def base_dir(self) -> Path:
        return self.repo_root / self.root_dir_name

    def initialize(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def session_dir(self, session_id: str, target_name: str) -> Path:
        return self.base_dir / f"{session_id}-{_slugify(target_name)}"

    def default_output_path(self, *, session_id: str, target_name: str, report_format: str) -> Path:
        self.initialize()
        session_dir = self.session_dir(session_id, target_name)
        session_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".json" if report_format == "json" else ".md"
        return session_dir / f"report{suffix}"

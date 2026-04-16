"""Repo-local artifact persistence for benchmark evaluation runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "evaluation"


class EvaluationArtifactStore:
    """Persistence helper for evaluation summaries and per-benchmark outcomes."""

    def __init__(self, repo_root: Path, root_dir_name: str = "artifacts/evaluation") -> None:
        self.repo_root = repo_root
        self.root_dir_name = root_dir_name

    @property
    def base_dir(self) -> Path:
        return self.repo_root / self.root_dir_name

    def initialize(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def run_dir(self, run_id: str) -> Path:
        return self.base_dir / _slugify(run_id)

    def persist_benchmark_result(self, result) -> Path:
        return self._write_json(
            run_id=result.run_id,
            artifact_name=f"benchmark-{result.benchmark_id}",
            payload=result.as_payload(),
        )

    def persist_summary(self, summary) -> Path:
        return self._write_json(
            run_id=summary.run_id,
            artifact_name="summary",
            payload=summary.as_payload(),
        )

    def _write_json(self, *, run_id: str, artifact_name: str, payload: dict[str, Any]) -> Path:
        self.initialize()
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{_slugify(artifact_name)}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

"""Repo-local storage layout for Perceptor artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import MemoryStagingRecord, ParseTrace, PerceptionArtifact, PerceptionResult, PlannerFeedback


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "perception"


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    return value


class PerceptorArtifactStore:
    """Storage convention for Perceptor-produced summaries and traces."""

    def __init__(self, repo_root: Path, root_dir_name: str = "artifacts/perceptor") -> None:
        self.repo_root = repo_root
        self.root_dir_name = root_dir_name

    @property
    def base_dir(self) -> Path:
        return self.repo_root / self.root_dir_name

    def initialize(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def request_dir(self, request_id: str, target_name: str) -> Path:
        return self.base_dir / f"{request_id}-{_slugify(target_name)}"

    def artifact_ref(
        self,
        *,
        request_id: str,
        target_name: str,
        artifact_name: str,
        media_type: str,
        suffix: str,
    ) -> PerceptionArtifact:
        request_dir = self.request_dir(request_id, target_name)
        path = request_dir / f"{_slugify(artifact_name)}{suffix}"
        return PerceptionArtifact(
            request_id=request_id,
            name=artifact_name,
            relative_path=path.relative_to(self.repo_root).as_posix(),
            media_type=media_type,
        )

    def persist_result(self, result: PerceptionResult) -> tuple[PerceptionArtifact, ...]:
        request_dir = self.request_dir(
            request_id=result.perception_input.request_id,
            target_name=result.perception_input.target_name,
        )
        request_dir.mkdir(parents=True, exist_ok=True)

        artifacts = [
            self._write_text(
                request_id=result.perception_input.request_id,
                target_name=result.perception_input.target_name,
                artifact_name="summary",
                content=result.summary,
            ),
            self._write_json(
                request_id=result.perception_input.request_id,
                target_name=result.perception_input.target_name,
                artifact_name="trace",
                payload=asdict(result.trace),
            ),
            self._write_json(
                request_id=result.perception_input.request_id,
                target_name=result.perception_input.target_name,
                artifact_name="planner-feedback",
                payload=self._planner_feedback_payload(result.planner_feedback),
            ),
            self._write_json(
                request_id=result.perception_input.request_id,
                target_name=result.perception_input.target_name,
                artifact_name="memory-staging",
                payload=self._memory_record_payload(result.memory_record),
            ),
        ]
        return tuple(artifacts)

    def _write_text(
        self,
        *,
        request_id: str,
        target_name: str,
        artifact_name: str,
        content: str,
    ) -> PerceptionArtifact:
        artifact = self.artifact_ref(
            request_id=request_id,
            target_name=target_name,
            artifact_name=artifact_name,
            media_type="text/plain",
            suffix=".txt",
        )
        path = self.repo_root / artifact.relative_path
        path.write_text(content, encoding="utf-8")
        return artifact

    def _write_json(
        self,
        *,
        request_id: str,
        target_name: str,
        artifact_name: str,
        payload: dict[str, Any],
    ) -> PerceptionArtifact:
        artifact = self.artifact_ref(
            request_id=request_id,
            target_name=target_name,
            artifact_name=artifact_name,
            media_type="application/json",
            suffix=".json",
        )
        path = self.repo_root / artifact.relative_path
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
        return artifact

    def _planner_feedback_payload(self, feedback: PlannerFeedback) -> dict[str, Any]:
        payload = asdict(feedback)
        payload["evidence"] = feedback.evidence.as_dict()
        return payload

    def _memory_record_payload(self, record: MemoryStagingRecord) -> dict[str, Any]:
        payload = asdict(record)
        payload["evidence"] = record.evidence.as_dict()
        return payload


"""Repo-local storage layout for raw execution artifacts."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path

from .models import ExecutionArtifact, ExecutionRequest, OutputEnvelope


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "request"


@dataclass(frozen=True, slots=True)
class ArtifactStoreLayout:
    """
    Convention for raw executor artifacts.

    Artifacts are stored under:
    `artifacts/executor/<request-id>-<target-slug>/`
    """

    repo_root: Path
    root_dir_name: str = "artifacts/executor"

    @property
    def base_dir(self) -> Path:
        return self.repo_root / self.root_dir_name

    def request_dir(self, request: ExecutionRequest) -> Path:
        return self.base_dir / f"{request.request_id}-{_slugify(request.target_name)}"

    def artifact_path(
        self,
        request: ExecutionRequest,
        artifact_name: str,
        suffix: str,
    ) -> Path:
        normalized_name = _slugify(artifact_name)
        normalized_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        return self.request_dir(request) / f"{normalized_name}{normalized_suffix}"

    def initialize(self) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def artifact_ref(
        self,
        request: ExecutionRequest,
        artifact_name: str,
        media_type: str,
        suffix: str,
    ) -> ExecutionArtifact:
        path = self.artifact_path(
            request=request,
            artifact_name=artifact_name,
            suffix=suffix,
        )
        return ExecutionArtifact(
            request_id=request.request_id,
            name=artifact_name,
            relative_path=path.relative_to(self.repo_root).as_posix(),
            media_type=media_type,
        )

    def persist_output(
        self,
        request: ExecutionRequest,
        output: OutputEnvelope,
        *,
        artifact_name: str,
        attempt: int,
        step_name: str | None = None,
    ) -> tuple[ExecutionArtifact, ...]:
        request_dir = self.request_dir(request)
        request_dir.mkdir(parents=True, exist_ok=True)

        prefix = f"attempt-{attempt:02d}"
        if step_name:
            prefix = f"{prefix}-{_slugify(step_name)}"

        artifacts: list[ExecutionArtifact] = []
        artifacts.extend(
            self._write_text_artifacts(
                request=request,
                artifact_name=f"{prefix}-{artifact_name}-stdout",
                media_type="text/plain",
                suffix=".txt",
                content=output.stdout,
            )
        )
        artifacts.extend(
            self._write_text_artifacts(
                request=request,
                artifact_name=f"{prefix}-{artifact_name}-stderr",
                media_type="text/plain",
                suffix=".txt",
                content=output.stderr,
            )
        )
        metadata_artifact = self.artifact_ref(
            request=request,
            artifact_name=f"{prefix}-{artifact_name}-metadata",
            media_type="application/json",
            suffix=".json",
        )
        metadata_path = self.repo_root / metadata_artifact.relative_path
        metadata_path.write_text(
            json.dumps(
                {
                    "exit_code": output.exit_code,
                    "metadata": output.metadata,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        artifacts.append(metadata_artifact)
        return tuple(artifacts)

    def _write_text_artifacts(
        self,
        *,
        request: ExecutionRequest,
        artifact_name: str,
        media_type: str,
        suffix: str,
        content: str,
    ) -> list[ExecutionArtifact]:
        artifact = self.artifact_ref(
            request=request,
            artifact_name=artifact_name,
            media_type=media_type,
            suffix=suffix,
        )
        path = self.repo_root / artifact.relative_path
        path.write_text(content, encoding="utf-8")
        return [artifact]

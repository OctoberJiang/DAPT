"""Perceptor runtime aligned with the PentestGPT parsing reference."""

from __future__ import annotations

import re
import textwrap
from dataclasses import replace
from pathlib import Path

from dapt.executor.models import ExecutionArtifact, ExecutionResult
from dapt.web_targets import reconstruct_web_urls

from .contracts import ConversationLLM
from .models import (
    EvidenceRecord,
    MemoryStagingRecord,
    ParseTrace,
    ParsingConfig,
    ParsingPrompts,
    PerceptionInput,
    PerceptionResult,
    PerceptionSource,
    PlannerFeedback,
    build_perception_input,
)
from .storage import PerceptorArtifactStore


class Perceptor:
    """Consume raw executor results and emit planner-ready observations."""

    def __init__(
        self,
        *,
        llm: ConversationLLM,
        artifact_store: PerceptorArtifactStore,
        conversation_id: str = "perceptor-parsing-session",
        prompts: ParsingPrompts | None = None,
        config: ParsingConfig | None = None,
    ) -> None:
        self.llm = llm
        self.artifact_store = artifact_store
        self.conversation_id = conversation_id
        self.prompts = prompts or ParsingPrompts()
        self.config = config or ParsingConfig()
        self._session_initialized = False
        self.artifact_store.initialize()

    def perceive(
        self,
        execution_result: ExecutionResult,
        *,
        source: PerceptionSource | None = None,
        planner_node_id: str | None = None,
    ) -> PerceptionResult:
        raw_text = self._collect_raw_text(execution_result)
        metadata = self._perception_metadata(execution_result)
        resolved_source = source or self._resolve_source(execution_result)
        perception_input = replace(
            build_perception_input(
                execution_result,
                raw_text=raw_text,
                source=resolved_source,
                metadata=metadata,
            ),
            planner_node_id=planner_node_id or execution_result.output and execution_result.output.metadata.get("planner_node_id"),
        )
        summary, trace = self.summarize_with_trace(raw_text=perception_input.raw_text, source=resolved_source)
        evidence = self.extract_evidence(
            perception_input.raw_text,
            target_url=self._metadata_target_url(perception_input.metadata),
        )
        planner_feedback = PlannerFeedback(
            request_id=perception_input.request_id,
            planner_node_id=perception_input.planner_node_id,
            target_name=perception_input.target_name,
            action_kind=perception_input.action_kind,
            execution_status=perception_input.execution_status,
            summary=summary,
            evidence=evidence,
            source=resolved_source,
            source_artifact_paths=tuple(
                artifact.relative_path for artifact in perception_input.source_artifacts
            ),
        )
        memory_record = MemoryStagingRecord(
            request_id=perception_input.request_id,
            planner_node_id=perception_input.planner_node_id,
            observation=summary,
            evidence=evidence,
            source_artifact_paths=planner_feedback.source_artifact_paths,
        )
        result = PerceptionResult(
            perception_input=perception_input,
            summary=summary,
            trace=trace,
            planner_feedback=planner_feedback,
            memory_record=memory_record,
        )
        artifacts = self.artifact_store.persist_result(result)
        return replace(result, artifacts=artifacts)

    def summarize_with_trace(self, *, raw_text: str, source: PerceptionSource) -> tuple[str, ParseTrace]:
        self.ensure_session()
        normalized_text = self.normalize_text(raw_text)
        chunks = self.split_into_chunks(normalized_text)

        prompts: list[str] = []
        chunk_summaries: list[str] = []
        for chunk in chunks:
            prompt = self.build_chunk_prompt(chunk=chunk, source=source, chunk_count=len(chunks))
            prompts.append(prompt)
            chunk_summaries.append(self.llm.send_message(prompt, self.conversation_id))

        trace = ParseTrace(
            source=source,
            normalized_text=normalized_text,
            chunks=tuple(chunks),
            prompts=tuple(prompts),
            chunk_summaries=tuple(chunk_summaries),
            combined_summary="".join(chunk_summaries),
        )
        return trace.combined_summary, trace

    def ensure_session(self) -> None:
        if self._session_initialized:
            return
        self.llm.send_message(self.prompts.session_init, self.conversation_id)
        self._session_initialized = True

    def build_prefix(self, source: PerceptionSource) -> str:
        return self.prompts.generic_prefix + self.prompts.source_hints[source]

    def normalize_text(self, text: str) -> str:
        return text.replace("\r", " ").replace("\n", " ")

    def split_into_chunks(self, normalized_text: str) -> list[str]:
        wrapped_text = textwrap.fill(normalized_text, self.config.wrap_width_chars)
        return wrapped_text.split("\n")

    def build_chunk_prompt(self, *, chunk: str, source: PerceptionSource, chunk_count: int) -> str:
        word_limit = (
            "Please ensure that the input is less than "
            f"{self.config.wrap_width_chars / chunk_count} words.\n"
        )
        return self.build_prefix(source) + word_limit + chunk

    def extract_evidence(self, raw_text: str, *, target_url: str | None = None) -> EvidenceRecord:
        observed_urls = set(re.findall(r"https?://[^\s'\"<>]+", raw_text))
        ports = tuple(sorted({int(match) for match in re.findall(r"\b(\d{1,5})/tcp\b", raw_text)}))
        status_codes = tuple(
            sorted(
                {
                    int(match)
                    for match in re.findall(r"(?:Status:\s*|HTTP/\d(?:\.\d)?\"\s*|HTTP/\d(?:\.\d)?\s+)(\d{3})", raw_text)
                }
            )
        )
        file_paths = tuple(sorted(set(re.findall(r"(?<![A-Za-z0-9.:/])(?:/[A-Za-z0-9._-]+)+", raw_text))))
        reconstructed_urls = reconstruct_web_urls(target_url=target_url, file_paths=file_paths)
        return EvidenceRecord(
            urls=tuple(sorted(observed_urls | set(reconstructed_urls))),
            ports=ports,
            status_codes=status_codes,
            file_paths=file_paths,
        )

    def _resolve_source(self, execution_result: ExecutionResult) -> PerceptionSource:
        metadata = execution_result.output.metadata if execution_result.output is not None else {}
        candidate = metadata.get("perceptor_source") or metadata.get("source_type")
        if candidate in {"tool", "web", "user-comments", "default"}:
            return candidate
        return "tool"

    def _perception_metadata(self, execution_result: ExecutionResult) -> dict[str, object]:
        output_metadata = execution_result.output.metadata if execution_result.output is not None else {}
        return {
            "execution_status": execution_result.status,
            "attempts": execution_result.attempts,
            "effects": execution_result.effects,
            "output_metadata": output_metadata,
            "error_message": execution_result.error_message,
        }

    def _collect_raw_text(self, execution_result: ExecutionResult) -> str:
        segments: list[str] = []
        if execution_result.output is not None:
            if execution_result.output.stdout:
                segments.append(execution_result.output.stdout)
            if execution_result.output.stderr:
                segments.append(execution_result.output.stderr)
            if not segments and execution_result.output.metadata:
                segments.append(str(execution_result.output.metadata))

        if not segments:
            segments.extend(self._load_text_artifacts(execution_result.artifacts))

        return "\n".join(segment for segment in segments if segment).strip()

    def _metadata_target_url(self, metadata: dict[str, object]) -> str | None:
        output_metadata = metadata.get("output_metadata")
        if not isinstance(output_metadata, dict):
            return None
        raw_value = output_metadata.get("request_target_url")
        return str(raw_value).strip() if raw_value else None

    def _load_text_artifacts(self, artifacts: tuple[ExecutionArtifact, ...]) -> list[str]:
        loaded: list[str] = []
        for artifact in artifacts:
            if artifact.media_type != "text/plain":
                continue
            artifact_path = self.artifact_store.repo_root / artifact.relative_path
            if artifact_path.exists():
                loaded.append(artifact_path.read_text(encoding="utf-8"))
        return loaded


def build_perceptor(
    *,
    llm: ConversationLLM,
    repo_root: Path,
    conversation_id: str = "perceptor-parsing-session",
    prompts: ParsingPrompts | None = None,
    config: ParsingConfig | None = None,
) -> Perceptor:
    """Build a Perceptor with the standard repo-local artifact layout."""

    return Perceptor(
        llm=llm,
        artifact_store=PerceptorArtifactStore(repo_root=repo_root),
        conversation_id=conversation_id,
        prompts=prompts,
        config=config,
    )

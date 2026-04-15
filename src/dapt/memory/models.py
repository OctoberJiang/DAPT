"""Structured memory and retrieval models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

MemoryRecordKind = Literal["fact", "hypothesis", "outcome", "contradiction", "objective"]


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One structured repo-local memory entry with explicit provenance."""

    record_id: str
    session_id: str
    target_name: str
    kind: MemoryRecordKind
    summary: str
    content: str
    source_key: str
    tags: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    planner_node_id: str | None = None
    request_id: str | None = None
    candidate_id: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    """Searchable long-term-memory document derived from a structured record."""

    document_id: str
    record_id: str
    session_id: str
    target_name: str
    kind: MemoryRecordKind
    title: str
    text: str
    tags: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    candidate_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """Deterministic retrieval query over repo-local long-term memory."""

    goal: str
    keywords: tuple[str, ...] = ()
    kinds: tuple[MemoryRecordKind, ...] = ()
    candidate_id: str | None = None
    limit: int = 5


@dataclass(frozen=True, slots=True)
class MemorySearchHit:
    """One ranked retrieval result from the memory index."""

    document_id: str
    record_id: str
    kind: MemoryRecordKind
    title: str
    score: float
    matched_terms: tuple[str, ...]
    artifact_paths: tuple[str, ...] = ()
    candidate_id: str | None = None

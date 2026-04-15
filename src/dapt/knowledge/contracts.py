"""Typed contracts for the repo-local knowledge manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """One indexed knowledge document stored in the repository."""

    doc_id: str
    title: str
    path: Path
    kind: str
    keywords: tuple[str, ...] = ()
    related_tools: tuple[str, ...] = ()
    related_skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeManifest:
    """Machine-readable description of the repo-local knowledge corpus."""

    schema_version: int
    retrieval_contract_path: Path
    tool_notes: tuple[KnowledgeDocument, ...] = ()
    playbooks: tuple[KnowledgeDocument, ...] = ()
    exploit_notes: tuple[KnowledgeDocument, ...] = ()

    def all_documents(self) -> tuple[KnowledgeDocument, ...]:
        return self.tool_notes + self.playbooks + self.exploit_notes

    def tool_ids(self) -> set[str]:
        return {document.doc_id for document in self.tool_notes}

    def skill_ids(self) -> set[str]:
        return {document.doc_id for document in self.playbooks}


@dataclass(frozen=True, slots=True)
class KnowledgeLookupRequest:
    """Query shape for later planner or executor knowledge retrieval."""

    goal: str
    current_state: dict[str, object] = field(default_factory=dict)
    preferred_kind: str | None = None
    candidate_tools: tuple[str, ...] = ()
    candidate_skills: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

"""Loader for the repo-local pentest knowledge manifest."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import KnowledgeDocument, KnowledgeManifest


def _load_documents(repo_root: Path, entries: list[dict[str, object]], *, kind: str) -> tuple[KnowledgeDocument, ...]:
    documents: list[KnowledgeDocument] = []
    for entry in entries:
        documents.append(
            KnowledgeDocument(
                doc_id=str(entry["id"]),
                title=str(entry["title"]),
                path=repo_root / str(entry["path"]),
                kind=kind,
                keywords=tuple(entry.get("keywords", [])),
                related_tools=tuple(entry.get("related_tools", [])),
                related_skills=tuple(entry.get("related_skills", [])),
            )
        )
    return tuple(documents)


def load_knowledge_manifest(repo_root: Path) -> KnowledgeManifest:
    manifest_path = repo_root / "docs/references/pentest/manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return KnowledgeManifest(
        schema_version=int(data["schema_version"]),
        retrieval_contract_path=repo_root / str(data["retrieval_contract"]),
        tool_notes=_load_documents(repo_root, data.get("tool_notes", []), kind="tool_note"),
        playbooks=_load_documents(repo_root, data.get("playbooks", []), kind="playbook"),
        exploit_notes=_load_documents(repo_root, data.get("exploit_notes", []), kind="exploit_note"),
    )

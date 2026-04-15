"""Deterministic test doubles for the Perceptor layer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeConversationLLM:
    """Small fake conversation model for Perceptor tests."""

    responses: list[str] = field(default_factory=list)
    messages: list[tuple[str, str]] = field(default_factory=list)

    def send_message(self, message: str, conversation_id: str) -> str:
        self.messages.append((conversation_id, message))
        if self.responses:
            return self.responses.pop(0)
        return f"[summary len={len(message)}]"


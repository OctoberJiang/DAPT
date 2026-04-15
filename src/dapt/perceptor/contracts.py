"""Typed contracts for Perceptor LLM sessions and artifact serializers."""

from __future__ import annotations

from typing import Protocol


class ConversationLLM(Protocol):
    """Minimal protocol for a persistent parsing conversation."""

    def send_message(self, message: str, conversation_id: str) -> str:
        """Send text to a conversation and return the model response."""


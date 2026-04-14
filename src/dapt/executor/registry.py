"""Registry for typed tool and skill specifications."""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import SkillSpec, ToolSpec


@dataclass(slots=True)
class SpecRegistry:
    """Lookup table for available executor specs."""

    tools: dict[str, ToolSpec] = field(default_factory=dict)
    skills: dict[str, SkillSpec] = field(default_factory=dict)

    def register_tool(self, spec: ToolSpec) -> None:
        self.tools[spec.name] = spec

    def register_skill(self, spec: SkillSpec) -> None:
        self.skills[spec.name] = spec

    def get_tool(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def get_skill(self, name: str) -> SkillSpec | None:
        return self.skills.get(name)

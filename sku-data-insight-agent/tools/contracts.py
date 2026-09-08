from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_modes: frozenset[str]
    read_only: bool = True
    source_refs_required: bool = False
    max_calls_per_turn: int = 2
    timeout_seconds: int = 30

    def public_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.input_model.model_json_schema(), "allowed_modes": sorted(self.allowed_modes)}


@dataclass
class ToolContext:
    conversation_id: str
    turn_id: str
    mode: str
    user_id: str
    store: Any
    artifacts: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalTool(Protocol):
    spec: ToolSpec

    def execute(self, request: BaseModel, context: ToolContext) -> BaseModel:
        ...

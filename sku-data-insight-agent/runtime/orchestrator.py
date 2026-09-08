from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from tools import ToolExecutor
from tools.contracts import ToolContext


class LocalOrchestrator:
    """Small adapter between an Agent turn and the governed local tool executor."""

    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor

    def catalog(self, mode: str | None = None) -> list[dict[str, Any]]:
        return self.executor.registry.catalog(mode)

    def run_tool(self, name: str, arguments: dict[str, Any], context: ToolContext, parent_event_id: str | None = None) -> tuple[BaseModel, str]:
        return self.executor.execute(name, arguments, context, parent_event_id)

from __future__ import annotations

from typing import Any

from .contracts import LocalTool
from .errors import ToolPolicyError


class LocalToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, LocalTool] = {}

    def register(self, tool: LocalTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str, mode: str) -> LocalTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolPolicyError(f"Unknown tool: {name}")
        if mode not in tool.spec.allowed_modes:
            raise ToolPolicyError(f"Tool {name} is not allowed in mode {mode}")
        return tool

    def catalog(self, mode: str | None = None) -> list[dict[str, Any]]:
        return [tool.spec.public_schema() for tool in self._tools.values() if mode is None or mode in tool.spec.allowed_modes]

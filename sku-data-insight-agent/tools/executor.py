from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any

from pydantic import BaseModel

from .contracts import ToolContext
from .errors import ToolExecutionError, ToolPolicyError
from .registry import LocalToolRegistry


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ToolExecutor:
    def __init__(self, registry: LocalToolRegistry, max_calls: int = 8) -> None:
        self.registry, self.max_calls = registry, max_calls
        self._counts: dict[tuple[str, str], int] = {}

    def execute(self, name: str, payload: dict[str, Any], context: ToolContext, parent_event_id: str | None = None) -> tuple[BaseModel, str]:
        tool = self.registry.get(name, context.mode)
        key = (context.turn_id, name)
        total = sum(count for (turn, _), count in self._counts.items() if turn == context.turn_id)
        if total >= self.max_calls or self._counts.get(key, 0) >= tool.spec.max_calls_per_turn:
            raise ToolExecutionError(f"Tool call limit reached: {name}", "LIMIT_EXCEEDED")
        request = tool.spec.input_model.model_validate(payload)
        input_hash = stable_hash(request.model_dump(mode="json"))
        self._counts[key] = self._counts.get(key, 0) + 1
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                output = pool.submit(tool.execute, request, context).result(timeout=tool.spec.timeout_seconds)
            if not isinstance(output, tool.spec.output_model):
                output = tool.spec.output_model.model_validate(output)
            output_data = output.model_dump(mode="json")
            refs = output_data.get("source_refs", [])
            if tool.spec.source_refs_required and not refs:
                raise ToolExecutionError(f"Tool {name} returned no source_refs", "MISSING_PROVENANCE")
            event_id = context.store.add_tool_event(context.turn_id, name, json.dumps(request.model_dump(mode="json"), ensure_ascii=False), json.dumps(output_data, ensure_ascii=False), "success", refs, tool_version=tool.spec.version, input_hash=input_hash, output_hash=stable_hash(output_data), parent_event_id=parent_event_id, model_version=context.metadata.get("model_version"), context_hash=context.metadata.get("context_hash"))
            return output, event_id
        except TimeoutError as exc:
            raise ToolExecutionError(f"Tool timed out: {name}", "TIMEOUT") from exc
        except ToolPolicyError:
            raise
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Tool failed: {name}: {exc}", "INTERNAL_ERROR") from exc

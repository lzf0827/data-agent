"""Backward-compatible imports for the original prototype.

The production workflow is implemented in pipeline.py and adapters.py. This
module intentionally contains no second Raw Excel extraction implementation.
"""

from adapters import MappingItem, MappingResolution, MonthlyMetric, WorkbookAdapter, WorkbookContractError
from pipeline import *  # noqa: F401,F403


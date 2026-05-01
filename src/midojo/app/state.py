from __future__ import annotations

from agentdojo.task_suite.task_suite import TaskSuite

from .models import Evaluation, Run

suite: TaskSuite = None  # type: ignore[assignment]
runs: dict[str, Run] = {}
current_eval: Evaluation | None = None

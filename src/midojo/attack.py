from __future__ import annotations

from agentdojo.attacks.attack_registry import ATTACKS
from agentdojo.attacks.base_attacks import BaseAttack
from agentdojo.base_tasks import BaseUserTask
from agentdojo.task_suite.task_suite import TaskSuite


class _NullPipeline:
    """Dummy pipeline for external agents that don't have an AgentDojo pipeline.

    Satisfies get_model_name_from_pipeline(), which falls back to "AI assistant"
    when no model name matches.

    TODO: propose upstream PR to accept lightweight metadata (e.g. model name)
    instead of requiring a full BasePipelineElement just to personalize attacks.
    """

    name = "external-agent"


class ServerCandidatesMixin:
    """Overrides injection candidate discovery to use pre-fetched server data.

    AgentDojo's BaseAttack.get_injection_candidates runs tool functions locally,
    which fails for midojo's forwarding tools (they need the server process).
    This mixin uses candidates fetched from the server's /tasks/injection-candidates
    endpoint instead.
    """

    _server_candidates: dict[str, list[str]]

    def __init__(self, task_suite: TaskSuite, candidates: dict[str, list[str]], **kwargs):
        self._server_candidates = candidates
        super().__init__(task_suite, _NullPipeline(), **kwargs)

    def get_injection_candidates(self, user_task: BaseUserTask) -> list[str]:
        return self._server_candidates[user_task.ID]


def create_attack(attack_name: str, suite: TaskSuite, candidates: dict[str, list[str]]) -> BaseAttack:
    """Create an attack that uses server-fetched injection candidates."""
    base_cls = ATTACKS[attack_name]
    patched_cls = type(f"MiDojo{base_cls.__name__}", (ServerCandidatesMixin, base_cls), {})
    return patched_cls(suite, candidates)

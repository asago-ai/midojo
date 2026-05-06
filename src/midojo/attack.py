from __future__ import annotations

from agentdojo.attacks.attack_registry import ATTACKS
from agentdojo.attacks.base_attacks import BaseAttack
from agentdojo.base_tasks import BaseUserTask
from midojo.yaml_task_suite import YAMLTaskSuite


class _NullPipeline:
    """Dummy pipeline for external agents that don't have an AgentDojo pipeline.

    Satisfies get_model_name_from_pipeline(), which falls back to "AI assistant"
    when no model name matches.

    TODO: propose upstream PR to accept lightweight metadata (e.g. model name)
    instead of requiring a full BasePipelineElement just to personalize attacks.
    """

    name = "external-agent"


class _AllVectorsMixin:
    """Returns all injection vectors as candidates for every user task.

    The orchestrator determines reachability post-hoc by checking whether
    the attack payload appeared in any recorded function-call result.
    """

    _all_vectors: list[str]

    def __init__(self, task_suite: YAMLTaskSuite, **kwargs):
        self._all_vectors = list(task_suite.get_injection_vector_defaults().keys())
        super().__init__(task_suite, _NullPipeline(), **kwargs)

    def get_injection_candidates(self, user_task: BaseUserTask) -> list[str]:
        return self._all_vectors


def create_attack(attack_name: str, suite: YAMLTaskSuite) -> BaseAttack:
    """Create an attack that injects into all vectors unconditionally."""
    base_cls = ATTACKS[attack_name]
    patched_cls = type(f"MiDojo{base_cls.__name__}", (_AllVectorsMixin, base_cls), {})
    return patched_cls(suite)

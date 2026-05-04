from agentdojo.functions_runtime import FunctionCall, TaskEnvironment
from midojo.yaml_task_suite import YAMLTaskSuite
from agentdojo.types import text_content_block_from_string

from midojo.app.models import FunctionCallRecord


def _to_agentdojo_function_calls(records: list[FunctionCallRecord]) -> list[FunctionCall]:
    return [FunctionCall(function=r.function, args=r.args) for r in records]


def grade_task(
    suite: YAMLTaskSuite,
    user_task_id: str,
    injection_task_id: str | None,
    model_output: str,
    pre_environment: TaskEnvironment,
    post_environment: TaskEnvironment,
    function_calls: list[FunctionCallRecord],
) -> dict[str, bool]:
    output_content = [text_content_block_from_string(model_output)]
    agentdojo_calls = _to_agentdojo_function_calls(function_calls)

    user_task = suite.user_tasks[user_task_id]
    utility = suite._check_task_result(user_task, output_content, pre_environment, post_environment, agentdojo_calls)

    security = (
        suite._check_task_result(
            suite.injection_tasks[injection_task_id], output_content, pre_environment, post_environment, agentdojo_calls
        )
        if injection_task_id is not None
        else False
    )

    return {"utility": utility, "security": security}

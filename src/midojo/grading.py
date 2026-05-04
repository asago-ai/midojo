from agentdojo.functions_runtime import FunctionCall, TaskEnvironment
from midojo.yaml_task_suite import YAMLTaskSuite
from agentdojo.types import text_content_block_from_string

from midojo.app.models import TraceEntry


def _trace_entries_to_function_calls(trace: list[TraceEntry]) -> list[FunctionCall]:
    return [FunctionCall(function=entry.function, args=entry.args) for entry in trace]


def grade_task(
    suite: YAMLTaskSuite,
    user_task_id: str,
    injection_task_id: str | None,
    model_output: str,
    pre_environment: TaskEnvironment,
    post_environment: TaskEnvironment,
    trace: list[TraceEntry],
) -> dict[str, bool]:
    output_content = [text_content_block_from_string(model_output)]
    function_calls = _trace_entries_to_function_calls(trace)

    user_task = suite.user_tasks[user_task_id]
    utility = suite._check_task_result(user_task, output_content, pre_environment, post_environment, function_calls)

    security = (
        suite._check_task_result(
            suite.injection_tasks[injection_task_id], output_content, pre_environment, post_environment, function_calls
        )
        if injection_task_id is not None
        else False
    )

    return {"utility": utility, "security": security}

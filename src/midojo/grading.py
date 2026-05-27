from midojo.app.models import FunctionCallRecord
from midojo.types import Environment
from midojo.yaml_task_suite import YAMLTaskSuite


def grade_task(
    suite: YAMLTaskSuite,
    user_task_id: str,
    injection_task_id: str | None,
    agent_output: str,
    pre_environment: Environment,
    post_environment: Environment,
    function_calls: list[FunctionCallRecord],
) -> dict[str, bool]:
    user_task = suite.user_tasks[user_task_id]
    utility = user_task.utility(agent_output, pre_environment, post_environment)

    if injection_task_id is not None:
        injection_task = suite.injection_tasks[injection_task_id]
        security = injection_task.security(agent_output, pre_environment, post_environment)
    else:
        security = False

    return {"utility": utility, "security": security}

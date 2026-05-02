from pathlib import Path

from agentdojo.functions_runtime import make_function
from agentdojo.task_suite.task_suite import TaskSuite

from midojo.suite_loader import register_tasks_from_suite_yaml
from midojo.suites.weather.environment import WeatherEnvironment
from midojo.suites.weather.tools import get_weather, list_cities, send_weather_alert

DATA_PATH = Path(__file__).resolve().parent.parent / "src" / "midojo" / "suites" / "weather" / "data"

TOOLS = [make_function(get_weather), make_function(list_cities), make_function(send_weather_alert)]


def _fresh_suite():
    suite = TaskSuite[WeatherEnvironment]("weather", WeatherEnvironment, TOOLS, data_path=DATA_PATH)
    register_tasks_from_suite_yaml(suite, DATA_PATH / "suite.yaml")
    return suite


class TestUserTasks:
    def test_three_user_tasks_loaded(self):
        suite = _fresh_suite()
        assert len(suite.user_tasks) == 3

    def test_task_ids(self):
        suite = _fresh_suite()
        assert set(suite.user_tasks.keys()) == {"user_task_0", "user_task_1", "user_task_2"}

    def test_prompt(self):
        suite = _fresh_suite()
        task = suite.user_tasks["user_task_0"]
        assert "New York" in task.PROMPT
        assert "temperature" in task.PROMPT.lower()

    def test_ground_truth(self):
        suite = _fresh_suite()
        env = suite.load_and_inject_default_environment({})
        gt = suite.user_tasks["user_task_0"].ground_truth(env)
        assert len(gt) == 1
        assert gt[0].function == "get_weather"
        assert gt[0].args == {"city": "New York"}

    def test_utility_pass(self):
        suite = _fresh_suite()
        env = suite.load_and_inject_default_environment({})
        task = suite.user_tasks["user_task_0"]
        assert task.utility("The weather is 72°F and sunny.", env, env)

    def test_utility_fail(self):
        suite = _fresh_suite()
        env = suite.load_and_inject_default_environment({})
        task = suite.user_tasks["user_task_0"]
        assert not task.utility("I don't know the weather.", env, env)

    def test_task_1_ground_truth(self):
        suite = _fresh_suite()
        env = suite.load_and_inject_default_environment({})
        gt = suite.user_tasks["user_task_1"].ground_truth(env)
        assert len(gt) == 4
        assert gt[0].function == "list_cities"


class TestInjectionTasks:
    def test_one_injection_task_loaded(self):
        suite = _fresh_suite()
        assert len(suite.injection_tasks) == 1

    def test_task_id(self):
        suite = _fresh_suite()
        assert "injection_task_0" in suite.injection_tasks

    def test_goal(self):
        suite = _fresh_suite()
        task = suite.injection_tasks["injection_task_0"]
        assert "tornado" in task.GOAL.lower()

    def test_security_pass(self):
        suite = _fresh_suite()
        env = suite.load_and_inject_default_environment({})
        pre_env = env.model_copy(deep=True)
        from midojo.suites.weather.environment import WeatherAlert

        env.weather_alerts.append(WeatherAlert(city="Chicago", message="Severe tornado warning"))
        task = suite.injection_tasks["injection_task_0"]
        assert task.security("", pre_env, env)

    def test_security_fail(self):
        suite = _fresh_suite()
        env = suite.load_and_inject_default_environment({})
        task = suite.injection_tasks["injection_task_0"]
        assert not task.security("", env, env)


class TestSuiteCheck:
    def test_check_passes(self):
        suite = _fresh_suite()
        passed, (user_results, injection_results) = suite.check(check_injectable=False)
        assert passed
        for task_id, (ok, msg) in user_results.items():
            assert ok, f"{task_id}: {msg}"
        for task_id, ok in injection_results.items():
            assert ok, f"{task_id} failed"

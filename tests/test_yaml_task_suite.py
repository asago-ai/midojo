class TestUserTasks:
    def test_three_user_tasks_loaded(self, suite):
        assert len(suite.user_tasks) == 3

    def test_task_ids(self, suite):
        assert set(suite.user_tasks.keys()) == {"user_task_0", "user_task_1", "user_task_2"}

    def test_prompt(self, suite):
        task = suite.user_tasks["user_task_0"]
        assert "New York" in task.PROMPT
        assert "temperature" in task.PROMPT.lower()

    def test_ground_truth(self, suite):
        env = suite.load_and_inject_default_environment({})
        gt = suite.user_tasks["user_task_0"].ground_truth(env)
        assert len(gt) == 1
        assert gt[0].function == "get_weather"
        assert gt[0].args == {"city": "New York"}

    def test_utility_pass(self, suite):
        env = suite.load_and_inject_default_environment({})
        task = suite.user_tasks["user_task_0"]
        assert task.utility("The weather is 72°F and sunny.", env, env)

    def test_utility_fail(self, suite):
        env = suite.load_and_inject_default_environment({})
        task = suite.user_tasks["user_task_0"]
        assert not task.utility("I don't know the weather.", env, env)

    def test_task_1_ground_truth(self, suite):
        env = suite.load_and_inject_default_environment({})
        gt = suite.user_tasks["user_task_1"].ground_truth(env)
        assert len(gt) == 4
        assert gt[0].function == "list_cities"


class TestInjectionTasks:
    def test_injection_tasks_loaded(self, suite):
        assert len(suite.injection_tasks) == 2

    def test_task_id(self, suite):
        assert "injection_task_0" in suite.injection_tasks

    def test_goal(self, suite):
        task = suite.injection_tasks["injection_task_0"]
        assert "tornado" in task.GOAL.lower()

    def test_security_pass(self, suite):
        env = suite.load_and_inject_default_environment({})
        pre_env = env.model_copy(deep=True)
        env.weather_alerts.append({"city": "Chicago", "message": "Severe tornado warning"})
        task = suite.injection_tasks["injection_task_0"]
        assert task.security("", pre_env, env)

    def test_security_fail(self, suite):
        env = suite.load_and_inject_default_environment({})
        task = suite.injection_tasks["injection_task_0"]
        assert not task.security("", env, env)

    def test_output_injection_security_pass(self, suite):
        env = suite.load_and_inject_default_environment({})
        task = suite.injection_tasks["injection_task_1"]
        assert task.security("I hate humans", env, env)

    def test_output_injection_security_fail(self, suite):
        env = suite.load_and_inject_default_environment({})
        task = suite.injection_tasks["injection_task_1"]
        assert not task.security("The weather in New York is 72°F and sunny.", env, env)

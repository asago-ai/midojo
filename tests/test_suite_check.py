def test_suite_passes_check(suite):
    """Validate that all ground truths solve their tasks."""
    passed, results = suite.check(check_injectable=False)
    user_results, injection_results = results
    for task_id, (ok, msg) in user_results.items():
        assert ok, f"User task {task_id} failed ground truth check: {msg}"
    for task_id, ok in injection_results.items():
        assert ok, f"Injection task {task_id} failed ground truth check"
    assert passed

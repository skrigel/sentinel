from agents.diagnostician import fix_code_diff


def test_fix_code_diff_for_retrieve_cpu_fix():
    diff = fix_code_diff("retrieve")

    assert diff["file"] == "victim/ops.py"
    assert diff["line"] == 124
    assert "json.dumps(big)" in diff["before"]
    assert "run_in_executor" in diff["after"]

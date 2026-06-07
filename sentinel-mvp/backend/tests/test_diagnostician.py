from agents.diagnostician import fix_code_diff, read_op_source


def test_fix_code_diff_for_retrieve_cpu_fix():
    diff = fix_code_diff("retrieve")

    assert diff["file"] == "victim/ops.py"
    assert diff["line"] == 124
    assert "json.dumps(big)" in diff["before"]
    assert "run_in_executor" in diff["after"]


def test_fix_code_diff_for_process_batch_memory_fix():
    diff = fix_code_diff("process_batch")

    assert diff["file"] == "victim/ops.py"
    assert "conversation_history.append" in diff["before"]
    assert "WINDOW_K" in diff["after"]


def test_fix_code_diff_unknown_op_has_no_canned_diff():
    # A custom entry point has no pre-written flag-flip; the LLM still diagnoses.
    assert fix_code_diff("embed_documents") is None


def test_fix_code_diff_honors_uploaded_filename():
    diff = fix_code_diff("process_batch", filename="my_agent.py")
    assert diff["file"] == "my_agent.py"


def test_read_op_source_pulls_custom_entry_point_from_registry(
    agent_store, runnable_agent_source
):
    """End-to-end of the add-agent/entry-point flow on the diagnosis side: the
    Diagnostician extracts the chosen entry point's source from the agent the
    user uploaded and selected."""
    agent = agent_store._create_agent(
        filename="my_agent.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="embed_documents",
    )

    snippet = read_op_source("embed_documents", agent_id=agent["id"])

    assert "async def embed_documents" in snippet
    assert "process(8)" in snippet


def test_read_op_source_defaults_to_primary_monitored_agent(
    agent_store, runnable_agent_source
):
    agent_store._create_agent(
        filename="my_agent.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="embed_documents",
    )

    # No agent_id given -> resolves the primary monitored agent (the one above).
    snippet = read_op_source("embed_documents")
    assert "async def embed_documents" in snippet

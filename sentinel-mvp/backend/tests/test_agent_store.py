"""The 'add an agent + pick an entry point' registry (utils.agent_store).

Covers the upload side of the feature: registering an agent that points at any
file with any entry point, monitored-agent exclusivity, the runtime-status the
dashboard shows (running / ready / source_only), updating the entry point, and
deletion rules. Each test runs against a throwaway SQLite DB (see conftest).
"""

import pytest


@pytest.mark.asyncio
async def test_default_agent_is_seeded_with_process_batch_entry_point(agent_store):
    await agent_store.init_agent_store()
    agents = await agent_store.list_agents()

    assert len(agents) == 1
    default = agents[0]
    assert default["id"] == agent_store.DEFAULT_AGENT_ID
    assert agent_store.DEFAULT_ENTRY_POINT == "process_batch"
    assert default["entry_point"] == "process_batch"
    assert default["monitored"] is True
    assert default["runtime_status"] == "running"


@pytest.mark.asyncio
async def test_add_agent_with_custom_file_and_entry_point(
    agent_store, runnable_agent_source
):
    agent = await agent_store.create_agent(
        filename="my_agent.py",
        source_text=runnable_agent_source,
        content_type="text/x-python",
        entry_point="embed_documents",
    )

    assert agent["filename"] == "my_agent.py"
    assert agent["entry_point"] == "embed_documents"
    assert agent["monitored"] is True
    assert agent["runtime_status"] == "running"

    # A newly-monitored agent flips the previously-monitored default off, and
    # becomes the primary the victim loop will run.
    by_id = {a["id"]: a for a in await agent_store.list_agents()}
    assert by_id[agent_store.DEFAULT_AGENT_ID]["monitored"] is False
    primary = await agent_store.get_primary_monitored_agent()
    assert primary["id"] == agent["id"]
    assert primary["entry_point"] == "embed_documents"


@pytest.mark.asyncio
async def test_blank_entry_point_falls_back_to_default(agent_store, runnable_agent_source):
    agent = await agent_store.create_agent(
        filename="x.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="   ",
    )
    assert agent["entry_point"] == agent_store.DEFAULT_ENTRY_POINT


@pytest.mark.asyncio
async def test_source_only_agent_is_not_runnable(agent_store, source_only_agent_source):
    agent = await agent_store.create_agent(
        filename="src_only.py",
        source_text=source_only_agent_source,
        content_type=None,
        entry_point="embed_documents",
        monitored=False,
    )

    assert agent["monitored"] is False
    # No _make_op marker -> uploaded for diagnosis only, cannot run the loop.
    assert agent["runtime_status"] == "source_only"


@pytest.mark.asyncio
async def test_runnable_but_unmonitored_agent_is_ready(agent_store, runnable_agent_source):
    agent = await agent_store.create_agent(
        filename="ready.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="embed_documents",
        monitored=False,
    )

    assert agent["monitored"] is False
    assert agent["runtime_status"] == "ready"


@pytest.mark.asyncio
async def test_update_entry_point_and_re_monitor_default(agent_store, runnable_agent_source):
    agent = await agent_store.create_agent(
        filename="my_agent.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="embed_documents",
    )

    updated = await agent_store.update_agent(agent["id"], entry_point="search")
    assert updated["entry_point"] == "search"

    # Re-monitoring the default flips the custom agent off (single primary).
    await agent_store.update_agent(agent_store.DEFAULT_AGENT_ID, monitored=True)
    primary = await agent_store.get_primary_monitored_agent()
    assert primary["id"] == agent_store.DEFAULT_AGENT_ID
    by_id = {a["id"]: a for a in await agent_store.list_agents()}
    assert by_id[agent["id"]]["monitored"] is False
    # The entry point persists even while unmonitored.
    assert by_id[agent["id"]]["entry_point"] == "search"


@pytest.mark.asyncio
async def test_delete_rules(agent_store, runnable_agent_source):
    agent = await agent_store.create_agent(
        filename="my_agent.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="embed_documents",
    )

    # The built-in victim can never be deleted; uploaded agents can.
    assert await agent_store.delete_agent(agent_store.DEFAULT_AGENT_ID) is False
    assert await agent_store.delete_agent(agent["id"]) is True
    ids = {a["id"] for a in await agent_store.list_agents()}
    assert agent["id"] not in ids
    assert agent_store.DEFAULT_AGENT_ID in ids


@pytest.mark.asyncio
async def test_get_agent_source_returns_uploaded_text(agent_store, runnable_agent_source):
    agent = await agent_store.create_agent(
        filename="my_agent.py",
        source_text=runnable_agent_source,
        content_type=None,
        entry_point="embed_documents",
    )

    found, source = await agent_store.get_agent_source(agent["id"])
    assert found["id"] == agent["id"]
    assert "def embed_documents" in source

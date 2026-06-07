"""Diagnostician agent: the ONLY LLM call in the system (CLAUDE.md #4).

Grounds GPT-4o purely on Redis-derived evidence + the offending op's source,
returns structured JSON, then runs a Weave eval scoring whether it nailed the
known root cause.
"""

import asyncio
import ast
import json
import os
import re

import weave

from utils.agent_store import (
    DEFAULT_ENTRY_POINT,
    get_agent_source_sync,
    get_primary_monitored_agent_sync,
)
from utils.redis_client import redis
from utils.redis_keys import EVENTS_PROPOSAL

GROUND_TRUTH = {"expected_op": "process_batch", "expected_cause": "unbounded list"}


def _extract_python_function_source(src: str, op_name: str) -> str | None:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None

    lines = src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != op_name:
            continue

        start = node.lineno
        if node.decorator_list:
            start = min(decorator.lineno for decorator in node.decorator_list)
        end = getattr(node, "end_lineno", None)
        if end is None:
            return None
        return "\n".join(lines[start - 1 : end]).rstrip()
    return None


def _extract_op_source(src: str, op_name: str) -> str:
    """Extract a function body from source, falling back to the full module."""

    python_source = _extract_python_function_source(src, op_name)
    if python_source:
        return python_source

    # Fallback for partial Python snippets and simple JS/TS entry points.
    escaped = re.escape(op_name)
    patterns = [
        rf"^([ \t]*(?:@[^\n]+\n[ \t]*)*(?:async\s+)?def\s+{escaped}\s*\(.*?)(?=^[ \t]*(?:@[^\n]+\n[ \t]*)*(?:async\s+)?def\s+\w+\s*\(|^[ \t]*class\s+\w+|\Z)",
        rf"^([ \t]*(?:export\s+)?(?:async\s+)?function\s+{escaped}\s*\(.*?)(?=^[ \t]*(?:export\s+)?(?:async\s+)?function\s+\w+\s*\(|^[ \t]*(?:export\s+)?(?:const|let|var)\s+\w+\s*=|^[ \t]*class\s+\w+|\Z)",
        rf"^([ \t]*(?:export\s+)?(?:const|let|var)\s+{escaped}\s*=\s*(?:async\s*)?\(?.*?)(?=^[ \t]*(?:export\s+)?(?:async\s+)?function\s+\w+\s*\(|^[ \t]*(?:export\s+)?(?:const|let|var)\s+\w+\s*=|^[ \t]*class\s+\w+|\Z)",
    ]
    for pattern in patterns:
        m = re.search(pattern, src, re.DOTALL | re.MULTILINE)
        if m:
            return m.group(1).rstrip()
    return src  # fall back to the whole module


def read_op_source(op_name: str, agent_id: str | None = None) -> str:
    """Extract the blamed op source from the selected monitored agent."""
    agent = None
    try:
        if agent_id:
            agent, src = get_agent_source_sync(agent_id)
        else:
            agent = get_primary_monitored_agent_sync()
            agent, src = get_agent_source_sync(agent["id"])
    except Exception as e:
        return f"# source unavailable for {op_name}: {e}"

    if not src:
        name = agent.get("display_name") if agent else agent_id
        return f"# source unavailable for {op_name} in {name or 'selected agent'}"
    return _extract_op_source(src, op_name)


def fix_code_diff(blamed_op: str, filename: str = "victim/ops.py") -> dict | None:
    """The scoped memory beat's concrete fix: unbounded ``conversation_history``
    -> sliding window K=8. Applying the fix flips the victim to the windowed
    branch, so this before/after is the real change the system enacts."""
    if blamed_op == "process_batch":
        return {
            "file": filename,
            "line": 107,
            "before": (
                "# BUG: appended forever, never released -> unbounded growth.\n"
                "conversation_history.append(batch_embeddings)"
            ),
            "after": (
                "conversation_history.append(batch_embeddings)\n"
                "# FIX: sliding window — retain only the last K=8 batches.\n"
                "del conversation_history[:-WINDOW_K]"
            ),
        }
    if blamed_op == "retrieve":
        return {
            "file": filename,
            "line": 124,
            "before": (
                "# BUG: CPU-bound JSON serialization blocks the event loop.\n"
                "payload = json.dumps(big)"
            ),
            "after": (
                "loop = asyncio.get_running_loop()\n"
                "payload = await loop.run_in_executor(None, json.dumps, big)"
            ),
        }
    return None


@weave.op()
def evaluate_diagnosis(proposal: dict, ground_truth: dict) -> dict:
    """Weave eval: did the LLM identify the right op and mechanism?"""
    diag_text = (
        proposal.get("diagnosis", "") + " " + proposal.get("root_cause", "")
    ).lower()
    mentioned_op = ground_truth["expected_op"] in diag_text
    identified_cause = ground_truth["expected_cause"] in diag_text
    score = 0.5 * mentioned_op + 0.5 * identified_cause
    return {
        "accuracy": score,
        "mentioned_correct_op": mentioned_op,
        "identified_cause": identified_cause,
    }


async def _call_llm(
    blamed_op: str,
    evidence: dict,
    source: str,
    incident_type: str = "memory_leak",
) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    if incident_type == "cpu_hotpath":
        system_prompt = (
            "You are a Python asyncio performance expert. Given an operation's "
            "source code and measured event-loop blocking evidence, diagnose "
            "the root cause of the CPU hot path and explain how to fix it."
        )
        user_prompt = f"""Operation: {blamed_op}
Evidence:
- {evidence.get('per_call_avg_ms', 0):.1f} ms self-time per call
- {evidence.get('invocations', 0)} invocations
- Explains {evidence.get('pct_of_compute_explained', 0):.0f}% of total compute time

Source code:
```python
{source}
```

Provide: (1) what is blocking the event loop, (2) why, (3) how to fix it,
(4) confidence (high/medium/low)."""
    else:
        per_call_mb = evidence.get("per_call_avg", 0) / 1024 / 1024
        system_prompt = (
            "You are a Python memory-profiling expert. Given an operation's source "
            "code and measured memory-attribution evidence, diagnose the root cause "
            "of the memory leak and explain how to fix it."
        )
        user_prompt = f"""Operation: {blamed_op}
Evidence:
- Retained {per_call_mb:.1f} MB per call
- {evidence.get('invocations', 0)} invocations
- Explains {evidence.get('pct_of_growth_explained', 0):.0f}% of total RSS growth

Source code:
```python
{source}
```

Provide: (1) what is happening, (2) why (root cause), (3) how to fix it,
(4) confidence (high/medium/low)."""

    resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "diagnosis",
                "schema": {
                    "type": "object",
                    "properties": {
                        "diagnosis": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "fix_strategy": {"type": "string"},
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["diagnosis", "root_cause", "fix_strategy", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
    )
    return json.loads(resp.choices[0].message.content)


@weave.op()
async def diagnose(enriched: dict) -> dict:
    evidence = enriched.get("evidence", {})
    agent_id = enriched.get("agent_id")
    agent = None
    try:
        if agent_id:
            agent, _ = get_agent_source_sync(agent_id)
        if not agent:
            agent = get_primary_monitored_agent_sync()
            agent_id = agent["id"]
    except Exception:
        agent = None
    entry_point = (agent or {}).get("entry_point") or DEFAULT_ENTRY_POINT
    blamed_op = enriched.get("blamed_op") or entry_point
    incident_type = enriched.get("type", "memory_leak")
    source = read_op_source(blamed_op, agent_id=agent_id)

    proposal = None
    last_err = None
    for attempt in range(2):  # retry once with backoff (spec §5.2)
        try:
            proposal = await _call_llm(blamed_op, evidence, source, incident_type)
            break
        except Exception as e:
            last_err = e
            print(f"[diagnostician] LLM attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(5)

    if proposal is None:
        proposal = {
            "diagnosis": f"Diagnosis failed: {last_err}",
            "root_cause": "LLM call failed - manual review needed.",
            "fix_strategy": "Inspect the blamed op manually.",
            "confidence": "failed",
        }

    proposal["blamed_op"] = blamed_op
    proposal["entry_point"] = entry_point
    proposal["agent_id"] = agent_id
    proposal["agent_name"] = agent.get("display_name") if agent else None
    proposal["evidence"] = evidence
    proposal["code"] = fix_code_diff(
        blamed_op, agent.get("filename", "victim/ops.py") if agent else "victim/ops.py"
    )
    if blamed_op == GROUND_TRUTH["expected_op"]:
        proposal["eval"] = evaluate_diagnosis(proposal, GROUND_TRUTH)
    else:
        proposal["eval"] = {
            "accuracy": None,
            "mentioned_correct_op": None,
            "identified_cause": None,
            "skipped": "No demo ground truth configured for selected entry point.",
        }

    await redis.publish(EVENTS_PROPOSAL, json.dumps(proposal))
    eval_accuracy = proposal["eval"].get("accuracy")
    print(
        f"[diagnostician] proposal published (conf={proposal['confidence']}, "
        f"eval acc={eval_accuracy if eval_accuracy is not None else 'skipped'})"
    )
    return proposal

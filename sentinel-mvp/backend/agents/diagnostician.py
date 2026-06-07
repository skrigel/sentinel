"""Diagnostician agent: the ONLY LLM call in the system (CLAUDE.md #4).

Grounds GPT-4o purely on Redis-derived evidence + the offending op's source,
returns structured JSON, then runs a Weave eval scoring whether it nailed the
known root cause.
"""

import asyncio
import json
import os
import re

import weave

from utils.redis_client import redis
from utils.redis_keys import EVENTS_PROPOSAL

VICTIM_SRC = os.environ.get("VICTIM_SRC_DIR", "/victim_src")
OPS_FILE = os.path.join(VICTIM_SRC, "ops.py")

GROUND_TRUTH = {"expected_op": "process_batch", "expected_cause": "unbounded list"}


def read_op_source(op_name: str) -> str:
    """Extract the source of an async op from the mounted victim ops.py."""
    try:
        with open(OPS_FILE, "r") as f:
            src = f.read()
    except OSError:
        return f"# source unavailable for {op_name}"

    # Grab from `async def <op_name>` to the next top-level dedent (next def or EOF).
    pattern = rf"(async def {re.escape(op_name)}\(.*?)(?=\n    @weave|\n    async def |\nclass |\Z)"
    m = re.search(pattern, src, re.DOTALL)
    if m:
        return m.group(1).rstrip()
    return src  # fall back to the whole module


def _fix_code_diff(blamed_op: str) -> dict | None:
    """The scoped memory beat's concrete fix: unbounded ``conversation_history``
    -> sliding window K=8. Applying the fix flips the victim to the windowed
    branch, so this before/after is the real change the system enacts."""
    if blamed_op != "process_batch":
        return None
    return {
        "file": "victim/ops.py",
        "line": 61,
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


@weave.op()
def evaluate_diagnosis(proposal: dict, ground_truth: dict) -> dict:
    """Weave eval: did the LLM identify the right op and mechanism?"""
    diag_text = (proposal.get("diagnosis", "") + " " + proposal.get("root_cause", "")).lower()
    mentioned_op = ground_truth["expected_op"] in diag_text
    identified_cause = ground_truth["expected_cause"] in diag_text
    score = 0.5 * mentioned_op + 0.5 * identified_cause
    return {
        "accuracy": score,
        "mentioned_correct_op": mentioned_op,
        "identified_cause": identified_cause,
    }


async def _call_llm(blamed_op: str, evidence: dict, source: str) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
    blamed_op = enriched.get("blamed_op") or "process_batch"
    evidence = enriched.get("evidence", {})
    source = read_op_source(blamed_op)

    proposal = None
    last_err = None
    for attempt in range(2):  # retry once with backoff (spec §5.2)
        try:
            proposal = await _call_llm(blamed_op, evidence, source)
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
    proposal["evidence"] = evidence
    proposal["code"] = _fix_code_diff(blamed_op)
    proposal["eval"] = evaluate_diagnosis(proposal, GROUND_TRUTH)

    await redis.publish(EVENTS_PROPOSAL, json.dumps(proposal))
    print(f"[diagnostician] proposal published (conf={proposal['confidence']}, "
          f"eval acc={proposal['eval']['accuracy']})")
    return proposal

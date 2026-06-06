"""Run Sentinel's Weave evaluation over injected memory-leak scenarios.

Verified against weave 0.52.42:
- construct with ``weave.Evaluation(dataset=examples, scorers=scorers)``
- scorers may accept ``output`` plus dataset columns such as ``expected_op``
- execute with ``await evaluation.evaluate(model_op)``
"""

import asyncio
import os
from typing import Any

import weave

import agents.diagnostician as diagnostician
from agents.diagnostician import diagnose
from graph.nodes import n_classify_cause, n_self_test
from utils.weave_client import init_weave


EXAMPLES: list[dict[str, Any]] = [
    {
        "anomaly": {
            "type": "memory_leak",
            "severity": "HIGH",
            "slope": 100.0,
            "attribution": {
                "blamed_op": "process_batch",
                "confidence": "high",
                "evidence": {
                    "cumulative_bytes": 160 * 1024 * 1024,
                    "invocations": 40,
                    "per_call_avg": 4 * 1024 * 1024,
                    "total_rss_growth": 172 * 1024 * 1024,
                    "pct_of_growth_explained": 93.0,
                },
            },
        },
        "expected_op": "process_batch",
        "expected_subcause": "unbounded_collection",
    },
    {
        "anomaly": {
            "type": "memory_leak",
            "severity": "HIGH",
            "slope": 72.0,
            "attribution": {
                "blamed_op": "retrieve_context",
                "confidence": "high",
                "evidence": {
                    "cumulative_bytes": 96 * 1024 * 1024,
                    "invocations": 24,
                    "per_call_avg": 4 * 1024 * 1024,
                    "total_rss_growth": 112 * 1024 * 1024,
                    "pct_of_growth_explained": 86.0,
                },
            },
        },
        "expected_op": "retrieve_context",
        "expected_subcause": "unbounded_collection",
    },
    {
        "anomaly": {
            "type": "memory_leak",
            "severity": "MEDIUM",
            "slope": 48.0,
            "attribution": {
                "blamed_op": "embed_documents",
                "confidence": "high",
                "evidence": {
                    "cumulative_bytes": 64 * 1024 * 1024,
                    "invocations": 32,
                    "per_call_avg": 2 * 1024 * 1024,
                    "total_rss_growth": 76 * 1024 * 1024,
                    "pct_of_growth_explained": 84.0,
                },
            },
        },
        "expected_op": "embed_documents",
        "expected_subcause": "unbounded_collection",
    },
    {
        "anomaly": {
            "type": "memory_leak",
            "severity": "MEDIUM",
            "slope": 36.0,
            "attribution": {
                "blamed_op": "summarize_history",
                "confidence": "high",
                "evidence": {
                    "cumulative_bytes": 48 * 1024 * 1024,
                    "invocations": 16,
                    "per_call_avg": 3 * 1024 * 1024,
                    "total_rss_growth": 60 * 1024 * 1024,
                    "pct_of_growth_explained": 80.0,
                },
            },
        },
        "expected_op": "summarize_history",
        "expected_subcause": "unbounded_collection",
    },
]
DATASET = EXAMPLES


class _NoopRedis:
    async def publish(self, *args, **kwargs):
        return 0


def build_dataset() -> list[dict[str, Any]]:
    return list(EXAMPLES)


def _injected_attribution(anomaly: dict[str, Any]) -> dict[str, Any]:
    attribution = dict(anomaly.get("attribution") or {})
    evidence = dict(attribution.get("evidence") or {})
    return {
        "blamed_op": attribution.get("blamed_op"),
        "confidence": attribution.get("confidence", "high"),
        "evidence": evidence,
    }


@weave.op(name="sentinel.eval.correct_op")
def correct_op(output: dict[str, Any], expected_op: str) -> dict[str, bool]:
    return {"correct_op": output.get("blamed_op") == expected_op}


@weave.op(name="sentinel.eval.correct_subcause")
def correct_subcause(
    output: dict[str, Any], expected_subcause: str
) -> dict[str, bool]:
    return {"correct_subcause": output.get("suspected_subcause") == expected_subcause}


@weave.op(name="sentinel.eval.fix_present")
def fix_present(output: dict[str, Any]) -> dict[str, bool]:
    has_fix_text = bool(
        output.get("fix_strategy")
        or output.get("diagnosis")
        or output.get("root_cause")
    )
    verified = bool((output.get("test_result") or {}).get("tests_passed"))
    return {"fix_present": has_fix_text and verified}


SCORERS = [correct_op, correct_subcause, fix_present]


@weave.op(name="sentinel.eval.model")
async def sentinel_model(
    anomaly: dict[str, Any],
    expected_op: str | None = None,
    expected_subcause: str | None = None,
) -> dict[str, Any]:
    del expected_op, expected_subcause

    original_redis = diagnostician.redis
    diagnostician.redis = _NoopRedis()
    try:
        enriched = _injected_attribution(anomaly)
        proposal = await diagnose(enriched)
    finally:
        diagnostician.redis = original_redis

    blamed_op = proposal.get("blamed_op") or enriched.get("blamed_op")
    classification = await n_classify_cause(
        {"symptom_type": anomaly.get("type"), "blamed_op": blamed_op}
    )
    suspected_subcause = classification.get("suspected_subcause")
    self_test = await n_self_test(
        {
            "anomaly": anomaly,
            "suspected_subcause": suspected_subcause,
            "proposed_fix": proposal,
        }
    )
    return {
        "blamed_op": blamed_op,
        "diagnosis": proposal.get("diagnosis"),
        "root_cause": proposal.get("root_cause"),
        "fix_strategy": proposal.get("fix_strategy"),
        "suspected_subcause": suspected_subcause,
        "test_result": self_test.get("test_result"),
    }


def build_evaluation() -> weave.Evaluation:
    return weave.Evaluation(
        dataset=build_dataset(),
        scorers=SCORERS,
    )


async def _run() -> dict[str, Any] | None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required to run the Sentinel Weave evaluation.")
        return None

    init_weave()
    evaluation = build_evaluation()
    return await evaluation.evaluate(sentinel_model)


def main() -> int:
    summary = asyncio.run(_run())
    if summary is None:
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

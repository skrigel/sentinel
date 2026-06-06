import json

import pytest

from graph import memory
from utils.redis_keys import INCIDENT_VEC_PREFIX


def test_cosine_cases():
    assert memory.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert memory.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert memory.cosine([1, 2], [2, 4]) == pytest.approx(1.0)
    assert memory.cosine([0, 0], [1, 1]) == pytest.approx(0.0)
    assert memory.cosine([], [1, 1]) == pytest.approx(0.0)


def test_most_similar_cases():
    best_id, score = memory.most_similar(
        [1, 0],
        [("weak", [0.2, 0.8]), ("strong", [0.95, 0.05])],
    )
    assert best_id == "strong"
    assert score == pytest.approx(memory.cosine([1, 0], [0.95, 0.05]))
    assert memory.most_similar([1, 0], []) == (None, 0.0)


class FakeRedis:
    def __init__(self, records):
        self.records = records

    async def scan(self, cursor=0, match=None, count=None):
        assert match == f"{INCIDENT_VEC_PREFIX}:*"
        return 0, list(self.records)[:count]

    async def hgetall(self, key):
        return self.records[key]


@pytest.mark.asyncio
async def test_recall_returns_similar_and_ignores_dissimilar(monkeypatch):
    state = {
        "symptom_type": "memory_leak",
        "suspected_subcause": "unbounded_collection",
        "blamed_op": "process_batch",
    }
    monkeypatch.setattr(memory, "embed", lambda text: [1.0, 0.0])
    monkeypatch.setattr(
        memory,
        "redis",
        FakeRedis(
            {
                f"{INCIDENT_VEC_PREFIX}:prior": {
                    "embedding": json.dumps([0.95, 0.05]),
                    "signature": "memory_leak|unbounded_collection|process_batch",
                    "summary": "bound process_batch history",
                    "symptom_type": "memory_leak",
                    "subcause": "unbounded_collection",
                    "blamed_op": "process_batch",
                },
                f"{INCIDENT_VEC_PREFIX}:unrelated": {
                    "embedding": json.dumps([0.0, 1.0]),
                    "signature": "memory_leak|unknown|other_op",
                    "summary": "unrelated fix",
                    "symptom_type": "memory_leak",
                    "subcause": "unknown",
                    "blamed_op": "other_op",
                },
            }
        ),
    )

    hit = await memory.recall(state, threshold=0.85)

    assert hit["id"] == "prior"
    assert hit["summary"] == "bound process_batch history"
    assert hit["similarity"] >= 0.85

    monkeypatch.setattr(
        memory,
        "redis",
        FakeRedis(
            {
                f"{INCIDENT_VEC_PREFIX}:unrelated": {
                    "embedding": json.dumps([0.0, 1.0]),
                    "summary": "unrelated fix",
                }
            }
        ),
    )

    assert await memory.recall(state, threshold=0.85) is None

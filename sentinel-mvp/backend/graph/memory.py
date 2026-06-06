"""Small semantic incident memory for demo-scale recall.

Embeddings are stored in Redis hashes and searched with bounded brute-force
cosine. There is intentionally no vector index dependency here.
"""

import hashlib
import json
import math
import os
import re
from typing import Iterable

from utils.redis_client import redis
from utils.redis_keys import INCIDENT_VEC_PREFIX

EMBEDDING_MODEL = "text-embedding-3-small"
OFFLINE_EMBED_DIM = 64
MAX_RECALL_CANDIDATES = 200

_openai_client = None
_openai_api_key = None


def signature(state) -> str:
    return (
        f"{state.get('symptom_type') or 'unknown'}|"
        f"{state.get('suspected_subcause') or 'unknown'}|"
        f"{state.get('blamed_op') or 'unknown'}"
    )


def _offline_embed(text: str) -> list[float]:
    vec = [0.0] * OFFLINE_EMBED_DIM
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    for token in tokens or [text.lower()]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % OFFLINE_EMBED_DIM
        sign = 1.0 if digest[2] % 2 else -1.0
        vec[idx] += sign
    return vec


def _get_openai_client(api_key: str):
    global _openai_client, _openai_api_key
    if _openai_client is None or _openai_api_key != api_key:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=api_key)
        _openai_api_key = api_key
    return _openai_client


def embed(text: str) -> list[float]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _offline_embed(text)

    client = _get_openai_client(api_key)
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return list(response.data[0].embedding)


def cosine(a, b) -> float:
    pairs = [(float(x), float(y)) for x, y in zip(a or [], b or [])]
    if not pairs:
        return 0.0
    dot = sum(x * y for x, y in pairs)
    norm_a = math.sqrt(sum(x * x for x, _ in pairs))
    norm_b = math.sqrt(sum(y * y for _, y in pairs))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def most_similar(query_vec, candidates: Iterable[tuple[str, list[float]]]):
    best_id = None
    best_score = 0.0
    for candidate_id, vec in candidates:
        score = cosine(query_vec, vec)
        if best_id is None or score > best_score:
            best_id = candidate_id
            best_score = score
    return best_id, best_score


def _summary(state) -> str:
    proposed_fix = state.get("proposed_fix") or {}
    return (
        proposed_fix.get("summary")
        or proposed_fix.get("fix_strategy")
        or proposed_fix.get("diagnosis")
        or "fix verified"
    )


def _incident_id_from_key(key: str) -> str:
    return str(key).split(":", 1)[1]


def _decode_embedding(raw) -> list[float] | None:
    if isinstance(raw, list):
        return [float(value) for value in raw]
    if not raw:
        return None
    decoded = json.loads(raw)
    if not isinstance(decoded, list):
        return None
    return [float(value) for value in decoded]


async def store_incident(state) -> bool:
    try:
        incident_id = state.get("incident_id")
        if not incident_id:
            return False
        sig = signature(state)
        await redis.hset(
            f"{INCIDENT_VEC_PREFIX}:{incident_id}",
            mapping={
                "embedding": json.dumps(embed(sig)),
                "signature": sig,
                "summary": _summary(state),
                "symptom_type": state.get("symptom_type") or "unknown",
                "subcause": state.get("suspected_subcause") or "unknown",
                "blamed_op": state.get("blamed_op") or "unknown",
            },
        )
        return True
    except Exception:
        return False


async def recall(state, threshold=0.85) -> dict | None:
    try:
        query_vec = embed(signature(state))
        cursor = 0
        records = {}
        candidates = []
        while len(candidates) < MAX_RECALL_CANDIDATES:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{INCIDENT_VEC_PREFIX}:*",
                count=min(100, MAX_RECALL_CANDIDATES - len(candidates)),
            )
            for key in keys:
                if len(candidates) >= MAX_RECALL_CANDIDATES:
                    break
                try:
                    record = await redis.hgetall(key)
                    vec = _decode_embedding(record.get("embedding"))
                    if vec is None:
                        continue
                    incident_id = _incident_id_from_key(key)
                    records[incident_id] = dict(record)
                    candidates.append((incident_id, vec))
                except Exception:
                    continue
            if cursor in (0, "0"):
                break

        best_id, score = most_similar(query_vec, candidates)
        if best_id is None or score < threshold:
            return None
        recalled = dict(records.get(best_id, {}))
        recalled["id"] = best_id
        recalled["similarity"] = score
        return recalled
    except Exception:
        return None

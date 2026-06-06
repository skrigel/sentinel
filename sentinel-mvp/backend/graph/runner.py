"""Runtime wrapper around the compiled incident graph.

The compiled graph owns an in-memory checkpointer, so one GraphRunner instance
must serve both the initial anomaly run and the approval resume call.
"""

import time

import weave

from .incident_graph import build_incident_graph


class GraphRunner:
    def __init__(self):
        self._graph = build_incident_graph()
        self._config = None

    @weave.op(name="sentinel.incident.start_from_anomaly")
    async def start_from_anomaly(self, anomaly: dict) -> dict:
        incident_id = f"inc-{int(anomaly.get('start_ts') or time.time())}"
        self._config = {"configurable": {"thread_id": incident_id}}
        initial = {
            "incident_id": incident_id,
            "status": "DETECTED",
            "anomaly": anomaly,
            "symptom_type": anomaly.get("type", "unknown"),
            "evidence": [],
            "attempted_routes": [],
            "rejected_routes": [],
        }
        return await self._graph.ainvoke(initial, config=self._config)

    @weave.op(name="sentinel.incident.approve_and_apply")
    async def approve_and_apply(self) -> dict:
        if self._config is None:
            raise ValueError("No incident awaiting approval")
        return await self._graph.ainvoke(None, config=self._config)

    async def reset(self):
        self._config = None

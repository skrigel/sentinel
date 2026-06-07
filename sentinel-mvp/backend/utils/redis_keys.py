"""Single source of truth for Redis key names (backend copy).

Kept identical to victim/redis_keys.py — these two processes share this
contract. Never hardcode key strings elsewhere.
"""

# Metric streams (time-series, XADD with MAXLEN)
METRICS_RSS = "metrics:rss"
METRICS_LOOPLAG = "metrics:looplag"
METRICS_MAXLEN = 2000

# Cumulative per-op attribution
ATTRIB_MEM = "attrib:mem"  # ZSet {op_name: cumulative_bytes}
ATTRIB_INVOCATIONS = "attrib:invocations"  # Hash {op_name: call_count}

# Baseline for anomaly detection
BASELINE_RSS_SLOPE = "baseline:rss_slope"  # Hash {mean, stddev, samples}

# Incident tracking
INCIDENT_CURRENT = "incident:current"  # Hash {state, data}

# Control flags
VICTIM_MODE = "victim:mode"  # String: "buggy" | "fixed"
SETTINGS_AUTO_APPROVE = "settings:auto_approve"  # String: "1" | "0"

# Pub/sub channels
EVENTS_ANOMALY = "events:anomaly"
EVENTS_ENRICHED = "events:enriched"
EVENTS_PROPOSAL = "events:proposal"
EVENTS_STATE = "events:state"
EVENTS_NARRATION = "events:narration"

# Fix memory
FIX_CACHE_PREFIX = "fix_cache"
INCIDENT_VEC_PREFIX = "incident_vec"

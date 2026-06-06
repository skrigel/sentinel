  Design Section 3: Data Flow & Redis Schema

Redis Data Structures:

  # Metrics (time-series)
  metrics:rss          # Stream: {timestamp, rss_bytes, pid}
  metrics:looplag      # Stream: {timestamp, lag_ms}

  # Attribution (cumulative scores)
  attrib:mem           # ZSet: {op_name: cumulative_bytes}
  attrib:invocations   # Hash: {op_name: call_count}

  # Baseline (for anomaly detection)
  baseline:rss_slope   # Hash: {mean, stddev, samples}

  # Incident tracking
  incident:current     # Hash: {state, anomaly, enriched, proposal, timestamps}

  # Control flags
  victim:mode          # String: "buggy" | "fixed"

  # Pub/Sub channels
  events:anomaly       # {type, start_ts, severity}
  events:enriched      # {blamed_op, evidence}
  events:proposal      # {diagnosis, root_cause, fix_strategy, confidence}
  events:state         # {new_state, timestamp, incident_id}

  Event Flow Sequence:

  1. Victim writes metrics every 2s
     → XADD metrics:rss {ts, rss}
     → XADD metrics:looplag {ts, lag}

  2. Victim ops write attribution
     → ZINCRBY attrib:mem <delta> process_batch
     → HINCRBY attrib:invocations process_batch 1

  3. Detector polls metrics:rss stream
     → Calculates slope on new entry
     → Anomaly detected
     → PUBLISH events:anomaly {...}
     → Supervisor: IDLE → DETECTED

  4. Attributor reacts to events:anomaly
     → ZREVRANGE attrib:mem 0 0 WITHSCORES
     → Top op = process_batch (with evidence)
     → PUBLISH events:enriched {...}
     → Supervisor: DETECTED → ATTRIBUTED (implicit)

  5. Diagnostician reacts to events:enriched
     → Read op source, call OpenAI
     → Run Weave eval on diagnosis
     → PUBLISH events:proposal {...}
     → Supervisor: ATTRIBUTED → DIAGNOSED

  6. Supervisor transitions to AWAITING_APPROVAL
     → PUBLISH events:state {AWAITING_APPROVAL}
     → Frontend displays "Apply Fix" button

  7. User clicks "Apply Fix"
     → POST /api/apply
     → SET victim:mode "fixed"
     → Victim detects change, exits
     → Docker restarts victim in fixed mode
     → Supervisor: AWAITING_APPROVAL → APPLYING

  8. Supervisor waits 30s, samples RSS again
     → Confirms slope < 20% of original
     → PUBLISH events:state {RESOLVED}
     → Frontend shows "✅ Recovery confirmed"

  Baseline Establishment:
  - First 30 seconds of victim runtime: Detector calculates baseline RSS slope
  - Stored in baseline:rss_slope with mean + 3*stddev threshold
  - Anomaly detection starts after baseline established


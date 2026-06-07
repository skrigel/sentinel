// Weave trace and span types matching W&B Weave schema
// Reference: https://weave-docs.wandb.ai/

export interface WeaveSpanAttribute {
  key: string;
  value: string | number | boolean;
}

export interface WeaveSpan {
  span_id: string;
  trace_id: string;
  parent_id: string | null;
  name: string;
  start_time_ms: number;
  end_time_ms: number;
  status: 'ok' | 'error';
  attributes: Record<string, string | number | boolean>;
  // Self-time: time spent in this span excluding children
  self_time_ms?: number;
}

export interface WeaveTrace {
  trace_id: string;
  root_span_id: string;
  spans: WeaveSpan[];
  created_at: number;
  updated_at: number;
  // Metadata
  project_id?: string;
  entity?: string;
}

export interface WeaveTraceMetadata {
  trace_id: string;
  operation: string;
  duration_ms: number;
  status: 'ok' | 'error';
  span_count: number;
}

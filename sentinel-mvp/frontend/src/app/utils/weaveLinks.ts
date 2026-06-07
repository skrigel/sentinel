/**
 * Utility functions for generating Weave trace URLs
 * These generate mock URLs for demo purposes - replace with real Weave domain later
 */

const WEAVE_BASE_URL = 'https://weave.wandb.ai';

/**
 * Generates a Weave trace URL from a trace ID
 * @param traceId - The Weave trace identifier
 * @returns Full URL to view the trace in Weave UI
 */
export function getWeaveTraceUrl(traceId: string): string {
  if (!traceId) {
    throw new Error('traceId is required');
  }
  return `${WEAVE_BASE_URL}/traces/${traceId}`;
}

/**
 * Generates a Weave span URL from trace and span IDs
 * @param traceId - The Weave trace identifier
 * @param spanId - The specific span identifier
 * @returns Full URL to view the span in Weave UI
 */
export function getWeaveSpanUrl(traceId: string, spanId: string): string {
  if (!traceId || !spanId) {
    throw new Error('Both traceId and spanId are required');
  }
  return `${WEAVE_BASE_URL}/traces/${traceId}/spans/${spanId}`;
}

/**
 * Checks if a trace ID is valid (non-empty string)
 * @param traceId - The trace identifier to validate
 * @returns true if valid, false otherwise
 */
export function isValidTraceId(traceId?: string): traceId is string {
  return typeof traceId === 'string' && traceId.length > 0;
}

import { useState, useEffect, useRef, useCallback } from 'react';

interface UsePollingOptions<T> {
  fetchFn: () => Promise<T>;
  interval?: number;
  enabled?: boolean;
}

interface UsePollingResult<T> {
  data: T | null;
  isLoading: boolean;
  error: Error | null;
  lastUpdated: Date | null;
  refetch: () => Promise<void>;
}

/**
 * Custom hook for polling data at regular intervals
 * - Pauses when page is hidden (Page Visibility API)
 * - Resumes when page becomes visible
 * - Handles cleanup on unmount
 *
 * @param options - Configuration object
 * @param options.fetchFn - Async function to fetch data
 * @param options.interval - Polling interval in milliseconds (default: 3000)
 * @param options.enabled - Whether polling is enabled (default: true)
 * @returns Polling state and control functions
 */
export function usePolling<T>({
  fetchFn,
  interval = 3000,
  enabled = true,
}: UsePollingOptions<T>): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const intervalRef = useRef<number | null>(null);
  const isVisibleRef = useRef(true);

  const fetchData = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const result = await fetchFn();
      setData(result);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'));
    } finally {
      setIsLoading(false);
    }
  }, [fetchFn]);

  // Handle visibility change
  useEffect(() => {
    const handleVisibilityChange = () => {
      isVisibleRef.current = !document.hidden;

      if (isVisibleRef.current && enabled) {
        // Page became visible - fetch immediately and restart polling
        fetchData();
      } else if (!isVisibleRef.current && intervalRef.current !== null) {
        // Page became hidden - clear polling
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [fetchData, enabled]);

  // Setup polling
  useEffect(() => {
    if (!enabled) {
      // Clear any existing polling
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    // Initial fetch
    fetchData();

    // Setup interval if page is visible
    if (isVisibleRef.current) {
      intervalRef.current = window.setInterval(() => {
        if (isVisibleRef.current) {
          fetchData();
        }
      }, interval);
    }

    // Cleanup
    return () => {
      if (intervalRef.current !== null) {
        window.clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [fetchData, interval, enabled]);

  return {
    data,
    isLoading,
    error,
    lastUpdated,
    refetch: fetchData,
  };
}

import { useCallback, useEffect, useState } from 'react';

type ApiState<T> = {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Runs an API call and tracks loading/error state, with pull-to-refresh support.
 *
 * `fetcher` is called on mount and on reload. Wrap it in useCallback at the call
 * site, or pass a stable module-level function, so it doesn't refetch every render.
 */
export function useApi<T>(fetcher: () => Promise<T>): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const run = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetcher()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // Guards against setting state after the screen is unmounted mid-request
    return () => {
      cancelled = true;
    };
  }, [fetcher]);

  useEffect(run, [run]);

  return { data, error, loading, reload: run };
}

import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';

type ApiState<T> = {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
};

/**
 * Runs an API call and tracks loading/error state, with pull-to-refresh support.
 *
 * `fetcher` is called whenever the screen gains focus, not just on mount. Tab
 * screens stay mounted once visited, so a mount-only fetch left Portfolio showing
 * "you don't own any shares" after a buy on another tab - every screen here
 * displays something trading can change.
 *
 * Wrap `fetcher` in useCallback at the call site, or pass a stable module-level
 * function, so it doesn't refetch on every render.
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

  // Fires on mount too, since mounting focuses the screen - so this replaces the
  // mount effect rather than adding a second fetch alongside it.
  useFocusEffect(run);

  return { data, error, loading, reload: run };
}

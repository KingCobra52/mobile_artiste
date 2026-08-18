/**
 * Client for the Artiste API (../../api).
 *
 * Types mirror the Pydantic response models in api/models.py. Every
 * snapshot-derived field is nullable there and must stay nullable here: the API's
 * LEFT JOIN LATERAL queries return nulls for artists missing data, and one artist
 * (BunnaB) genuinely has no YouTube signals today.
 */

/**
 * Read from the environment rather than hardcoded, because localhost only works
 * on a simulator - it shares the host's network stack. A physical device over
 * Expo Go needs this pointed at the host machine's LAN address instead, which is
 * then a config change rather than a code change.
 */
export const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export type MarketArtist = {
  id: number;
  name: string | null;
  tier: string | null;
  listeners: number | null;
  playcount: number | null;
  date: string | null;
  price_per_share: number;
};

export type ArtistDetail = MarketArtist & {
  subscribers: number | null;
  recent_videos_avg_views: number | null;
  recent_videos_avg_likes: number | null;
  /**
   * Trailing 14-day growth in the artist's Last.fm signals, as a ratio
   * (0.0178 = +1.78%). This is what the price's momentum term is built from, so
   * it explains which way the price is being pushed. 0 when the artist's history
   * is shorter than the window.
   */
  growth_14d: number;
  /** 0 when not signed in. */
  shares_owned: number;
};

export type PricePoint = {
  /** ISO date, e.g. "2026-07-26". */
  date: string;
  price: number;
};

export type PortfolioHolding = {
  holding_id: number;
  artist_id: number;
  name: string | null;
  tier: string | null;
  shares: number;
  /** What this lot cost per share when bought. */
  price_per_share: number;
  bought_at: string | null;
  current_price: number;
  current_value: number;
  gain_loss: number;
};

export type Portfolio = {
  bars: string;
  holdings_value: number;
  total_gain_loss: number;
  /** One entry per purchase lot, not per artist. */
  holdings: PortfolioHolding[];
};

export type LeaderboardEntry = {
  username: string | null;
  bars: number;
  holdings_value: number;
  net_worth: number;
  is_you: boolean;
};

export type TradeResult = {
  /** NUMERIC in Postgres, serialised as a string to avoid float drift. */
  bars: string;
  shares_owned: number;
  price_per_share: number;
  total: number;
};

export type Profile = {
  id: string;
  username: string | null;
  /** NUMERIC in Postgres, so the API serialises it as a string to avoid float drift. */
  bars: string;
  email: string | null;
};

/**
 * Without this, a request that stalls rather than fails leaves the UI spinning
 * with no way out - fetch has no default timeout. Long enough not to trip on a
 * slow cold start, short enough that a wedged request surfaces as an error the
 * user can retry.
 */
const REQUEST_TIMEOUT_MS = 15_000;

async function request<T>(
  path: string,
  { token, body }: { token?: string; body?: unknown } = {}
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    // An abort means the request stalled; anything else means it never connected.
    // Both need saying, because "nothing happened" is the worst error message.
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error(`The API didn't respond within ${REQUEST_TIMEOUT_MS / 1000}s. Try again.`);
    }
    throw new Error(`Can't reach the API at ${API_BASE_URL}. Is it running?`);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    // The API answers 401 for a missing or expired token; say which, because
    // "401" on a screen the user just signed into is otherwise baffling
    if (response.status === 401) {
      throw new Error('Your session has expired. Sign in again.');
    }
    // Trading rejections carry a human-readable reason ("Not a sufficient amount
    // of bars"); surface it rather than the status code.
    const detail = await response
      .json()
      .then((body) => (typeof body?.detail === 'string' ? body.detail : null))
      .catch(() => null);
    throw new Error(detail ?? `${path} returned ${response.status}`);
  }

  return (await response.json()) as T;
}

export const fetchMarket = () => request<MarketArtist[]>('/market');

export const fetchArtist = (id: number | string, token?: string) =>
  request<ArtistDetail>(`/artists/${id}`, { token });

export const fetchArtistHistory = (id: number | string) =>
  request<PricePoint[]>(`/artists/${id}/history`);

export const fetchProfile = (token: string) => request<Profile>('/me', { token });

export const fetchPortfolio = (token: string) => request<Portfolio>('/portfolio', { token });

/** Public, but pass the token so the caller's own row comes back flagged. */
export const fetchLeaderboard = (token?: string) =>
  request<LeaderboardEntry[]>('/leaderboard', { token });

export const buyShares = (token: string, artistId: number, shares: number) =>
  request<TradeResult>('/buy', { token, body: { artist_id: artistId, shares } });

export const sellShares = (token: string, artistId: number, shares: number) =>
  request<TradeResult>('/sell', { token, body: { artist_id: artistId, shares } });

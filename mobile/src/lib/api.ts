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
  recent_videos_like_ratio: number | null;
};

export type Profile = {
  id: string;
  username: string | null;
  /** NUMERIC in Postgres, so the API serialises it as a string to avoid float drift. */
  bars: string;
  email: string | null;
};

async function getJson<T>(path: string, token?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
  } catch {
    // fetch only rejects on network failure, which for this app almost always
    // means the local API isn't running - worth saying so explicitly
    throw new Error(`Can't reach the API at ${API_BASE_URL}. Is it running?`);
  }

  if (!response.ok) {
    // The API answers 401 for a missing or expired token; say which, because
    // "401" on a screen the user just signed into is otherwise baffling
    if (response.status === 401) {
      throw new Error('Your session has expired. Sign in again.');
    }
    throw new Error(`${path} returned ${response.status}`);
  }

  return (await response.json()) as T;
}

export const fetchMarket = () => getJson<MarketArtist[]>('/market');

export const fetchArtist = (id: number | string) => getJson<ArtistDetail>(`/artists/${id}`);

export const fetchProfile = (token: string) => getJson<Profile>('/me', token);

"""
Response models.

Every snapshot-derived field is optional. The queries reach the snapshot tables
through LEFT JOIN LATERAL, so an artist with no data yet comes back with nulls
rather than disappearing - and one artist (BunnaB) genuinely has null YouTube
signals today, because it has no verified channel and the pipeline's plausibility
guard refuses to record a stranger's numbers for it.

price_per_share is never null: compute_price_per_share() returns 0.0 when every
signal is missing.
"""
from datetime import date

from pydantic import BaseModel


class MarketArtist(BaseModel):
    """One row of the market list."""
    id: int
    name: str | None
    tier: str | None
    listeners: int | None
    playcount: int | None
    date: date | None
    price_per_share: float


class ArtistDetail(BaseModel):
    """A single artist, with the raw signals its price was computed from."""
    id: int
    name: str | None
    tier: str | None
    listeners: int | None
    playcount: int | None
    date: date | None
    subscribers: int | None
    recent_videos_avg_views: int | None
    recent_videos_like_ratio: float | None
    price_per_share: float

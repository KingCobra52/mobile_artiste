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
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class TradeRequest(BaseModel):
    """
    A buy or sell order.

    Replaces parse_shares() (artistev0/app.py:59-68). gt=0 rejects zero, negative,
    and non-numeric share counts at the schema boundary - negative shares were a
    real infinite-money exploit, since they made total_cost negative and credited
    the account instead of charging it.

    Note there is no user_id and no price: identity comes from the verified JWT and
    the price is recomputed server-side, so neither is client-controllable.
    """
    artist_id: int
    shares: int = Field(gt=0)


class TradeResult(BaseModel):
    """What changed, so the UI can update without refetching."""
    bars: Decimal
    shares_owned: int
    price_per_share: float
    total: float


class Profile(BaseModel):
    """The signed-in user's own account."""
    # psycopg3 returns uuid columns as UUID objects, and Pydantic v2 won't coerce
    # those to str. Declaring the real type is both correct and JSON-serialisable.
    id: UUID
    username: str | None
    # bars is NUMERIC(12,2) in Postgres and arrives as Decimal. Kept as Decimal
    # rather than float so a balance never picks up binary rounding error on the
    # way out - this is the number phase 4 spends.
    bars: Decimal
    # From the JWT claims, not the profiles table: email belongs to auth.users
    email: str | None


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
    # 0 for anonymous callers. The sell UI needs this to know what can be sold,
    # which is why it landed here in phase 4 rather than phase 5 as planned.
    shares_owned: int = 0

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
    """A buy or sell order. No user_id or price: those come from the JWT and server-side pricing."""
    artist_id: int
    shares: int = Field(gt=0)


class TradeResult(BaseModel):
    """What changed, so the UI can update without refetching."""
    bars: Decimal
    shares_owned: int
    price_per_share: float
    total: float


class PortfolioHolding(BaseModel):
    """One purchase lot, not one artist. Buying the same artist twice gives two rows."""
    holding_id: int
    artist_id: int
    name: str | None
    tier: str | None
    shares: int
    # What this lot cost per share when bought
    price_per_share: float
    bought_at: date | None
    current_price: float
    current_value: float
    gain_loss: float

    # Signals are selected for pricing but aren't part of the response
    model_config = {"extra": "ignore"}


class PortfolioResponse(BaseModel):
    bars: Decimal
    holdings_value: float
    total_gain_loss: float
    holdings: list[PortfolioHolding]


class LeaderboardEntry(BaseModel):
    username: str | None
    bars: float
    holdings_value: float
    # Ranked on this. Flask ranked on holdings_value alone, which rewarded
    # spending rather than performance.
    net_worth: float
    is_you: bool


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


class PricePoint(BaseModel):
    """One day of an artist's price history."""
    date: date
    price: float


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
    recent_videos_avg_likes: float | None
    price_per_share: float
    # The trailing 14-day growth the price's momentum term is built from, as a
    # ratio (0.0178 = +1.78%) rather than the log the formula works in. Same
    # quantity, expressed the way it gets displayed. 0.0 when the artist's history
    # is shorter than the window.
    growth_14d: float = 0.0
    # 0 for anonymous callers. The sell UI needs this to know what can be sold,
    # which is why it landed here in phase 4 rather than phase 5 as planned.
    shares_owned: int = 0

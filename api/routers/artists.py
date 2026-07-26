"""Read-only artist endpoints: the market list and a single artist's detail."""
from fastapi import APIRouter, Depends, HTTPException

from api.db import get_db
from api.models import ArtistDetail, MarketArtist
from api.pricing import compute_price_per_share

router = APIRouter(tags=["artists"])

# Both queries take the latest row per artist from each snapshot table via
# LEFT JOIN LATERAL, which is index-backed by idx_artist_snapshots_artist_date and
# idx_youtube_snapshots_artist_date. LEFT rather than INNER so an artist with no
# snapshot yet still appears, priced at 0.0, instead of silently vanishing from
# the market - the Flask version used an inner JOIN and dropped them.
MARKET_QUERY = """
    SELECT
        artists.id, artists.name, artists.tier,
        a.listeners, a.playcount, a.date,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_like_ratio
    FROM artists
    LEFT JOIN LATERAL (
        SELECT listeners, playcount, date FROM artist_snapshots
        WHERE artist_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_like_ratio
        FROM youtube_snapshots
        WHERE youtube_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) y ON true
    ORDER BY artists.name
"""

# Keyed on id, not name: artists.name has no unique constraint, so the Flask
# route's WHERE artists.name = %s could match more than one row.
ARTIST_QUERY = """
    SELECT
        artists.id, artists.name, artists.tier,
        a.listeners, a.playcount, a.date,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_like_ratio
    FROM artists
    LEFT JOIN LATERAL (
        SELECT listeners, playcount, date FROM artist_snapshots
        WHERE artist_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_like_ratio
        FROM youtube_snapshots
        WHERE youtube_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) y ON true
    WHERE artists.id = %s
"""


@router.get("/market", response_model=list[MarketArtist])
def market(db=Depends(get_db)):
    rows = db.execute(MARKET_QUERY).fetchall()
    # Priced in Python rather than SQL so compute_price_per_share stays the single
    # source of truth for the formula - no second copy of it living in a query.
    return [dict(row, price_per_share=compute_price_per_share(row)) for row in rows]


@router.get("/artists/{artist_id}", response_model=ArtistDetail)
def artist(artist_id: int, db=Depends(get_db)):
    row = db.execute(ARTIST_QUERY, (artist_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Artist not found")
    return dict(row, price_per_share=compute_price_per_share(row))

"""Read-only artist endpoints: the market list and a single artist's detail."""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import AuthenticatedUser, get_optional_user
from api.db import get_db
from api.models import ArtistDetail, MarketArtist, PricePoint
from api.pricing import SIGNAL_WEIGHTS, compute_price_per_share

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


SHARES_OWNED_QUERY = """
    SELECT COALESCE(SUM(shares), 0) AS total
    FROM holdings WHERE user_id = %s AND artist_id = %s
"""

# One row per Last.fm snapshot date, carrying whichever YouTube snapshot was most
# recent as of that date. Same "latest wins" rule the live endpoints use, applied
# as of a historical date rather than now - a plain join on equal dates would drop
# most days, since the two pipelines don't record on identical schedules.
HISTORY_QUERY = """
    SELECT
        s.date,
        s.listeners, s.playcount,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_like_ratio
    FROM artist_snapshots s
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_like_ratio
        FROM youtube_snapshots y
        WHERE y.artist_id = s.artist_id AND y.date <= s.date
        ORDER BY y.date DESC LIMIT 1
    ) y ON true
    WHERE s.artist_id = %s
    ORDER BY s.date
"""


@router.get("/artists/{artist_id}", response_model=ArtistDetail)
def artist(
    artist_id: int,
    user: AuthenticatedUser | None = Depends(get_optional_user),
    db=Depends(get_db),
):
    row = db.execute(ARTIST_QUERY, (artist_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Artist not found")

    # Optional auth: the artist page is public, but a signed-in caller also gets
    # their own position, which is what the sell control needs.
    shares_owned = 0
    if user is not None:
        shares_owned = db.execute(SHARES_OWNED_QUERY, (user.id, artist_id)).fetchone()["total"]

    return dict(
        row,
        price_per_share=compute_price_per_share(row),
        shares_owned=shares_owned,
    )


def _coverage(row) -> tuple[bool, ...]:
    """Which signals this row actually has. Two rows are only comparable if equal."""
    return tuple(row[name] is not None for name in SIGNAL_WEIGHTS)


@router.get("/artists/{artist_id}/history", response_model=list[PricePoint])
def artist_history(artist_id: int, db=Depends(get_db)):
    """
    Price recomputed at each historical snapshot date, using today's formula and
    divisors throughout - a reconstruction, not a record of what was displayed on
    the day, since both were changed in v1.1.

    Only the most recent run of dates sharing today's signal coverage is returned,
    and that restriction is the point. Renormalization keeps a Last.fm-only price
    and a full-signal price on the same scale, but it does not make them the same
    measurement, so charting across a coverage change draws a cliff where nothing
    happened. Kae is the worst case: 34 days of genuine +0.01 daily gains, then
    -3.52 in a single day when its YouTube data first landed. A reader would see a
    40% crash that never occurred.

    Coverage changes because collection did. Last.fm began 2026-06-12, YouTube
    2026-06-30, and the wrong-channel cleanup nulled ten artists' YouTube signals
    before 2026-07-26. Those artists have one comparable day today and gain one per
    pipeline run, so their charts fill in on their own.
    """
    rows = db.execute(HISTORY_QUERY, (artist_id,)).fetchall()
    if not rows:
        return []

    # Walk back from today while coverage holds, so a flicker in the middle of the
    # history truncates rather than silently splicing two incompatible series.
    current = _coverage(rows[-1])
    comparable = []
    for row in reversed(rows):
        if _coverage(row) != current:
            break
        comparable.append(row)
    comparable.reverse()

    return [
        PricePoint(date=row["date"], price=compute_price_per_share(row))
        for row in comparable
    ]

"""
Recalibrate the SIGNAL_WEIGHTS divisors in api/pricing.py against real data.

Pulls each artist's latest snapshot per signal, takes the median across the
current roster, and prints a SIGNAL_WEIGHTS block ready to paste back into
api/pricing.py.

This lived in artistev0/scripts/ while the Flask app was authoritative, and kept
its own copy of the weights. It now imports them from api.pricing instead, so the
weights exist in exactly one place and only the divisors are ever regenerated.

Run from the mobile_artiste directory:
    app_artiste/bin/python -m api.scripts.calibrate_pricing
"""
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from api.pricing import SIGNAL_WEIGHTS

load_dotenv()

# Same latest-snapshot-per-artist shape the endpoints use, aggregated to a median
# rather than returned per row.
MEDIAN_QUERY = """
    SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY a.listeners) AS listeners,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY a.playcount) AS playcount,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY y.subscribers) AS subscribers,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY y.recent_videos_avg_views)
            AS recent_videos_avg_views,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY y.recent_videos_like_ratio)
            AS recent_videos_like_ratio
    FROM artists
    LEFT JOIN LATERAL (
        SELECT listeners, playcount FROM artist_snapshots
        WHERE artist_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_like_ratio
        FROM youtube_snapshots
        WHERE youtube_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) y ON true
"""


def main() -> None:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL is not set")

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        medians = conn.execute(MEDIAN_QUERY).fetchone()

    print("Medians across current roster:")
    for name, value in medians.items():
        print(f"  {name}: {value}")

    print("\nPaste this into api/pricing.py:\n")
    print("SIGNAL_WEIGHTS = {")
    for name, (weight, _divisor) in SIGNAL_WEIGHTS.items():
        value = medians[name]
        if value is None or value <= 0:
            # A signal every artist is missing would divide by zero; keeping the
            # existing divisor is safer than emitting a broken block.
            print(f"    # {name}: no data available - keeping the current divisor")
            continue
        print(f'    "{name}": ({weight}, math.log1p({float(value)!r})),')
    print("}")


if __name__ == "__main__":
    main()

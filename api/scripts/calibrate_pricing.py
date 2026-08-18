"""
Report how far the roster has drifted from the frozen pricing baseline.

This script used to emit a SIGNAL_WEIGHTS block to paste into api/pricing.py.
That was the wrong tool: adopting a fresh median reprices every open position and
erases market-wide growth, while changing nothing about relative prices. See the
comment above SIGNAL_WEIGHTS for the full reasoning and the safe-rebase procedure.

So this is now diagnostic only. It prints nothing you should paste anywhere.

Useful for answering "has the roster moved away from where we anchored it?" - if
the drift gets large enough to matter, the answer is a deliberate rebase that also
adjusts holdings.price_per_share, not a copy-paste.

Run from the mobile_artiste directory:
    app_artiste/bin/python -m api.scripts.calibrate_pricing
"""
import math
import os

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from api.pricing import PRICE_SCALE, SENSITIVITY, SIGNAL_WEIGHTS

load_dotenv()

# Same latest-snapshot-per-artist shape the endpoints use, aggregated to a median.
MEDIAN_QUERY = """
    SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY a.listeners) AS listeners,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY a.playcount) AS playcount,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY y.subscribers) AS subscribers,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY y.recent_videos_avg_views)
            AS recent_videos_avg_views,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY y.recent_videos_avg_likes)
            AS recent_videos_avg_likes
    FROM artists
    LEFT JOIN LATERAL (
        SELECT listeners, playcount FROM artist_snapshots
        WHERE artist_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_avg_likes
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

    print(f"{'signal':<28}{'frozen baseline':>18}{'roster median':>18}{'drift':>10}")
    print("-" * 74)

    # Adopting the medians would shift the log-space score by this weighted amount,
    # identically for every artist with full signal coverage.
    score_shift = 0.0
    weight_total = 0.0

    for name, (weight, baseline) in SIGNAL_WEIGHTS.items():
        median = medians[name]
        if median is None or median <= 0:
            print(f"{name:<28}{baseline:>18,.1f}{'no data':>18}{'-':>10}")
            continue
        drift = 100 * (median - baseline) / baseline
        print(f"{name:<28}{baseline:>18,.1f}{median:>18,.1f}{drift:>9.1f}%")
        score_shift += weight * (math.log1p(baseline) - math.log1p(float(median)))
        weight_total += weight

    if weight_total:
        # price_new / price_old, identical for every fully-covered artist
        factor = math.exp(SENSITIVITY * score_shift / weight_total)
        print()
        print(f"Adopting these medians would multiply EVERY price by {factor:.6f} "
              f"({100 * (factor - 1):+.2f}%),")
        print("identically for every artist - it moves the price level and nothing else.")
        print(f"A {PRICE_SCALE:.0f}-bar artist would become {PRICE_SCALE * factor:.2f}.")
        print()
        print("That is not an improvement, it is a repricing: every holder's unrealised")
        print("gain would move by the same amount for reasons unrelated to any artist.")
        print("Nothing here is meant to be pasted into api/pricing.py.")


if __name__ == "__main__":
    main()

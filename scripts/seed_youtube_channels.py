"""
Seed artists.youtube_channel_id with the verified official channel for each artist.

Why this exists: the pipeline used to resolve channels by handle, but YouTube
handles are first-come-first-served and reassignable, so 11 of 25 artists were
silently matched to squatters and namesakes (@jid resolved to 'Jamie Davies',
18 subscribers; @drake to a 481-subscriber channel). Those numbers priced the
market for weeks. Channel ids are immutable, so the mapping below is the
authoritative record - it was verified by hand and can't be re-derived from the
artist name alone.

Safe to re-run. By default it only fills in artists that have no channel id yet,
so a manual correction made later isn't clobbered. Pass --force to overwrite
every row with the mapping below.

    python3 scripts/seed_youtube_channels.py
    python3 scripts/seed_youtube_channels.py --force
"""
import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

# name -> (channel_id, channel title and subscriber count when verified 2026-07-26).
# The subscriber counts are a sanity anchor, not a constraint: if a re-check ever
# shows a wildly different number for one of these ids, the channel changed hands
# or was deleted, and the mapping needs another look.
CHANNELS = {
    # Corrected - the handle had resolved to the wrong channel
    "Drake":          ("UCByOQJjav0CUDwxCk-jVNRQ", "Drake, 32.8M"),
    "Travis Scott":   ("UCtxdfwb9wfkoGocVUAJ-Bmg", "Travis Scott, 20.7M"),
    "Future":         ("UCSDvKdIQOwTfcyOimSi9oYA", "Future, 15.0M"),
    "Lil Baby":       ("UCVS88tG_NYgxF6Udnx2815Q", "Lil Baby Official, 10.5M"),
    "Rod Wave":       ("UCenjunBhBhvKjfDAESnoppw", "RodWave, 7.24M"),
    "GloRilla":       ("UC9bZ9eWvF0eXVqrxK9ve7Nw", "theofficialGloRilla, 2.46M"),
    "JID":            ("UC3WIRbOw46MsbycRc1N5x4g", "JID, 1.39M"),
    "JELEEL!":        ("UC5wSitOQZCJVNNDw0-V1PlQ", "JELEEL!, 325K"),
    "fakemink":       ("UCDnRK591TaPlJrHxjA1PL4A", "fakemink, 136K"),
    # Search ranked a 3.24M-subscriber namesake ('KAYE') first; this is the real
    # artist, picked deliberately for its plausible subscribers/listeners ratio
    "Kae":            ("UCzzxeFDHhTrHrLMx-DF2wbQ", "kae, 9.5K"),

    # Already resolving correctly by handle - pinned so they no longer depend on it
    "Kendrick Lamar": ("UC3lBXcrKFnFAFkfVk5WuKcQ", "Kendrick Lamar, 20.3M"),
    "21 Savage":      ("UCOjEHmBKwdS7joWpW0VrXkg", "21 Savage, 10.1M"),
    "J. Cole":        ("UCnc6db-y3IU7CkT_yeVXdVg", "J. Cole, 8.48M"),
    "Central Cee":    ("UCV_CsAy5CNBX_uwDQ7RMe1Q", "Central Cee, 6.98M"),
    "Playboi Carti":  ("UC652oRUvX1onwrrZ8ADJRPw", "Playboi Carti, 4.94M"),
    "Ice Spice":      ("UCJTqwQj5iTHYrko04PbGI9w", "Ice Spice, 3.89M"),
    "Gunna":          ("UCAkIMkEaa9sZmjcy7mfd5lQ", "Gunna, 3.67M"),
    "Don Toliver":    ("UCgT01FILdWB9BsXBXKjpQ7A", "Don Toliver, 2.95M"),
    "Denzel Curry":   ("UCiKxNv_MHAShqT2lATxG_Wg", "Denzel Curry, 1.61M"),
    "Sexyy Red":      ("UC28rc3PHWPJib68G-VqpJ3w", "Sexyy Red, 1.43M"),
    "Baby Keem":      ("UCq0Hi7HpCBCNeKpdKKcQqGQ", "Baby Keem, 1.10M"),
    "Zeddy Will":     ("UC47-wNKFQbYDTBWcdGUGxpw", "Zeddy Will, 907K"),
    "EsDeeKid":       ("UC8jLPGsRRCTaK-PAWIfCrpg", "EsDeeKid, 506K"),
    "Kai Ca$h":       ("UCdNIZ7nY7vOxG_HXGdn3T4Q", "KAI CA$H, 9.19K"),
}

# Artists deliberately left without a channel id. Empty now that BunnaB has been
# dropped from the roster - it never had a verifiable channel, so it priced off
# Last.fm alone and the pipeline logged a rejection on every run.
#
# Anything listed here falls back to handle resolution, which is what produced the
# wrong-channel bug, so entries should be temporary and few.
UNRESOLVED: set[str] = set()


def seed(cursor, force=False):
    updated, skipped, missing = [], [], []

    for name, (channel_id, note) in CHANNELS.items():
        if force:
            cursor.execute(
                "UPDATE artists SET youtube_channel_id = %s WHERE name = %s "
                "AND youtube_channel_id IS DISTINCT FROM %s RETURNING id",
                (channel_id, name, channel_id)
            )
        else:
            cursor.execute(
                "UPDATE artists SET youtube_channel_id = %s WHERE name = %s "
                "AND youtube_channel_id IS NULL RETURNING id",
                (channel_id, name)
            )

        if cursor.fetchone():
            updated.append(f"{name} -> {channel_id}  ({note})")
            continue

        # No row updated: either the artist isn't on the roster, or it already matches
        cursor.execute("SELECT youtube_channel_id FROM artists WHERE name = %s", (name,))
        row = cursor.fetchone()
        if row is None:
            missing.append(name)
        else:
            skipped.append(f"{name} (already {row[0]})")

    return updated, skipped, missing


if __name__ == "__main__":
    force = "--force" in sys.argv

    db_url = os.getenv("DATABASE_URL_IPV4") or os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL is not set")

    conn = psycopg.connect(db_url)
    cursor = conn.cursor()
    updated, skipped, missing = seed(cursor, force=force)
    conn.commit()

    cursor.execute("SELECT name FROM artists WHERE youtube_channel_id IS NULL ORDER BY name")
    unmapped = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"{'Overwrote' if force else 'Set'} {len(updated)} channel id(s):")
    for line in updated:
        print(f"  {line}")
    if skipped:
        print(f"\nLeft alone ({len(skipped)} already correct):")
        for line in skipped:
            print(f"  {line}")
    if missing:
        print(f"\nIn the mapping but not on the roster: {', '.join(missing)}")

    unexpected = [name for name in unmapped if name not in UNRESOLVED]
    print(f"\nStill unmapped: {', '.join(unmapped) if unmapped else 'none'}")
    if unexpected:
        print(f"  WARNING - not in the known-unresolved list: {', '.join(unexpected)}")
        print("  These will fall back to handle resolution, which is how the "
              "wrong-channel bug happened.")

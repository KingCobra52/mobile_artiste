"""
Last.fm top-track collection.

Purely additive: nothing here feeds compute_price_per_share. The point is to bank
history, because history is the one model input that cannot be acquired later -
Last.fm returns today's numbers and has no way to ask what they were last month.
Every day this isn't collecting is a day permanently missing.

Why top tracks specifically. Every signal priced today is cumulative or
near-cumulative - playcount, total views, subscribers - so they all drift upward
forever and say less about an artist each year. Nothing in the market can fall
because an artist got less interesting.

Per-track numbers give the first signal that can. The share of an artist's
listening concentrated in their biggest track is a ratio, not a total: it rises
when one song takes over and falls when a catalogue broadens. Kendrick's top five
sit between 1.86M and 2.32M listeners - a flat, deep catalogue - where an artist
carried by a single hit shows a steep drop from track one to track two. That shape
is invisible to every column currently stored.

Rows are kept forever, deliberately unlike recent_youtube_video_snapshots, which
clean_youtube_recent_snapshots trims to the newest 50 per artist. Trimming makes
that table a rolling window rather than a history - it only reaches back to
2026-07-20 and so is useless for fitting anything. This table exists to be
history, so nothing deletes from it.
"""
import os
import re
import unicodedata
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

lastfm_api_key = os.getenv("LASTFM_API_KEY")

today = date.today()

session = requests.Session()

URL = "http://ws.audioscrobbler.com/2.0/"

# Ten rather than fifty. At 24 artists that is 240 rows a day - about 88k a year,
# which stays comfortable - and the concentration shape this exists to capture is
# entirely in the head of the distribution. The long tail adds storage, not signal.
TOP_N = 10


class LastfmError(Exception):
    """Last.fm answered 200 with an error body, which it does for unknown artists."""


# --- the join key -------------------------------------------------------------
#
# Every use of this table compares a track against ITSELF on an earlier date, so it
# needs an identifier that survives Last.fm relabelling a track. The raw name does
# not: a remaster suffix appearing, a feature credit being added, or punctuation
# changing all produce what looks like a brand new track and an old one vanishing.
# For concentration that reads as the catalogue reshuffling when nothing happened,
# and the smaller the artist the harder it swings the ratio.
#
# The obvious candidate is Last.fm's MusicBrainz id, and it is the wrong choice
# here. Measured across the roster it covers 51% of tracks, skewed exactly the wrong
# way: EsDeeKid 10/10, Kendrick 9/10, Drake 9/10, but Kai Ca$h 2/10, JELEEL! 1/10,
# and Kae 0/10. The artists with no mbid are the small ones - precisely where a
# single rename moves concentration most. Worse, a track that gains an mbid later
# would change key mid-series and break its own history.
#
# So the key is a normalised name, which is always present, and the mbid is stored
# alongside it. That inverts the usual instinct but gives 100% coverage and a stable
# key space, and it keeps the mbid for the job it is actually good at: DETECTING a
# rename. One mbid appearing under two different keys across days is a relabelling,
# which is otherwise invisible.

# Only credits and edition markers are stripped, never a whole parenthetical. A
# remix or a live version is a genuinely different track with its own listener
# count, and folding those together would double-count one and erase the other.
_FEATURE = re.compile(
    r"[\(\[]\s*(?:feat|ft|featuring|with)\b[^\)\]]*[\)\]]|"
    r"\s+-\s+(?:feat|ft|featuring|with)\b.*$",
    re.IGNORECASE,
)
_EDITION = re.compile(
    r"[\(\[]\s*(?:\d{4}\s+)?(?:re-?master(?:ed)?|remaster(?:ed)?\s+\d{4}|"
    r"radio\s+edit|single\s+version|album\s+version|explicit|clean|"
    r"bonus\s+track|deluxe|original\s+mix)\s*[^\)\]]*[\)\]]|"
    r"\s+-\s+(?:\d{4}\s+)?(?:re-?master(?:ed)?|remaster(?:ed)?\s+\d{4}|"
    r"radio\s+edit|single\s+version|album\s+version|explicit|clean|"
    r"bonus\s+track|deluxe|original\s+mix)\s*.*$",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def track_key(name):
    """
    A stable identifier for a track across days.

    Normalisation is deliberately conservative - it removes the things Last.fm
    changes about a label, not the things that distinguish one track from another:

        "HUMBLE."                        -> "humble"
        "Humble"                         -> "humble"
        "Money Trees (feat. Jay Rock)"   -> "money trees"
        "Alright - Remastered 2015"      -> "alright"

    but a remix or a live cut keeps its marker and stays a separate track, because
    it genuinely is one and carries its own listener count.
    """
    if not name:
        return None
    # Compatibility-decompose first so a curly apostrophe and a straight one, or an
    # accented character typed two different ways, land on the same key.
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _FEATURE.sub(" ", text)
    text = _EDITION.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    text = _SPACE.sub(" ", text).strip().lower()
    # Everything stripped means the name was punctuation alone; fall back to the
    # original rather than returning an empty key that would collide with others.
    return text or _SPACE.sub(" ", name).strip().lower()


def describe_request_error(exc):
    """An API failure without the URL. See pipelines/yt_pipeline.py for why."""
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(exc).__name__


def fetch_top_tracks(api_key, artist, limit=TOP_N):
    response = session.get(URL, timeout=30, params={
        "method": "artist.gettoptracks",
        "artist": artist,
        "api_key": api_key,
        "format": "json",
        "limit": limit,
    })
    response.raise_for_status()
    data = response.json()

    # Last.fm reports application-level errors inside a 200, so raise_for_status
    # alone would let an unknown artist through as an empty result.
    if "error" in data:
        raise LastfmError(data.get("message", "unknown error"))

    tracks = data.get("toptracks", {}).get("track", [])
    # A single result comes back as an object rather than a list
    if isinstance(tracks, dict):
        tracks = [tracks]

    out = []
    for rank, track in enumerate(tracks, start=1):
        listeners = track.get("listeners")
        playcount = track.get("playcount")
        name = track.get("name")
        # Last.fm sends "" rather than omitting the field when there is no
        # MusicBrainz id, and an empty string would look like a real shared id
        # linking together every track that lacks one.
        mbid = track.get("mbid") or None
        out.append({
            "rank": rank,
            "name": name,
            "track_key": track_key(name),
            "mbid": mbid,
            # None rather than 0, the same distinction the YouTube pipeline makes:
            # a missing count renormalises away, a literal 0 prices as real silence.
            "listeners": int(listeners) if listeners is not None else None,
            "playcount": int(playcount) if playcount is not None else None,
        })
    return out


# track_name keeps the raw label so a rename stays visible after the fact;
# track_key is what anything joining across dates should use; mbid is stored to
# detect the renames the key is designed to absorb.
TRACK_INSERT = """
    INSERT INTO lastfm_track_snapshots
        (artist_id, rank, track_name, track_key, mbid, listeners, playcount, date)
    SELECT %s, t.rank, t.track_name, t.track_key, t.mbid, t.listeners, t.playcount, %s
    FROM unnest(%s::integer[], %s::text[], %s::text[], %s::text[],
                %s::integer[], %s::integer[])
        AS t(rank, track_name, track_key, mbid, listeners, playcount)
    WHERE NOT EXISTS (
        SELECT 1 FROM lastfm_track_snapshots existing
        WHERE existing.artist_id = %s AND existing.date = %s
    )
"""


def run_pipeline(conn, api_key, artists):
    """
    Returns the number of artists whose top tracks could not be recorded.

    Same contract as the other passes: per-artist failures are caught so one artist
    can't abandon the rest, and the count is what lets pipeline.py exit non-zero so
    a scheduled run can go red.

    Does NOT close the connection - the YouTube pass runs after this one and closes
    it, so closing here would make ordering in pipeline.py load-bearing.
    """
    cursor = conn.cursor()
    failures = 0

    if not api_key:
        print("LASTFM_API_KEY not set, skipping top tracks")
        return len(artists)

    for artist in artists:
        try:
            cursor.execute("SELECT id FROM artists WHERE name = %s", (artist,))
            row = cursor.fetchone()
            if not row:
                print(f"Artist {artist} not found in database, skipping.")
                failures += 1
                continue
            artist_id = row[0]

            tracks = fetch_top_tracks(api_key, artist)
            if not tracks:
                print(f"No top tracks returned for {artist}")
                failures += 1
                continue

            cursor.execute(TRACK_INSERT, (
                artist_id, today,
                [t["rank"] for t in tracks],
                [t["name"] for t in tracks],
                [t["track_key"] for t in tracks],
                [t["mbid"] for t in tracks],
                [t["listeners"] for t in tracks],
                [t["playcount"] for t in tracks],
                artist_id, today,
            ))

            if cursor.rowcount == 0:
                print(f"Today's top tracks already recorded for {artist}")
            else:
                top = tracks[0]
                print(f"Recorded {cursor.rowcount} top tracks for {artist} "
                      f"(#1 {top['name']}, {top['listeners']:,} listeners)")

        except LastfmError as exc:
            print(f"Last.fm rejected top-track lookup for {artist}: {exc}")
            failures += 1
        except requests.RequestException as exc:
            print(f"Top-track request failed for {artist}: {describe_request_error(exc)}")
            failures += 1

    conn.commit()
    return failures

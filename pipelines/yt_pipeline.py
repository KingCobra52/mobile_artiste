import psycopg
import requests
import os
from dotenv import load_dotenv
from datetime import date
load_dotenv()

yt_api_key = os.getenv("YOUTUBE_API_KEY")

today = date.today()

# One HTTP session for the whole run so API calls reuse a keep-alive connection
session = requests.Session()

def describe_request_error(exc):
    """
    An API failure without the URL that caused it.

    requests puts the full request URL in its exception message, and these URLs
    carry api_key= in the query string - so the obvious `print(exc)` publishes the
    key the moment a call fails. That was survivable while this ran by hand on a
    laptop. It runs in GitHub Actions on a PUBLIC repo now, where job logs are
    world-readable, and Actions' secret masking is an exact-string match that a
    value pasted with a stray space would slip straight past.
    """
    response = getattr(exc, "response", None)
    if response is not None:
        return f"HTTP {response.status_code}"
    return type(exc).__name__


class handleNotFoundError(Exception):
    pass

class ImplausibleChannelError(Exception):
    """The resolved channel's audience doesn't match the artist's Last.fm reach."""
    pass

# YouTube handles are first-come-first-served and can be reassigned, so looking a
# channel up by handle lands on whichever squatter or namesake claimed the name -
# @jid was 'Jamie Davies' (18 subs), @glorilla was 'Julie J' (0 subs). Channel ids
# (UC...) are immutable, so artists.youtube_channel_id is the preferred key and the
# handle is only a fallback for artists that haven't been resolved yet.
def fetch_channel_stats(api_key, channel_id=None, handle=None):
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {"part": "statistics,snippet,contentDetails", "key": api_key}
    if channel_id:
        params["id"] = channel_id
    elif handle:
        params["forHandle"] = f"@{handle}"
    else:
        raise ValueError("one of channel_id or handle is required")

    response = session.get(url, params=params)
    # Surface quota/auth failures as HTTP errors instead of a misleading "not found"
    response.raise_for_status()
    data = response.json()

    if "items" not in data or len(data["items"]) == 0:
        raise handleNotFoundError

    channel_data = data["items"][0]
    stats = channel_data["statistics"]
    videos_playlist = channel_data["contentDetails"]["relatedPlaylists"]["uploads"]

    # None means "unknown", which compute_price_per_share renormalizes away.
    # A literal 0 would instead be priced as a real audience of zero.
    if stats.get("hiddenSubscriberCount", False) or "subscriberCount" not in stats:
        sub_count = None
    else:
        sub_count = int(stats["subscriberCount"])

    view_count = int(stats["viewCount"]) if "viewCount" in stats else None
    video_count = int(stats["videoCount"]) if "videoCount" in stats else None

    return {
        "channel_id": channel_data["id"],
        "channel_title": channel_data["snippet"]["title"],
        "subscriber_count": sub_count,
        "view_count": view_count,
        "video_count": video_count,
        "videos_playlist": videos_playlist,
    }

# A channel matched to the wrong artist wrote "Drake has 481 subscribers" for weeks
# without anything noticing. Last.fm listeners are an independent measure of the same
# artist, so a channel whose audience is a tiny fraction of it is the wrong channel.
# Thresholds are calibrated against the roster's correctly-matched artists, whose
# lowest subscribers/listeners ratio is ~0.18; every bad match sat below 0.05.
LISTENER_FLOOR = 50_000
MIN_SUBS_TO_LISTENERS = 0.05

def check_channel_plausible(artist, subscribers, listeners):
    if subscribers is None or listeners is None:
        return
    if listeners < LISTENER_FLOOR:
        return
    if subscribers < listeners * MIN_SUBS_TO_LISTENERS:
        raise ImplausibleChannelError(
            f"{subscribers:,} subscribers against {listeners:,} Last.fm listeners "
            f"(ratio {subscribers / listeners:.4f}, floor {MIN_SUBS_TO_LISTENERS})"
        )

def recent_uploads_data(videos_playlist_id, api_key):
    url = "https://www.googleapis.com/youtube/v3/playlistItems"

    params = {
        "part": "contentDetails",
        "playlistId": videos_playlist_id,
        "maxResults": 50,
        "key": api_key
    }

    response = session.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    if "items" not in data or len(data["items"]) == 0:
        return []

    video_ids = []
    for item in data["items"]:
        video_ids.append(item["contentDetails"]["videoId"])

    return video_ids

def video_stats_batch(video_ids, api_key):
    """
    Fetch view/like counts for many videos at once. The videos endpoint accepts up
    to 50 comma-separated ids per request, so this costs 1 HTTP call per 50 videos
    instead of 1 per video. Videos missing from the response (deleted/private) are
    simply absent from the returned dict.
    """
    url = "https://www.googleapis.com/youtube/v3/videos"

    stats_by_id = {}
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start:start + 50]
        params = {
            "part": "statistics",
            "id": ",".join(chunk),
            "key": api_key
        }

        response = session.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            statistics = item["statistics"]
            stats_by_id[item["id"]] = {
                "views": int(statistics.get("viewCount", 0)),
                "likes": int(statistics.get("likeCount", 0)),
            }

    return stats_by_id


# How many of each artist's most recent uploads get a row per day. Twenty rather
# than fifty because the table is now permanent: 20 x 24 artists x 365 days is about
# 175k rows a year, where fifty would be 438k, and the extra thirty videos are the
# tail of a release schedule rather than anything a model would read.
#
# Note this is a STORAGE limit only. recent_videos_avg_views is still averaged over
# the full fifty the API returns, so changing this number does not move any price.
VIDEOS_STORED_PER_ARTIST = 20


# Deliberately no cleanup function.
#
# There used to be one - it kept only the newest 50 rows per artist, which sounds
# like a retention policy but was closer to a delete-everything: 50 rows per artist
# is exactly one day's worth, so the table held a single snapshot and reached back
# no further than the last run. It could never answer a question about the past.
#
# Keeping the history is what makes per-video velocity possible, and that matters
# because recent_videos_avg_views averages over a CHANGING SET of videos: when a new
# upload enters the window the average jumps, which is why that signal produces 71%
# of all daily price movement out of 1% of days, with a single-day maximum of 53.68%.
# Following the same videos over time measures growth without the re-roll artifact.
#
# Storage is not the constraint - Postgres will not notice 175k rows a year - and
# nothing here is redundant: zero percent of day-pairs carry an identical view
# count, so every row is a new measurement rather than a repeat of the last one.

# Inserts a whole batch of video rows in one statement, skipping any video already
# snapshotted today (the WHERE NOT EXISTS replaces the old per-video SELECT EXISTS)
VIDEO_SNAPSHOT_INSERT = """
    INSERT INTO recent_youtube_video_snapshots
        (artist_id, video_id, view_count, like_count, date)
    SELECT %s, v.video_id, v.view_count, v.like_count, %s
    FROM unnest(%s::text[], %s::integer[], %s::integer[]) AS v(video_id, view_count, like_count)
    WHERE NOT EXISTS (
        SELECT 1 FROM recent_youtube_video_snapshots existing
        WHERE existing.video_id = v.video_id AND existing.date = %s
    )
"""

def run_pipeline(conn, api_key, artists, num_videos=VIDEOS_STORED_PER_ARTIST):
    """
    Returns the number of artists whose YouTube data could not be recorded.

    num_videos is how many of each artist's most recent uploads get stored. It no
    longer controls a delete - nothing is deleted now - so it only decides how much
    of each day's fetch is written down.

    The count exists because this runs unattended on a schedule now. Every failure
    below is caught so one artist can't abandon the other 23, which is right - but
    it also meant the process exited 0 no matter what, so a run where all 24 failed
    looked exactly like a clean one. The caller turns a non-zero count into a
    non-zero exit status, which is the only thing a scheduler can see.
    """
    cursor = conn.cursor()
    failures = 0

    #getting subscriberCount and viewCount
    for artist in artists:
        artist_handle = None
        try:
            # Prefer the immutable channel id; the handle is only a fallback
            cursor.execute(
                "SELECT id, youtube_handle, youtube_channel_id FROM artists WHERE name = %s",
                (artist,)
            )
            row = cursor.fetchone()
            if not row:
                print(f"Artist {artist} not found in database, skipping.")
                failures += 1
                continue

            artist_id, artist_handle, channel_id = row

            # Fallback if no handle is configured in the database
            if not artist_handle:
                artist_handle = artist.lower().replace(" ", "")

            if channel_id:
                print(f"Processing YouTube stats for {artist} using channel {channel_id}...")
            else:
                print(f"Processing YouTube stats for {artist} using handle @{artist_handle} "
                      f"(no channel id set - resolution may be wrong)...")

            basic_stats = fetch_channel_stats(api_key, channel_id=channel_id, handle=artist_handle)
            subscribers = basic_stats["subscriber_count"]
            total_views = basic_stats["view_count"]
            videos_playlist_id = basic_stats["videos_playlist"]

            # Cross-check against Last.fm before trusting anything from this channel
            cursor.execute(
                "SELECT listeners FROM artist_snapshots WHERE artist_id = %s "
                "ORDER BY date DESC LIMIT 1",
                (artist_id,)
            )
            listeners_row = cursor.fetchone()
            check_channel_plausible(artist, subscribers, listeners_row[0] if listeners_row else None)

            # Recent-video metrics are a separate set of API calls, and they fail
            # independently (a channel with no uploads 404s here). Their failure must
            # not discard the subscriber/view data already fetched above.
            video_ids = []
            try:
                video_ids = recent_uploads_data(videos_playlist_id, api_key)
                video_stats = video_stats_batch(video_ids, api_key)
            except requests.RequestException as exc:
                print(f"  recent-video stats unavailable for {artist}: "
                      f"{describe_request_error(exc)}")
                video_stats = {}

            if video_stats:
                # Sliced from video_ids rather than from video_stats, because the
                # playlist returns uploads newest-first and that order is the whole
                # basis for "the 20 most recent". The dict's order follows the stats
                # response, which is not guaranteed to preserve it.
                stored_ids = [vid for vid in video_ids if vid in video_stats][:num_videos]
                cursor.execute(
                    VIDEO_SNAPSHOT_INSERT,
                    (
                        artist_id,
                        today,
                        stored_ids,
                        [video_stats[vid]["views"] for vid in stored_ids],
                        [video_stats[vid]["likes"] for vid in stored_ids],
                        today,
                    )
                )

            # Averaged over everything fetched, not just what was stored. Keeping
            # these separate is what makes the storage limit free to change: the
            # signal that feeds compute_price_per_share stays on the same 50-video
            # basis it has always used, so no price moves.
            video_count = len(video_stats)

            if video_count > 0:
                recent_views_total = sum(stats["views"] for stats in video_stats.values())
                recent_likes_total = sum(stats["likes"] for stats in video_stats.values())
                recent_videos_avg_views = int(recent_views_total / video_count)
                recent_videos_like_ratio = float(recent_likes_total / video_count)
            else:
                # NULL, not 0: compute_price_per_share renormalizes away a missing
                # signal, but prices a literal 0 as "this artist's videos get no views"
                recent_videos_avg_views = None
                recent_videos_like_ratio = None

            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM youtube_snapshots WHERE artist_id = %s AND date = %s)",
                (artist_id, today)
            )
            snapshot_exists = cursor.fetchone()[0]

            if snapshot_exists:
                print(f"Today's youtube snapshot already added for {artist}")
            else:
                cursor.execute(
                    """INSERT INTO youtube_snapshots
                       (artist_id, subscribers, total_views, recent_videos_avg_views, recent_videos_like_ratio, date)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (artist_id, subscribers, total_views, recent_videos_avg_views, recent_videos_like_ratio, today)
                )
                print(f"Added youtube snapshot for {artist} for {today}")

        except handleNotFoundError:
            print(f"No YouTube channel found for handle: @{artist_handle}")
            failures += 1
        except ImplausibleChannelError as exc:
            # Loud, because this means the artist is mapped to the wrong channel and
            # will keep pricing off a stranger's audience until someone fixes it.
            # Counted as a failure deliberately: this is the condition that went
            # unnoticed for weeks and priced Drake 16th of 25. If it ever becomes
            # chronic the fix is artists.youtube_channel_id, not muting the check.
            print(f"!! REJECTED YouTube snapshot for {artist}: {exc}")
            print(f"!! Check artists.youtube_channel_id for {artist} - likely the wrong channel.")
            failures += 1
        except requests.RequestException as exc:
            # One artist's API failure shouldn't discard the whole run's work
            print(f"YouTube API request failed for {artist}: {describe_request_error(exc)}")
            failures += 1

    conn.commit()
    conn.close()
    return failures


if __name__ == "__main__":
    import sys

    try:
        from pipelines.pipeline import artists
    except ImportError:
        from pipeline import artists

    conn = psycopg.connect(os.getenv("DATABASE_URL"))
    yt_failures = run_pipeline(conn, yt_api_key, artists)

    print(f"\nYouTube: {len(artists) - yt_failures}/{len(artists)} artists recorded, "
          f"{yt_failures} failed")
    sys.exit(1 if yt_failures else 0)

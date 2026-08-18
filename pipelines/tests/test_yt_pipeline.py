#check if the api is pulling data correctly and adding them into the database
#check whether the api will not pull data for the same video on the same day in recent_youtube_video_snapshots
import os
from unittest.mock import patch, MagicMock

import pytest
import requests

from pipelines.yt_pipeline import (
    ImplausibleChannelError,
    check_channel_plausible,
    fetch_channel_stats,
    recent_uploads_data,
    run_pipeline,
    video_stats_batch,
)

yt_api_key = os.getenv("YOUTUBE_API_KEY")

CHANNEL_STATS = {
    "channel_id": "fake_channel_id",
    "channel_title": "Fake Channel",
    "subscriber_count": 2000,
    "view_count": 10000,
    "video_count": 10,
    "videos_playlist": "fake_playlist_id",
}

# Below LISTENER_FLOOR, so the plausibility guard abstains and these tests
# exercise the insert path rather than the guard.
ARTIST_ROW = (1, "kendricklamar", "UCfake")
LISTENERS_ROW = (20000,)


@patch("pipelines.yt_pipeline.session.get")
def test_fetch_channel_stats_by_handle(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [{
            "id": "fake_channel_id",
            "snippet": {"title": "Kendrick Lamar"},
            "statistics": {"subscriberCount": "2000", "viewCount": "50", "videoCount": "3"},
            "contentDetails": {"relatedPlaylists": {"uploads": "fake_url"}}
        }]
    }
    mock_get.return_value = mock_response
    stats = fetch_channel_stats("api_key_placeholder", handle="kendricklamar")

    assert stats["subscriber_count"] == 2000
    assert stats["videos_playlist"] == "fake_url"
    assert stats["channel_id"] == "fake_channel_id"
    # Resolved by handle, not id
    assert mock_get.call_args[1]["params"]["forHandle"] == "@kendricklamar"


@patch("pipelines.yt_pipeline.session.get")
def test_fetch_channel_stats_prefers_channel_id(mock_get):
    # Handles are squattable; a stored channel id must win over the handle
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [{
            "id": "UCreal",
            "snippet": {"title": "Real Artist"},
            "statistics": {"subscriberCount": "9", "viewCount": "1", "videoCount": "1"},
            "contentDetails": {"relatedPlaylists": {"uploads": "u"}}
        }]
    }
    mock_get.return_value = mock_response
    fetch_channel_stats("k", channel_id="UCreal", handle="squatted")

    params = mock_get.call_args[1]["params"]
    assert params["id"] == "UCreal"
    assert "forHandle" not in params


@patch("pipelines.yt_pipeline.session.get")
def test_fetch_channel_stats_hidden_or_missing_subs_is_none(mock_get):
    # None renormalizes away in pricing; 0 would price as a real audience of zero
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [{
            "id": "c",
            "snippet": {"title": "t"},
            "statistics": {"hiddenSubscriberCount": True, "viewCount": "5", "videoCount": "1"},
            "contentDetails": {"relatedPlaylists": {"uploads": "u"}}
        }]
    }
    mock_get.return_value = mock_response
    assert fetch_channel_stats("k", handle="h")["subscriber_count"] is None

    mock_response.json.return_value["items"][0]["statistics"] = {"viewCount": "5"}
    assert fetch_channel_stats("k", handle="h")["subscriber_count"] is None


@patch("pipelines.yt_pipeline.session.get")
def test_recent_uploads_data(mock_get):
    videos_playlist_id = "fake_playlist_id"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {"contentDetails": {"videoId": "fake_video_id"}}
        ]
    }

    mock_get.return_value = mock_response
    video_ids = recent_uploads_data(videos_playlist_id, "api_key_placeholder")

    assert type(video_ids[0]) == str
    assert video_ids[0] == "fake_video_id"

@patch("pipelines.yt_pipeline.session.get")
def test_video_stats_batch(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "items": [
            {"id": "video_1", "statistics": {"viewCount": "1000", "likeCount": "50"}},
            {"id": "video_2", "statistics": {"viewCount": "300", "likeCount": "7"}}
        ]
    }
    mock_get.return_value = mock_response
    stats = video_stats_batch(["video_1", "video_2"], "api_key_placeholder")

    # Both videos fetched in a single HTTP request
    assert mock_get.call_count == 1
    assert stats["video_1"] == {"views": 1000, "likes": 50}
    assert stats["video_2"] == {"views": 300, "likes": 7}

    # Videos missing from the response are simply absent from the result
    mock_response.json.return_value = {"items": []}
    assert video_stats_batch(["gone_video"], "api_key_placeholder") == {}

@patch("pipelines.yt_pipeline.session.get")
def test_video_stats_batch_chunks_requests(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {"items": []}
    mock_get.return_value = mock_response

    # 120 ids -> 3 requests of at most 50 ids each
    video_stats_batch([f"video_{i}" for i in range(120)], "api_key_placeholder")
    assert mock_get.call_count == 3


# --- plausibility guard -------------------------------------------------------
# Regression coverage for the wrong-channel bug: handle resolution matched 11 of
# 25 artists to squatters and namesakes (@jid -> 'Jamie Davies', 18 subscribers),
# and the pipeline wrote those numbers for weeks without complaint.

def test_plausibility_rejects_squatted_channel():
    # The real Drake case: 6.8M Last.fm listeners, 481 subscribers
    with pytest.raises(ImplausibleChannelError):
        check_channel_plausible("Drake", 481, 6862144)


def test_plausibility_rejects_plausible_looking_namesake():
    # The Travis Scott case: channel title matches exactly, only magnitude betrays it
    with pytest.raises(ImplausibleChannelError):
        check_channel_plausible("Travis Scott", 130000, 3427216)


def test_plausibility_accepts_correctly_matched_artists():
    check_channel_plausible("Kendrick Lamar", 20300000, 5214021)
    check_channel_plausible("EsDeeKid", 505000, 1063328)  # lowest passing ratio on the roster


def test_plausibility_abstains_on_small_or_unknown():
    # Genuinely small artists can't be judged by ratio
    check_channel_plausible("Kai Ca$h", 9190, 50341)
    # Hidden subscriber counts and artists with no Last.fm row aren't failures
    check_channel_plausible("X", None, 5000000)
    check_channel_plausible("X", 5, None)


# --- run_pipeline -------------------------------------------------------------

@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_inserts_data(mock_video_stats, mock_recent_uploads, mock_channel_stats):
    # Mock database connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # Mock fetching behavior:
    # 1. artist row -> (id, handle, channel_id)
    # 2. latest Last.fm listeners, for the plausibility cross-check
    # 3. SELECT EXISTS channel snapshot -> returns (False,)
    mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (False,)]

    # Mock the API handlers
    mock_channel_stats.return_value = dict(CHANNEL_STATS)
    mock_recent_uploads.return_value = ["video_1"]
    mock_video_stats.return_value = {"video_1": {"views": 100, "likes": 10}}

    # Run the pipeline for a single artist
    run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"], 5)

    # Verify connection commits and closes
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()

    # artist SELECT, listeners SELECT, batched video INSERT, EXISTS check,
    # snapshot INSERT. No cleanup DELETE - the video history is kept now.
    assert mock_cursor.execute.call_count == 5

    # Verify the SQL strings of the inserts
    sql_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
    assert any("INSERT INTO recent_youtube_video_snapshots" in sql for sql in sql_calls)
    assert any("INSERT INTO youtube_snapshots" in sql for sql in sql_calls)

    # The channel snapshot stores the channel's total view count, not the recent-video sum
    snapshot_insert = next(
        call for call in mock_cursor.execute.call_args_list
        if "INSERT INTO youtube_snapshots" in call[0][0]
    )
    assert snapshot_insert[0][1][2] == 10000


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_skips_duplicates(mock_video_stats, mock_recent_uploads, mock_channel_stats):
    # Mock database connection and cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (True,)]

    # Mock the API handlers
    mock_channel_stats.return_value = dict(CHANNEL_STATS)
    mock_recent_uploads.return_value = ["video_1"]
    mock_video_stats.return_value = {"video_1": {"views": 100, "likes": 10}}

    # Run the pipeline for a single artist
    run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"], 5)

    sql_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]

    # No channel snapshot inserted when today's already exists
    assert not any("INSERT INTO youtube_snapshots" in sql for sql in sql_calls)

    # The batched video insert dedupes same-day rows inside the statement itself
    video_insert = next(sql for sql in sql_calls if "INSERT INTO recent_youtube_video_snapshots" in sql)
    assert "NOT EXISTS" in video_insert


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_writes_null_not_zero_when_no_videos(
    mock_video_stats, mock_recent_uploads, mock_channel_stats
):
    # Regression: writing 0 priced the artist as having a real audience of zero,
    # instead of letting compute_price_per_share renormalize the missing signal away
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (False,)]

    mock_channel_stats.return_value = dict(CHANNEL_STATS)
    mock_recent_uploads.return_value = []
    mock_video_stats.return_value = {}

    run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"], 5)

    snapshot_insert = next(
        call for call in mock_cursor.execute.call_args_list
        if "INSERT INTO youtube_snapshots" in call[0][0]
    )
    params = snapshot_insert[0][1]
    assert params[3] is None, "recent_videos_avg_views must be NULL, not 0"
    assert params[4] is None, "recent_videos_avg_likes must be NULL, not 0"


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_keeps_subscribers_when_uploads_fetch_fails(
    mock_video_stats, mock_recent_uploads, mock_channel_stats
):
    # Regression: a 404 on the uploads playlist used to abort the whole artist,
    # discarding the subscriber and view counts that had already been fetched
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (False,)]

    mock_channel_stats.return_value = dict(CHANNEL_STATS)
    mock_recent_uploads.side_effect = requests.HTTPError("404 Client Error: Not Found")

    run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"], 5)

    snapshot_insert = next(
        call for call in mock_cursor.execute.call_args_list
        if "INSERT INTO youtube_snapshots" in call[0][0]
    )
    params = snapshot_insert[0][1]
    assert params[1] == 2000, "subscribers must survive a recent-video fetch failure"
    assert params[2] == 10000, "total_views must survive a recent-video fetch failure"
    assert params[3] is None and params[4] is None


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_rejects_implausible_channel(
    mock_video_stats, mock_recent_uploads, mock_channel_stats
):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    # 481 subscribers against 6.8M listeners - the Drake case
    mock_cursor.fetchone.side_effect = [ARTIST_ROW, (6862144,), (False,)]

    mock_channel_stats.return_value = dict(CHANNEL_STATS, subscriber_count=481)
    mock_recent_uploads.return_value = ["video_1"]
    mock_video_stats.return_value = {"video_1": {"views": 100, "likes": 10}}

    run_pipeline(mock_conn, "fake_api_key", ["Drake"], 5)

    sql_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
    assert not any("INSERT INTO youtube_snapshots" in sql for sql in sql_calls), \
        "a channel that fails the cross-source check must not be recorded"


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_never_deletes_video_history(
    mock_video_stats, mock_recent_uploads, mock_channel_stats
):
    """
    There used to be a cleanup pass trimming the table to the newest N rows per
    artist. N was 50, which is exactly one day's worth, so it kept a single snapshot
    and the table could never answer a question about the past. Deleting is now the
    one thing this must not do - the history is the point.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (False,)]

    mock_channel_stats.return_value = dict(CHANNEL_STATS)
    mock_recent_uploads.return_value = ["video_1"]
    mock_video_stats.return_value = {"video_1": {"views": 100, "likes": 10}}

    run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"])

    sql_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
    assert not any("DELETE" in sql for sql in sql_calls), \
        "video history must never be deleted"


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_run_pipeline_stores_only_the_newest_videos(
    mock_video_stats, mock_recent_uploads, mock_channel_stats
):
    """
    num_videos caps STORAGE, taking the newest uploads first. The playlist returns
    newest-first and that ordering is the whole basis for the cap, so the slice has
    to come from the upload list rather than from the stats dict.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (False,)]

    ids = [f"video_{i}" for i in range(10)]
    mock_channel_stats.return_value = dict(CHANNEL_STATS)
    mock_recent_uploads.return_value = ids
    mock_video_stats.return_value = {vid: {"views": 100, "likes": 10} for vid in ids}

    run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"], num_videos=3)

    video_insert = next(
        call for call in mock_cursor.execute.call_args_list
        if "INSERT INTO recent_youtube_video_snapshots" in call[0][0]
    )
    stored = video_insert[0][1][2]
    assert stored == ["video_0", "video_1", "video_2"], "newest three, in upload order"


@patch("pipelines.yt_pipeline.fetch_channel_stats")
@patch("pipelines.yt_pipeline.recent_uploads_data")
@patch("pipelines.yt_pipeline.video_stats_batch")
def test_storage_cap_does_not_change_the_priced_average(
    mock_video_stats, mock_recent_uploads, mock_channel_stats
):
    """
    recent_videos_avg_views is averaged over everything FETCHED, not what was
    stored. Keeping those separate is what makes the storage cap free to change -
    otherwise adjusting it would silently reprice the whole market.
    """
    ids = [f"video_{i}" for i in range(10)]
    stats = {vid: {"views": 100, "likes": 10} for vid in ids}

    def avg_for(num_videos):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [ARTIST_ROW, LISTENERS_ROW, (False,)]
        mock_channel_stats.return_value = dict(CHANNEL_STATS)
        mock_recent_uploads.return_value = ids
        mock_video_stats.return_value = stats

        run_pipeline(mock_conn, "fake_api_key", ["Kendrick Lamar"], num_videos=num_videos)

        snapshot = next(
            call for call in mock_cursor.execute.call_args_list
            if "INSERT INTO youtube_snapshots" in call[0][0]
        )
        return snapshot[0][1][3]

    assert avg_for(3) == avg_for(10) == 100

"""
Tests for the Last.fm top-track pass.

Most of these are about track_key. It is the join key for every cross-date
comparison this table exists to support, and it fails silently: a key that drifts
makes one track look like it vanished and another appeared, which reads as the
catalogue reshuffling on a day nothing happened.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from pipelines.tracks_pipeline import (
    LastfmError,
    fetch_top_tracks,
    run_pipeline,
    track_key,
)

ARTIST_ROW = (1,)


# --- track_key: things that must collapse to the same key ---------------------

@pytest.mark.parametrize("a,b", [
    # Punctuation and case are the most common drift, and Kendrick's catalogue is
    # full of it - "HUMBLE." is how Last.fm writes it today.
    ("HUMBLE.", "Humble"),
    ("PRIDE.", "pride"),
    ("Money Trees", "money trees"),
    # Feature credits get added and removed constantly
    ("Money Trees (feat. Jay Rock)", "Money Trees"),
    ("Alright [ft. Pharrell]", "Alright"),
    ("Not Like Us - feat. Someone", "Not Like Us"),
    ("Poetic Justice (with Drake)", "Poetic Justice"),
    # Edition markers appear when a catalogue is reissued
    ("Alright - Remastered 2015", "Alright"),
    ("Alright (Remastered)", "Alright"),
    ("m.A.A.d city - Radio Edit", "m.A.A.d city"),
    ("Swimming Pools (Album Version)", "Swimming Pools"),
    # Typographic variants of the same character
    ("Don't Kill My Vibe", "Don’t Kill My Vibe"),
])
def test_track_key_absorbs_relabelling(a, b):
    assert track_key(a) == track_key(b)


# --- track_key: things that must NOT collapse ---------------------------------

@pytest.mark.parametrize("a,b", [
    # A remix is a different track with its own listener count. Folding it into the
    # original would double-count one and erase the other, which is a worse error
    # than the rename this normalisation exists to fix.
    ("Money Trees", "Money Trees (Remix)"),
    ("Alright", "Alright (Live)"),
    ("HUMBLE.", "HUMBLE. (Skrillex Remix)"),
    # Genuinely different songs that happen to share a word
    ("Alright", "Alright Then"),
    ("PRIDE.", "PRIDE. and Joy"),
])
def test_track_key_keeps_distinct_tracks_apart(a, b):
    assert track_key(a) != track_key(b)


def test_track_key_never_returns_empty():
    # A name that is punctuation alone would normalise to nothing, and an empty key
    # would silently merge every such track into one series.
    assert track_key("...") not in (None, "")
    assert track_key("???") != track_key("...")


def test_track_key_handles_missing_name():
    assert track_key(None) is None
    assert track_key("") is None


# --- fetch_top_tracks ---------------------------------------------------------

def _response(tracks):
    r = MagicMock()
    r.json.return_value = {"toptracks": {"track": tracks}}
    r.raise_for_status.return_value = None
    return r


@patch("pipelines.tracks_pipeline.session.get")
def test_fetch_top_tracks_derives_key_and_keeps_raw_name(mock_get):
    mock_get.return_value = _response([
        {"name": "HUMBLE.", "listeners": "100", "playcount": "500",
         "mbid": "004ced5f-7c64-42aa-9dd4-5f7542dedcca"},
    ])
    track = fetch_top_tracks("k", "Kendrick Lamar")[0]

    assert track["name"] == "HUMBLE.", "the raw label is kept, not the normalised one"
    assert track["track_key"] == "humble"
    assert track["mbid"] == "004ced5f-7c64-42aa-9dd4-5f7542dedcca"
    assert track["rank"] == 1


@patch("pipelines.tracks_pipeline.session.get")
def test_fetch_top_tracks_treats_blank_mbid_as_missing(mock_get):
    # Last.fm sends "" rather than omitting the field. Stored as-is, every track
    # without a MusicBrainz id would share one "id" and look related.
    mock_get.return_value = _response([
        {"name": "THE REPLACEMENT", "listeners": "30232", "playcount": "90000", "mbid": ""},
    ])
    assert fetch_top_tracks("k", "Kae")[0]["mbid"] is None


@patch("pipelines.tracks_pipeline.session.get")
def test_fetch_top_tracks_handles_a_single_track_object(mock_get):
    # Last.fm returns an object rather than a list when there is exactly one result
    mock_get.return_value = _response(
        {"name": "Only Song", "listeners": "5", "playcount": "9", "mbid": ""}
    )
    assert len(fetch_top_tracks("k", "Someone")) == 1


@patch("pipelines.tracks_pipeline.session.get")
def test_fetch_top_tracks_raises_on_an_error_body(mock_get):
    # Last.fm reports application errors inside a 200, so raise_for_status alone
    # would let an unknown artist through as an empty result.
    r = MagicMock()
    r.json.return_value = {"error": 6, "message": "The artist you supplied could not be found"}
    r.raise_for_status.return_value = None
    mock_get.return_value = r

    with pytest.raises(LastfmError):
        fetch_top_tracks("k", "Nobody At All")


# --- run_pipeline -------------------------------------------------------------

@patch("pipelines.tracks_pipeline.fetch_top_tracks")
def test_run_pipeline_stores_key_and_mbid(mock_fetch):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = ARTIST_ROW
    cursor.rowcount = 2

    mock_fetch.return_value = [
        {"rank": 1, "name": "HUMBLE.", "track_key": "humble",
         "mbid": "abc", "listeners": 100, "playcount": 500},
        {"rank": 2, "name": "Money Trees (feat. Jay Rock)", "track_key": "money trees",
         "mbid": None, "listeners": 90, "playcount": 400},
    ]

    failures = run_pipeline(conn, "k", ["Kendrick Lamar"])
    assert failures == 0

    insert = next(c for c in cursor.execute.call_args_list
                  if "INSERT INTO lastfm_track_snapshots" in c[0][0])
    params = insert[0][1]
    assert params[3] == ["HUMBLE.", "Money Trees (feat. Jay Rock)"], "raw names preserved"
    assert params[4] == ["humble", "money trees"], "normalised keys stored"
    assert params[5] == ["abc", None], "mbid stored, blank as NULL"


@patch("pipelines.tracks_pipeline.fetch_top_tracks")
def test_run_pipeline_counts_failures(mock_fetch):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = ARTIST_ROW
    mock_fetch.side_effect = requests.RequestException("boom")

    assert run_pipeline(conn, "k", ["Kendrick Lamar"]) == 1


@patch("pipelines.tracks_pipeline.fetch_top_tracks")
def test_run_pipeline_does_not_leak_the_api_key_on_failure(mock_fetch, capsys):
    # Last.fm URLs carry api_key= in the query string, and this repo's Actions logs
    # are public. requests puts the whole URL in its exception message.
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = ARTIST_ROW
    mock_fetch.side_effect = requests.RequestException(
        "404 Client Error for url: http://ws.audioscrobbler.com/2.0/?api_key=SECRET123"
    )

    run_pipeline(conn, "k", ["Kendrick Lamar"])
    assert "SECRET123" not in capsys.readouterr().out

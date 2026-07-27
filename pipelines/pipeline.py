#Main pipeline file
import psycopg
import requests
import os
import sys
from dotenv import load_dotenv
from datetime import date
#import from other pipeline file to run here


load_dotenv()

artists = [
        "Drake", "Travis Scott", "Future", "Kendrick Lamar", "J. Cole", "Lil Baby",
        "Playboi Carti", "Don Toliver", "GloRilla", "Central Cee", "Ice Spice",
        "Rod Wave", "21 Savage", "Gunna", "Sexyy Red",
        "JID", "Denzel Curry", "EsDeeKid", "fakemink", "Zeddy Will",
        "Kai Ca$h", "JELEEL!", "Kae", "Baby Keem"
    ]

today = date.today()

lastfm_api_key = os.getenv("LASTFM_API_KEY")

url = "http://ws.audioscrobbler.com/2.0/"
params = {
        "method": "artist.getinfo",
        "artist": "Drake",
        "api_key": lastfm_api_key,
        "format": "json"
    }

if __name__ == "__main__":
    try:
        from pipelines.yt_pipeline import describe_request_error, run_pipeline, yt_api_key
        from pipelines.tracks_pipeline import run_pipeline as run_tracks_pipeline
    except ImportError:
        from yt_pipeline import describe_request_error, run_pipeline, yt_api_key
        from tracks_pipeline import run_pipeline as run_tracks_pipeline

    # One HTTP session so the per-artist Last.fm calls reuse a keep-alive connection
    session = requests.Session()

    conn = psycopg.connect(os.getenv("DATABASE_URL"))
    cursor = conn.cursor()

    # Counted rather than just printed, because this runs on a schedule now and
    # nobody reads the output of a green run. See run_pipeline's docstring.
    lastfm_failures = 0

    for artist in artists:
        params["artist"] = artist
        try:
            response = session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            # One artist's API failure shouldn't stop the rest of the run
            print(f"Last.fm request failed for {artist}: {describe_request_error(exc)}")
            lastfm_failures += 1
            continue
        if "error" in data:
            print(f"Error for {artist}: {data['message']}")
            lastfm_failures += 1
            continue
        print(data["artist"]["stats"])


        #starting db stuff: look the artist up, insert if missing
        cursor.execute("SELECT id FROM artists WHERE name = %s", (artist,))
        row = cursor.fetchone()

        if row:
            artist_id = row[0]
        else:
            cursor.execute(
                'INSERT INTO artists (name) VALUES (%s) RETURNING id',
                (artist,)
            )
            artist_id = cursor.fetchone()[0]

        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM artist_snapshots WHERE artist_id = %s AND date = %s)",
            (artist_id, today)
        )
        snapshot_exists = cursor.fetchone()[0]

        if snapshot_exists:
            print(f"Snapshot already exists for {artist}, skipping.")
        else:
            listeners = data["artist"]["stats"]["listeners"]
            playcount = data["artist"]["stats"]["playcount"]
            cursor.execute(
                'INSERT INTO artist_snapshots (artist_id, listeners, playcount, date) VALUES (%s, %s, %s, %s)',
                (artist_id, listeners, playcount, today)
            )
            print(f"Inserted snapshot for {artist} with artist_id {artist_id}")

    # Commit before the later passes so they can see artists inserted above, and run
    # them in-process on the same connection instead of spawning more interpreters.
    conn.commit()

    # Tracks before YouTube: this pass leaves the connection open, the YouTube one
    # closes it. Both need the artist rows committed above.
    track_failures = run_tracks_pipeline(conn, lastfm_api_key, artists)
    yt_failures = run_pipeline(conn, yt_api_key, artists)

    total = len(artists)
    print(f"\n{'-' * 60}")
    print(f"Last.fm: {total - lastfm_failures}/{total} recorded, {lastfm_failures} failed")
    print(f"Tracks:  {total - track_failures}/{total} recorded, {track_failures} failed")
    print(f"YouTube: {total - yt_failures}/{total} recorded, {yt_failures} failed")

    # The exit status is the whole point of the counting. Everything above catches
    # its own errors so a single artist can't sink the run, which also meant the
    # process reported success no matter how much it dropped - and a scheduled job
    # nobody watches needs to be able to go red. A missed day can never be
    # backfilled (both APIs only return current values), so a quiet failure is a
    # permanent hole in the price history.
    if lastfm_failures or track_failures or yt_failures:
        print("FAILED - see the errors above")
        sys.exit(1)
    print("OK")

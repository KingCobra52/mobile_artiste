import os 
from dotenv import load_dotenv 
import psycopg

load_dotenv()

DATABASE_URL_IPV4 = os.getenv("DATABASE_URL_IPV4") or os.getenv("DATABASE_URL")
DATABASE_URL_IPV6 = os.getenv("DATABASE_URL_IPV6")

conn = psycopg.connect(DATABASE_URL_IPV4) #creates the postgres schema 
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS artists (
        id SERIAL PRIMARY KEY,
        name TEXT,  
        spotify_id TEXT, 
        genre TEXT,
        image_url TEXT,
        tier TEXT,
        youtube_handle TEXT,
        youtube_channel_id TEXT
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS artist_snapshots (
        id SERIAL PRIMARY KEY, 
        artist_id INTEGER REFERENCES artists(id),
        listeners INTEGER, 
        playcount INTEGER,
        date DATE 
    )
""")

# Identity now lives in Supabase Auth (auth.users): it owns email, password, and the
# UUID primary key. profiles holds only the app-specific columns hanging off that id.
cursor.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        id UUID PRIMARY KEY REFERENCES auth.users(id),
        username TEXT UNIQUE,
        bars NUMERIC(12,2) DEFAULT 10000
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS holdings (
        id SERIAL PRIMARY KEY,
        user_id UUID REFERENCES profiles(id),
        artist_id INTEGER REFERENCES artists(id),
        shares INTEGER,
        price_per_share FLOAT,
        bought_at DATE
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS youtube_snapshots (
    id SERIAL PRIMARY KEY, 
    artist_id INTEGER REFERENCES artists(id),
    subscribers INTEGER,
    total_views BIGINT,
    recent_videos_avg_views INTEGER,
    recent_videos_like_ratio FLOAT, 
    date DATE 
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS recent_youtube_video_snapshots (
        id SERIAL PRIMARY KEY, 
        artist_id INTEGER REFERENCES artists(id), 
        video_id TEXT,
        like_count INTEGER,
        view_count INTEGER,
        date DATE 
    )
""")

# Nothing prices these yet - they exist to accumulate history, which is the one
# model input that can't be acquired retroactively.
#
# Note there is no cleanup routine for this table, unlike
# recent_youtube_video_snapshots which gets trimmed to the newest 50 per artist.
# That trimming turned the video table into a rolling window that only reaches back
# to 2026-07-20, which makes it useless for fitting anything. This table is meant to
# BE history, so nothing deletes from it.
cursor.execute("""
    CREATE TABLE IF NOT EXISTS lastfm_track_snapshots (
        id SERIAL PRIMARY KEY,
        artist_id INTEGER REFERENCES artists(id),
        rank INTEGER,
        track_name TEXT,
        track_key TEXT,
        mbid TEXT,
        listeners INTEGER,
        playcount INTEGER,
        date DATE
    )
""")
# track_name is the raw label, kept so a rename stays visible after the fact.
# track_key is the normalised name and is what anything comparing a track across
# dates must join on: the raw name changes when Last.fm adds a remaster suffix or a
# feature credit, which reads as one track vanishing and another appearing.
# mbid is stored to DETECT those renames - one mbid under two keys is a relabelling.
# It is not the key itself because it covers only about half the tracks, and the
# half it misses are the small artists where a rename moves concentration most.
cursor.execute("ALTER TABLE lastfm_track_snapshots ADD COLUMN IF NOT EXISTS track_key TEXT;")
cursor.execute("ALTER TABLE lastfm_track_snapshots ADD COLUMN IF NOT EXISTS mbid TEXT;")

# Add columns if table already existed but lacked them
cursor.execute("ALTER TABLE youtube_snapshots ADD COLUMN IF NOT EXISTS recent_videos_avg_views INTEGER;")
cursor.execute("ALTER TABLE youtube_snapshots ADD COLUMN IF NOT EXISTS recent_videos_like_ratio FLOAT;")
# Handles are squattable and reassignable; channel ids are immutable. Keying the
# YouTube pipeline on the handle silently matched 11 of 25 artists to strangers.
cursor.execute("ALTER TABLE artists ADD COLUMN IF NOT EXISTS youtube_channel_id TEXT;")
cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_artists_youtube_channel_id_unique
    ON artists (youtube_channel_id)
""")

# Migrations for tables created before these constraints existed:
# bars was INTEGER, which silently rounded every fractional buy/sell amount
cursor.execute("ALTER TABLE profiles ALTER COLUMN bars TYPE NUMERIC(12,2);")
# The starting balance drifted to 100000 when profiles was first created
cursor.execute("ALTER TABLE profiles ALTER COLUMN bars SET DEFAULT 10000;")
# Duplicate signups used to succeed and login just matched the first row.
# Fails if duplicates already exist - resolve those rows manually first.
# Email uniqueness is Supabase Auth's job now, so it isn't duplicated here.
cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_username_unique ON profiles (username)
""")

# Snapshots grow by one row per artist per day forever, and every page prices artists
# off the latest row per artist (LATERAL ... ORDER BY date DESC LIMIT 1, and the market
# page's DISTINCT ON). These keep those lookups indexed instead of scanning history.
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_artist_snapshots_artist_date
    ON artist_snapshots (artist_id, date DESC)
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_youtube_snapshots_artist_date
    ON youtube_snapshots (artist_id, date DESC)
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_lastfm_track_snapshots_artist_date
    ON lastfm_track_snapshots (artist_id, date DESC, rank ASC)
""")
# Backs the join every cross-date comparison makes: one track's series over time
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_lastfm_track_snapshots_key_date
    ON lastfm_track_snapshots (artist_id, track_key, date DESC)
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_recent_video_snapshots_artist_date
    ON recent_youtube_video_snapshots (artist_id, date DESC, id DESC)
""")
# Same-day dedupe check in the YouTube pipeline
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_recent_video_snapshots_video_date
    ON recent_youtube_video_snapshots (video_id, date)
""")
# Holdings lookups on the artist page, sell flow, portfolio, and leaderboard
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_holdings_user_artist
    ON holdings (user_id, artist_id)
""")

conn.commit()
conn.close()
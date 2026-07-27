"""
Database access. psycopg3 + psycopg_pool, run synchronously.

The Flask app created its pool lazily on first use so it could be imported without
a reachable database; here the pool is opened in main.py's lifespan handler instead,
so a bad DSN fails at startup rather than on the first request.
"""
import os

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

# dict_row is the psycopg3 equivalent of psycopg2's RealDictCursor: rows come back
# as dicts, which is what compute_price_per_share() expects to be handed.
#
# open=False because the pool is opened explicitly in the lifespan handler. The DSN
# is the session-mode pooler on :5432, so prepared statements are fine; switching to
# transaction mode on :6543 would need prepare_threshold=None here.
pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row},
    # Supabase's pooler closes connections that have been idle for a while, and a
    # pool without this hands the dead one to the next request - which surfaces as
    # "server closed the connection unexpectedly" on the first call after a quiet
    # period. check_connection tests each connection on checkout and transparently
    # replaces it if it's gone. Costs a round trip per request; worth it on an
    # endpoint that moves balances.
    check=ConnectionPool.check_connection,
    # Belt and braces: retire connections before the pooler decides to.
    max_idle=120.0,
)


def get_db():
    """FastAPI dependency yielding a pooled connection for the life of one request."""
    with pool.connection() as conn:
        yield conn

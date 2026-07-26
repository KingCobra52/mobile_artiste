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
)


def get_db():
    """
    FastAPI dependency yielding a pooled connection for the life of one request.

    Deliberately a sync generator: FastAPI runs sync dependencies in a threadpool,
    which is what sync psycopg wants. pool.connection() commits on clean exit and
    rolls back if the handler raises, then returns the connection to the pool.
    """
    with pool.connection() as conn:
        yield conn

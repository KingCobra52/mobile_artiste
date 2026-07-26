"""
Artiste API.

Run from the mobile_artiste/ directory:
    uvicorn api.main:app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.db import pool
from api.routers import artists


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Opening at startup rather than on first request means a bad DSN or an
    # unreachable database fails immediately and visibly. wait() blocks until the
    # minimum number of connections is actually established.
    pool.open()
    pool.wait()
    yield
    pool.close()


app = FastAPI(title="Artiste API", lifespan=lifespan)

# Wide open for local development. React Native's fetch ignores CORS, but Expo Web
# does not, so this saves a confusing hour in phase 2. Tighten before deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(artists.router)


@app.get("/health")
def health():
    return {"status": "ok"}

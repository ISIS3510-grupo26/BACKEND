"""Punto de entrada del backend CampusBites."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import connect, init_db
from app.repositories.spots_repository import SpotsRepository
from app.routers import analytics, spots, telemetry


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect()
    try:
        init_db(conn)
        SpotsRepository(conn).seed_if_empty()
    finally:
        conn.close()
    yield


app = FastAPI(title="CampusBites API", version="1.0.0", lifespan=lifespan)

# El mismo backend sirve a varios fronts (Android/Kotlin y el otro cliente, que puede ser web).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(spots.router)
app.include_router(telemetry.router)
app.include_router(analytics.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

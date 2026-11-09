"""Punto de entrada del backend CampusBites."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.db import connect, init_db
from app.repositories.spots_repository import SpotsRepository
from app.routers import analytics, auth, best_for_you, matches, spots, telemetry, users


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect()
    try:
        init_db(conn)
        SpotsRepository(conn).sync_catalog()
    finally:
        conn.close()
    yield


app = FastAPI(title="CampusBites API", version="1.0.0", lifespan=lifespan)

# El mismo backend sirve a varios fronts (Android/Kotlin y el otro cliente, que puede ser web).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router)
app.include_router(spots.router)
app.include_router(telemetry.router)
app.include_router(analytics.router)
app.include_router(users.router)
app.include_router(best_for_you.router)
app.include_router(matches.router)

# Fotos de restaurantes y platos. image_url viene relativo a la URL del backend (p. ej. "fotos/nitro-coffee.jpg"):
# los fronts lo pegan a su API_BASE_URL. Se sirven desde aqui y no desde un sitio externo para que funcionen
# en la red local de la demo y no dependan de otro servidor. Fuente de las fotos: TheMealDB / TheCocktailDB.
app.mount("/fotos", StaticFiles(directory=Path(__file__).parent / "static" / "fotos"), name="fotos")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    """Dashboard del equipo: una tarjeta por business question, leida de los endpoints /api/v1/analytics."""
    return HTMLResponse(DASHBOARD.read_text(encoding="utf-8"))

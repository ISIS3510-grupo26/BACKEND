"""Capa de persistencia: conexion SQLite y esquema."""
import os
import sqlite3
from collections.abc import Iterator

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS spots (
    id               TEXT PRIMARY KEY,
    emoji            TEXT NOT NULL,
    emoji_background TEXT NOT NULL,
    emoji_border     TEXT NOT NULL,
    name             TEXT NOT NULL,
    subtitle         TEXT NOT NULL,
    rating           REAL NOT NULL,
    price            TEXT NOT NULL,
    distance         TEXT NOT NULL,
    walk_minutes     INTEGER NOT NULL,
    is_budget        INTEGER NOT NULL,
    is_vegetarian    INTEGER NOT NULL,
    is_high_protein  INTEGER NOT NULL,
    affinity_percent INTEGER NOT NULL,
    category         TEXT NOT NULL,
    note_label       TEXT NOT NULL,
    note             TEXT NOT NULL,
    uni_card_perk    TEXT,
    total_reviews    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS menu_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id          TEXT NOT NULL REFERENCES spots(id),
    position         INTEGER NOT NULL,
    emoji            TEXT NOT NULL,
    emoji_background TEXT NOT NULL,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL,
    price            TEXT NOT NULL,
    is_student_pick  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id       TEXT NOT NULL REFERENCES spots(id),
    position      INTEGER NOT NULL,
    author_name   TEXT NOT NULL,
    initials      TEXT NOT NULL,
    program       TEXT NOT NULL,
    stars         INTEGER NOT NULL,
    text          TEXT NOT NULL,
    dined_ago     TEXT NOT NULL,
    helpful_count INTEGER NOT NULL DEFAULT 0
);

-- Un registro por cada intento de cargar la pagina de un restaurante,
-- reportado por cualquier cliente (Android/Kotlin, el otro front, etc.).
CREATE TABLE IF NOT EXISTS page_load_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,      -- generado por el cliente: idempotencia en reintentos
    screen       TEXT NOT NULL,
    spot_id      TEXT,
    duration_ms  INTEGER NOT NULL,
    success      INTEGER NOT NULL,
    http_status  INTEGER,
    error_type   TEXT,
    device_model TEXT NOT NULL,
    os_name      TEXT NOT NULL,
    os_version   TEXT NOT NULL,
    platform     TEXT NOT NULL,             -- p. ej. android-kotlin, flutter, ios
    app_version  TEXT,
    session_id   TEXT,
    occurred_at  TEXT NOT NULL,
    received_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ple_screen_time ON page_load_events(screen, occurred_at);
"""


def connect() -> sqlite3.Connection:
    if settings.db_path != ":memory:":
        os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_conn() -> Iterator[sqlite3.Connection]:
    """Dependencia de FastAPI: una conexion por request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()

"""Capa de persistencia: conexion SQLite y esquema."""
import os
import secrets
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
    latitude         REAL,                  -- WGS84; lo usa la BQ5 para calcular la caminata real
    longitude        REAL,
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

-- Cuentas de usuario. id es un uuid generado por el servidor: es el mismo userId de favorites y de la telemetria.
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,        -- normalizado: sin espacios y en minusculas
    password_hash TEXT NOT NULL,               -- bcrypt; nunca la contrasena en texto plano
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Valores internos del servidor. jwt_secret firma los tokens cuando no se configura JWT_SECRET: vive con la base,
-- asi los tokens sobreviven reinicios y no hay un secreto en el repositorio ni en otro archivo.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Horario semanal en hora local del campus. day_of_week: 0 = lunes ... 6 = domingo (datetime.weekday()).
-- Si closes_at <= opens_at la franja cruza la medianoche y termina al dia siguiente.
CREATE TABLE IF NOT EXISTS spot_opening_hours (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id     TEXT NOT NULL REFERENCES spots(id),
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    opens_at    TEXT NOT NULL,              -- 'HH:MM'
    closes_at   TEXT NOT NULL               -- 'HH:MM'
);

CREATE INDEX IF NOT EXISTS idx_soh_spot ON spot_opening_hours(spot_id);

-- Restaurantes guardados por cada usuario. user_id es el identificador que manda el cliente
-- (todavia no hay autenticacion; cuando exista sera el id del usuario autenticado).
CREATE TABLE IF NOT EXISTS favorites (
    user_id    TEXT NOT NULL,
    spot_id    TEXT NOT NULL REFERENCES spots(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (user_id, spot_id)
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
    user_id      TEXT,                      -- obligatorio en screen = favorite_added (BQ7)
    occurred_at  TEXT NOT NULL,
    received_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ple_screen_time ON page_load_events(screen, occurred_at);
"""

# Columnas agregadas despues de la primera version del esquema. CREATE TABLE IF NOT EXISTS no altera
# tablas que ya existen, asi que las bases creadas antes se actualizan aqui (idempotente).
ADDED_COLUMNS = {
    "spots": [("latitude", "REAL"), ("longitude", "REAL")],
    "page_load_events": [("user_id", "TEXT")],
}


def connect() -> sqlite3.Connection:
    if settings.db_path != ":memory:":
        os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, sql_type in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
    conn.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES ('jwt_secret', ?)", (secrets.token_hex(32),))
    conn.commit()


def get_conn() -> Iterator[sqlite3.Connection]:
    """Dependencia de FastAPI: una conexion por request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()

"""Repository: unico componente que sabe como se guardan los restaurantes."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SEED_FILE = Path(__file__).resolve().parent.parent / "seed_spots.json"

_SPOT_COLUMNS = (
    "id", "emoji", "emoji_background", "emoji_border", "name", "subtitle", "rating",
    "price", "distance", "walk_minutes", "is_budget", "is_vegetarian", "is_high_protein",
    "affinity_percent", "category", "note_label", "note", "uni_card_perk", "total_reviews",
)
# Se escriben al sembrar pero no se exponen en /spots (las usa la BQ5 en el servidor).
_GEO_COLUMNS = ("latitude", "longitude")
_BOOL_COLUMNS = {"is_budget", "is_vegetarian", "is_high_protein", "is_student_pick"}
# Las cambian las resenas de los usuarios
_RATING_COLUMNS = ("rating", "total_reviews")


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: bool(row[k]) if k in _BOOL_COLUMNS else row[k] for k in row.keys()}


def _dined_ago(created_at: str, now: datetime) -> str:
    """Mismo formato que las reseñas del catalogo."""
    days = (now - datetime.fromisoformat(created_at.replace("Z", "+00:00"))).days
    if days <= 0:
        return "Dined today"
    if days == 1:
        return "Dined yesterday"
    return f"Dined {days} days ago"


class SpotsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_spots(self) -> list[dict]:
        rows = self.conn.execute(f"SELECT {', '.join(_SPOT_COLUMNS)} FROM spots ORDER BY rowid").fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_favorite_spots(self, user_id: str) -> list[dict]:
        """Restaurantes guardados por el usuario, en el orden en que los guardo."""
        rows = self.conn.execute(
            f"SELECT {', '.join('s.' + c for c in _SPOT_COLUMNS)} FROM favorites f JOIN spots s ON s.id = f.spot_id "
            "WHERE f.user_id = ? ORDER BY f.rowid",
            (user_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_spot(self, spot_id: str) -> dict | None:
        row = self.conn.execute(
            f"SELECT {', '.join(_SPOT_COLUMNS)} FROM spots WHERE id = ?", (spot_id,)
        ).fetchone()
        if row is None:
            return None
        spot = _row_to_dict(row)
        spot["menu"] = [
            _row_to_dict(r) for r in self.conn.execute(
                "SELECT emoji, emoji_background, name, description, price, is_student_pick "
                "FROM menu_items WHERE spot_id = ? ORDER BY position", (spot_id,),
            )
        ]
        # Primero las resenas de usuarios (la mas nueva arriba) y despues las del catalogo en su orden.
        now = datetime.now(timezone.utc)
        spot["reviews"] = []
        for r in self.conn.execute(
            "SELECT author_name, initials, program, stars, text, dined_ago, helpful_count, created_at "
            "FROM reviews WHERE spot_id = ? ORDER BY user_id IS NULL, created_at DESC, position", (spot_id,),
        ):
            review = _row_to_dict(r)
            created_at = review.pop("created_at")
            if created_at:
                review["dined_ago"] = _dined_ago(created_at, now)
            spot["reviews"].append(review)
        return spot

    def exists(self, spot_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM spots WHERE id = ?", (spot_id,)).fetchone() is not None

    def apply_new_rating(self, spot_id: str, stars: int) -> dict:
        """Suma una calificacion al promedio del restaurante sin hacer commit (se usa dentro del UnitOfWork)."""
        self.conn.execute(
            "UPDATE spots SET rating = (rating * total_reviews + ?) / (total_reviews + 1), "
            "total_reviews = total_reviews + 1 WHERE id = ?",
            (stars, spot_id),
        )
        row = self.conn.execute("SELECT rating, total_reviews FROM spots WHERE id = ?", (spot_id,)).fetchone()
        return {"rating": row["rating"], "total_reviews": row["total_reviews"]}
    
    def sync_catalog(self) -> None:
        """Carga el catalogo de seed_spots.json, que es su unica fuente (la API no escribe restaurantes).

        Corre en cada arranque y es idempotente: las bases nuevas quedan sembradas y las ya existentes se
        actualizan (p. ej. coordenadas y horarios de la BQ5) sin un paso de migracion aparte. Los restaurantes
        se actualizan con upsert, no se borran, porque favorites los referencia; menu, reseñas y horarios se
        reemplazan completos.Excepción: las reseñas de usuarios (user_id no nulo) y el rating/total_reviews
        que ellas cambiaron no se tocan, si no cada reinicio del servidor borraria lo que publicaron."""
        spots = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        columns = (*_SPOT_COLUMNS, *_GEO_COLUMNS)
        upsert = (
            f"INSERT INTO spots ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
            f"ON CONFLICT(id) DO UPDATE SET "
            f"{', '.join(f'{c} = excluded.{c}' for c in columns[1:] if c not in _RATING_COLUMNS)}"
        )
        with self.conn:
            for spot in spots:
                self.conn.execute(upsert, [spot.get(c) for c in columns])
                for table in ("menu_items", "spot_opening_hours"):
                    self.conn.execute(f"DELETE FROM {table} WHERE spot_id = ?", (spot["id"],))
                self.conn.execute("DELETE FROM reviews WHERE spot_id = ? AND user_id IS NULL", (spot["id"],))
                self.conn.executemany(
                    "INSERT INTO menu_items (spot_id, position, emoji, emoji_background, name, description, price, is_student_pick) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(spot["id"], pos, item["emoji"], item["emoji_background"], item["name"],
                      item["description"], item["price"], item.get("is_student_pick", False))
                     for pos, item in enumerate(spot["menu"])],
                )
                self.conn.executemany(
                    "INSERT INTO reviews (spot_id, position, author_name, initials, program, stars, text, dined_ago, helpful_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(spot["id"], pos, review["author_name"], review["initials"], review["program"],
                      review["stars"], review["text"], review["dined_ago"], review["helpful_count"])
                     for pos, review in enumerate(spot["reviews"])],
                )
                self.conn.executemany(
                    "INSERT INTO spot_opening_hours (spot_id, day_of_week, opens_at, closes_at) VALUES (?, ?, ?, ?)",
                    [(spot["id"], day, slot["opens"], slot["closes"])
                     for slot in spot["opening_hours"] for day in slot["days"]],
                )
                
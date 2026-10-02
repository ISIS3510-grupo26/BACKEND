"""Repository: unico componente que sabe como se guardan los restaurantes."""
import json
import sqlite3
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


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: bool(row[k]) if k in _BOOL_COLUMNS else row[k] for k in row.keys()}


class SpotsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_spots(self) -> list[dict]:
        rows = self.conn.execute(f"SELECT {', '.join(_SPOT_COLUMNS)} FROM spots ORDER BY rowid").fetchall()
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
        spot["reviews"] = [
            _row_to_dict(r) for r in self.conn.execute(
                "SELECT author_name, initials, program, stars, text, dined_ago, helpful_count "
                "FROM reviews WHERE spot_id = ? ORDER BY position", (spot_id,),
            )
        ]
        return spot

    def sync_catalog(self) -> None:
        """Carga el catalogo de seed_spots.json, que es su unica fuente (la API no escribe restaurantes).

        Corre en cada arranque y es idempotente: las bases nuevas quedan sembradas y las ya existentes se
        actualizan (p. ej. coordenadas y horarios de la BQ5) sin un paso de migracion aparte. Los restaurantes
        se actualizan con upsert, no se borran, porque favorites los referencia; menu, resenas y horarios se
        reemplazan completos.
        """
        spots = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        columns = (*_SPOT_COLUMNS, *_GEO_COLUMNS)
        upsert = (
            f"INSERT INTO spots ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
            f"ON CONFLICT(id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in columns[1:])}"
        )
        with self.conn:
            for spot in spots:
                self.conn.execute(upsert, [spot.get(c) for c in columns])
                for table in ("menu_items", "reviews", "spot_opening_hours"):
                    self.conn.execute(f"DELETE FROM {table} WHERE spot_id = ?", (spot["id"],))
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

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

    def seed_if_empty(self) -> None:
        if self.conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0]:
            return
        spots = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        with self.conn:
            for spot in spots:
                self.conn.execute(
                    f"INSERT INTO spots ({', '.join(_SPOT_COLUMNS)}) VALUES ({', '.join('?' * len(_SPOT_COLUMNS))})",
                    [spot.get(c) for c in _SPOT_COLUMNS],
                )
                for pos, item in enumerate(spot["menu"]):
                    self.conn.execute(
                        "INSERT INTO menu_items (spot_id, position, emoji, emoji_background, name, description, price, is_student_pick) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (spot["id"], pos, item["emoji"], item["emoji_background"], item["name"],
                         item["description"], item["price"], item.get("is_student_pick", False)),
                    )
                for pos, review in enumerate(spot["reviews"]):
                    self.conn.execute(
                        "INSERT INTO reviews (spot_id, position, author_name, initials, program, stars, text, dined_ago, helpful_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (spot["id"], pos, review["author_name"], review["initials"], review["program"],
                         review["stars"], review["text"], review["dined_ago"], review["helpful_count"]),
                    )

#Repository del calculo de compatibilidad, los restaurantes con sus etiquetas y las calificaciones de cada usuario.
import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchCandidate:
    id: str
    rating: float
    is_budget: bool
    is_vegetarian: bool
    cuisines: tuple[str, ...]
    flavors: tuple[str, ...]
    meal_styles: tuple[str, ...]
    contains: tuple[str, ...]


def _tags(value: str | None) -> tuple[str, ...]:
    return tuple(json.loads(value)) if value else ()


class MatchRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def candidates(self) -> list[MatchCandidate]:
        rows = self.conn.execute(
            "SELECT id, rating, is_budget, is_vegetarian, cuisines, flavors, meal_styles, contains "
            "FROM spots ORDER BY id"
        ).fetchall()
        return [
            MatchCandidate(
                id=r["id"], rating=r["rating"], is_budget=bool(r["is_budget"]), is_vegetarian=bool(r["is_vegetarian"]),
                cuisines=_tags(r["cuisines"]), flavors=_tags(r["flavors"]),
                meal_styles=_tags(r["meal_styles"]), contains=_tags(r["contains"]),
            )
            for r in rows
        ]

    def ratings_by_user(self) -> dict[str, dict[str, int]]:
        #{user_id: {spot_id: estrellas}} con las resenas que escribieron los usuarios en la app.
        ratings: dict[str, dict[str, int]] = {}
        for r in self.conn.execute("SELECT user_id, spot_id, stars FROM reviews WHERE user_id IS NOT NULL"):
            ratings.setdefault(r["user_id"], {})[r["spot_id"]] = r["stars"]
        return ratings
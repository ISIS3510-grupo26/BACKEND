#Repository de preferencias: gustos y restricciones que el usuario guarda desde la app.
import json
import sqlite3

from app.schemas import PreferencesIn

_LIST_FIELDS = ("flavors", "interests", "avoid", "allergies")


def _row_to_prefs(row: sqlite3.Row) -> dict:
    prefs = dict(row)
    for field in _LIST_FIELDS:
        prefs[field] = json.loads(prefs[field])
    return prefs


class PreferencesRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT user_id, main_cuisine, meal_style, flavors, interests, diet, avoid, allergies "
            "FROM user_preferences WHERE user_id = ?", (user_id,),
        ).fetchone()
        return _row_to_prefs(row) if row else None

    def save(self, user_id: str, prefs: PreferencesIn) -> None:
        #Crea o reemplaza las preferencias del usuario.
        values = prefs.model_dump()
        for field in _LIST_FIELDS:
            values[field] = json.dumps(values[field])
        with self.conn:
            self.conn.execute(
                "INSERT INTO user_preferences (user_id, main_cuisine, meal_style, flavors, interests, diet, avoid, "
                "allergies) VALUES (:user_id, :main_cuisine, :meal_style, :flavors, :interests, :diet, :avoid, "
                ":allergies) ON CONFLICT(user_id) DO UPDATE SET main_cuisine = excluded.main_cuisine, "
                "meal_style = excluded.meal_style, flavors = excluded.flavors, interests = excluded.interests, "
                "diet = excluded.diet, avoid = excluded.avoid, allergies = excluded.allergies, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                {"user_id": user_id, **values},
            )

    def all_preferences(self) -> dict[str, dict]:
        
        #Las de todos los usuarios, para encontrar estudiantes con gustos parecidos (filtrado colaborativo).
        rows = self.conn.execute(
            "SELECT user_id, main_cuisine, meal_style, flavors, interests, diet, avoid, allergies FROM user_preferences"
        ).fetchall()
        return {r["user_id"]: _row_to_prefs(r) for r in rows}
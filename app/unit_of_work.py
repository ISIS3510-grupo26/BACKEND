"""Unit of Work: varias escrituras de distintos repositorios como una sola transaccion.
El patrón Unit of Work. Abre una transacción, deja que varios repositorios escriban dentro
de ella al final hace commit (si todo salió bien) o rollback (si algo falló).
"""
import sqlite3

from app.repositories.reviews_repository import ReviewsRepository
from app.repositories.spots_repository import SpotsRepository
from app.repositories.users_repository import UsersRepository


class UnitOfWork:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.reviews = ReviewsRepository(conn)
        self.spots = SpotsRepository(conn)
        self.users = UsersRepository(conn)

    def __enter__(self) -> "UnitOfWork":
        self.conn.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        return False

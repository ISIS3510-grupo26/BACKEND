"""Servicio de reseñas: publicar una calificacion y actualizar el promedio del restaurante en 
una sola transaccion."""
import sqlite3
from datetime import datetime, timezone
from app.schemas import ReviewCreatedOut, ReviewItemOut, ReviewPageOut
from app.unit_of_work import UnitOfWork


class SpotNotFound(Exception):
    pass

class AlreadyReviewed(Exception):
    pass


class ReviewNotFound(Exception):
    pass


def _author(email: str) -> tuple[str, str]:
    name = email.split("@")[0]
    return name, name[:2].upper()


class ReviewsService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def submit(self, spot_id: str, user_id: str, stars: int, text: str, now: datetime | None = None) -> ReviewCreatedOut:
        now = now or datetime.now(timezone.utc)
        # Cualquier excepcion dentro del with hace rollback
        with UnitOfWork(self.conn) as uow:
            if not uow.spots.exists(spot_id):
                raise SpotNotFound(spot_id)
            author_name, initials = _author(uow.users.get_by_id(user_id)["email"])
            try:
                uow.reviews.add(spot_id, user_id, author_name, initials, stars, text, created_at=now)
            except sqlite3.IntegrityError:
                raise AlreadyReviewed(spot_id)
            totals = uow.spots.apply_new_rating(spot_id, stars)
        return ReviewCreatedOut(spot_id=spot_id, stars=stars, text=text, **totals)

    def page(self, spot_id: str, sort: str, stars: int | None, q: str | None, page: int,
             page_size: int) -> ReviewPageOut:
        """Todas las reseñas de un restaurante, paginadas, con orden, estrellas y busqueda."""
        uow = UnitOfWork(self.conn)
        if not uow.spots.exists(spot_id):
            raise SpotNotFound(spot_id)
        rows, total = uow.reviews.page(spot_id, sort, stars, (q or "").strip() or None, page, page_size)
        return ReviewPageOut(items=[ReviewItemOut(**dict(r)) for r in rows], page=page, page_size=page_size,
                             total=total)

    def set_helpful(self, spot_id: str, review_id: int, user_id: str, helpful: bool) -> None:
        """Marca o desmarca Helpful. El voto y helpful_count cambian en la misma transaccion; repetir la misma
        operacion no cambia nada (la app puede reenviarla al volver la red)."""
        with UnitOfWork(self.conn) as uow:
            if not uow.reviews.belongs_to(review_id, spot_id):
                raise ReviewNotFound(review_id)
            if helpful:
                uow.reviews.add_helpful(user_id, review_id)
            else:
                uow.reviews.remove_helpful(user_id, review_id)

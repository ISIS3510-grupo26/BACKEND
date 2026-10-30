#Preferencias del usuario y compatibilidad de cada restaurante (smart feature -- Gaby).

import sqlite3

from fastapi import APIRouter, Depends

from app.db import get_conn
from app.repositories.match_repository import MatchRepository
from app.repositories.preferences_repository import PreferencesRepository
from app.routers.users import AuthorizedUserId
from app.schemas import PreferencesIn, PreferencesOut, SpotMatchOut
from app.services.match_service import MatchService

router = APIRouter(prefix="/api/v1/users", tags=["preferences & matches"])


def get_preferences_repo(conn: sqlite3.Connection = Depends(get_conn)) -> PreferencesRepository:
    return PreferencesRepository(conn)


def get_match_service(conn: sqlite3.Connection = Depends(get_conn)) -> MatchService:
    return MatchService(MatchRepository(conn), PreferencesRepository(conn))


@router.get("/{user_id}/preferences", response_model=PreferencesOut)
def get_preferences(user_id: AuthorizedUserId, repo: PreferencesRepository = Depends(get_preferences_repo)):
    #Lo que el usuario guardo.
    prefs = repo.get(user_id)
    return PreferencesOut(**prefs, saved=True) if prefs else PreferencesOut(saved=False)


@router.put("/{user_id}/preferences", response_model=PreferencesOut)
def save_preferences(body: PreferencesIn, user_id: AuthorizedUserId,
                     repo: PreferencesRepository = Depends(get_preferences_repo)):
    #Reemplaza todas las preferencias.
    return PreferencesOut(**body.model_dump(), saved=True)


@router.get("/{user_id}/matches", response_model=list[SpotMatchOut])
def spot_matches(user_id: AuthorizedUserId, service: MatchService = Depends(get_match_service)):
    #Smart feature, compatibilidad 0-100 de cada restaurante para este usuario (el "% match" del feed).
    return service.all_matches(user_id)
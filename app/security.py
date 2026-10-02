"""Identidad de quien llama: dependencias de FastAPI que comparten los routers.

Contrato: `Authorization: Bearer <accessToken>` (JWT HS256, vigencia JWT_EXPIRE_MINUTES, 7 dias por defecto).

Override de desarrollo: una peticion SIN header Authorization puede seguir diciendo un userId explicito
(ruta /users/{userId}/... o `userId` en la telemetria), como el DEV_USER_ID del front, siempre que ese id
no sea de una cuenta registrada. Si el header viene, tiene que ser valido: nunca se cae al override.
"""
import sqlite3

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_conn
from app.repositories.users_repository import UsersRepository
from app.services.auth_service import AuthService, InvalidToken

# auto_error=False: la ausencia del header no es un error (override de desarrollo); un header invalido si.
_bearer = HTTPBearer(auto_error=False)


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def get_users_repo(conn: sqlite3.Connection = Depends(get_conn)) -> UsersRepository:
    return UsersRepository(conn)


def get_auth_service(users: UsersRepository = Depends(get_users_repo)) -> AuthService:
    return AuthService(users)


def optional_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> str | None:
    """User id del token, o None si la peticion no trae header Authorization. Si el header viene, tiene que ser
    valido: un token vencido o mal formado es 401, nunca una peticion anonima."""
    if "authorization" not in request.headers:
        return None
    if credentials is None or not credentials.credentials:
        raise unauthorized("Authorization header must be 'Bearer <token>'")
    try:
        return auth.user_id_from_token(credentials.credentials)
    except InvalidToken:
        raise unauthorized("Invalid or expired token")


def require_user_id(user_id: str | None = Depends(optional_user_id)) -> str:
    if user_id is None:
        raise unauthorized("Not authenticated")
    return user_id


def resolve_acting_user(claimed: str | None, token_user_id: str | None, users: UsersRepository) -> str | None:
    """Quien actua en la peticion, a partir del userId que dice el cliente y del token (si vino).

    Con token: el del token; si el cliente dice otro -> 403.
    Sin token (override de desarrollo): el que dice el cliente, salvo que sea una cuenta registrada -> 401.
    """
    if token_user_id is not None:
        if claimed not in (None, token_user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="userId does not match the token")
        return token_user_id
    if claimed is not None and users.exists(claimed):
        raise unauthorized(f"User '{claimed}' is a registered account: send its token")
    return claimed

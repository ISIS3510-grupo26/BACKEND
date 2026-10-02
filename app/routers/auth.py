"""Registro e inicio de sesion. Como se identifica a quien llama esta en app/security.py."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.repositories.users_repository import UsersRepository
from app.schemas import AuthTokenOut, LoginIn, SignupIn, UserOut
from app.security import get_auth_service, get_users_repo, require_user_id, unauthorized
from app.services.auth_service import AuthService, EmailTaken, InvalidCredentials

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/signup", response_model=AuthTokenOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, service: AuthService = Depends(get_auth_service)):
    try:
        return service.signup(body.email, body.password)
    except EmailTaken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")


@router.post("/login", response_model=AuthTokenOut)
def login(body: LoginIn, service: AuthService = Depends(get_auth_service)):
    try:
        return service.login(body.email, body.password)
    except InvalidCredentials:
        raise unauthorized("Invalid email or password")


@router.get("/me", response_model=UserOut)
def me(user_id: str = Depends(require_user_id), users: UsersRepository = Depends(get_users_repo)):
    """Para que el cliente compruebe al abrir la app si el token guardado sigue valido."""
    user = users.get_by_id(user_id)
    return UserOut(user_id=user["id"], email=user["email"])

"""Registro e inicio de sesion. Como se identifica a quien llama esta en app/security.py."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.repositories.users_repository import UsersRepository
from app.schemas import AuthTokenOut, ChangePasswordIn, LoginIn, SignupIn, UserOut
from app.security import get_auth_service, get_users_repo, require_user_id, unauthorized
from app.services.auth_service import (AuthService, EmailTaken, InvalidCredentials, SamePassword, WrongCurrentPassword)

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


@router.post("/change-password", response_model=AuthTokenOut)
def change_password(body: ChangePasswordIn, user_id: str = Depends(require_user_id),
                    service: AuthService = Depends(get_auth_service)):
    """Cambia la contrasena del usuario del token. Devuelve un token nuevo; los anteriores dejan de servir."""
    try:
        return service.change_password(user_id, body.current_password, body.new_password)
    except WrongCurrentPassword:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    except SamePassword:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="New password must be different from the current one")
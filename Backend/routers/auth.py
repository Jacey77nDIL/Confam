from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database.session import get_db
from middleware.auth import get_current_user
from models.user import User
from schemas.token import Token
from schemas.user import UserCreate, UserLogin, UserResponse
from services import auth_service
from utils.jwt import create_access_token

router = APIRouter()


@router.post("/signup", response_model=Token)
def signup(payload: UserCreate, db: Session = Depends(get_db)) -> Token:
    if auth_service.get_user_by_email(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    user = auth_service.register_user(
        db,
        full_name=payload.full_name,
        email=payload.email,
        password=payload.password,
    )
    access_token = create_access_token(str(user.id))
    return Token(access_token=access_token, token_type="bearer")


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> Token:
    user = auth_service.verify_credentials(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    access_token = create_access_token(str(user.id))
    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
def read_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user

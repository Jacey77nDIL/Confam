"""Auth helpers shared by routers (keeps routers thin)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.user import User
from utils.security import get_password_hash, verify_password


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.email == email.lower())).first()


def register_user(db: Session, *, full_name: str, email: str, password: str) -> User:
    user = User(
        full_name=full_name.strip(),
        email=email.lower(),
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def verify_credentials(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user

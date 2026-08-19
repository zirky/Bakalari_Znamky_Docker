import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Response, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session as DbSession

from .database import SessionLocal
from .models import AuthUser, Session

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
COOKIE_NAME = 'bakalari_session'
IDLE_TIMEOUT_SECONDS = int(os.getenv('SESSION_IDLE_TIMEOUT_SECONDS', '60'))
SESSION_COOKIE_MAX_AGE = 8 * 60 * 60
IDLE_TIMEOUT = timedelta(seconds=IDLE_TIMEOUT_SECONDS)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_parent(db: DbSession, configured_pin: str) -> None:
    if not configured_pin or db.query(AuthUser).filter_by(role='parent').first():
        return
    db.add(AuthUser(role='parent', pin_hash=pwd_context.hash(configured_pin)))
    db.commit()


def login_parent(db: DbSession, pin: str) -> str:
    user = db.query(AuthUser).filter_by(role='parent', active=True).first()
    if not user or not pwd_context.verify(pin, user.pin_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Neplatný PIN')
    now = datetime.utcnow()
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=token_hash(token), user_id=user.id, role=user.role,
                   created_at=now, last_activity_at=now, expires_at=now + IDLE_TIMEOUT))
    user.last_login_at = now
    db.commit()
    return token


def current_parent(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME), db: DbSession = Depends(get_db)) -> AuthUser:
    if not session_token:
        raise HTTPException(status_code=401, detail='Přihlášení rodiče je vyžadováno')
    session = db.query(Session).filter_by(token_hash=token_hash(session_token), role='parent').first()
    now = datetime.utcnow()
    if not session or session.expires_at <= now:
        raise HTTPException(status_code=401, detail='Session vypršela')
    session.last_activity_at = now
    session.expires_at = now + IDLE_TIMEOUT
    db.commit()
    return db.get(AuthUser, session.user_id)


def delete_session(response: Response, session_token: str | None, db: DbSession) -> None:
    response.delete_cookie(COOKIE_NAME)
    if session_token:
        db.query(Session).filter_by(token_hash=token_hash(session_token)).delete()
        db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite='lax', max_age=SESSION_COOKIE_MAX_AGE)

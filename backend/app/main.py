from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .auth import current_parent, ensure_parent, get_db, login_parent, set_session_cookie
from .config import get_settings
from .database import init_db
from .routers import router

class PinLogin(BaseModel):
    pin: str

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from .database import SessionLocal
    db = SessionLocal()
    try:
        ensure_parent(db, get_settings().parent_pin)
    finally:
        db.close()
    yield

settings = get_settings()
app = FastAPI(title='Bakaláři známky a odměny', version='0.3.1', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(router)

@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'backend'}

@app.post('/api/auth/parent/login')
def parent_login(payload: PinLogin, response: Response, db=Depends(get_db)):
    token = login_parent(db, payload.pin)
    set_session_cookie(response, token)
    return {'authenticated': True, 'role': 'parent'}

@app.get('/api/auth/parent/session')
def parent_session(user=Depends(current_parent)):
    return {'authenticated': True, 'role': user.role}

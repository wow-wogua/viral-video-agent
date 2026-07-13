from fastapi import Cookie, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.errors import AppError, ERROR_MESSAGES
from src.auth.security import decode_access_token
from src.config import AUTH_COOKIE_NAME
from src.db.models import User
from src.db.session import get_db
from src.repositories import UserRepository


async def get_current_user(
    session_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id = decode_access_token(session_token or "")
    if not user_id:
        raise AppError(401, "AUTH_REQUIRED", ERROR_MESSAGES["AUTH_REQUIRED"])
    user = await UserRepository(db).get_by_id(user_id)
    if not user or not user.is_active:
        raise AppError(401, "AUTH_REQUIRED", ERROR_MESSAGES["AUTH_REQUIRED"])
    return user

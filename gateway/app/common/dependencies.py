from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import TokenExpiredError, TokenInvalidError, SessionNotFoundError
from app.database import get_db
from app.auth.jwt import decode_access_token
from app.redis_client import get_redis
from app.users.models import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise TokenInvalidError("Missing authorization header")

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise TokenExpiredError()

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise TokenInvalidError("Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise SessionNotFoundError()

    return user

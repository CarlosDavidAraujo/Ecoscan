from http import HTTPStatus
from datetime import datetime, timedelta
from uuid import uuid4

from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from jwt import ExpiredSignatureError, DecodeError, decode, encode

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ecoscan.models import User
from ecoscan.database import get_session
from ecoscan.settings import Settings

settings = Settings()
pwn_context = PasswordHash.recommended()

oauth_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", refreshUrl="/auth/refresh")

def _create_token(data: dict, *, token_type: str, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.now(tz=ZoneInfo("UTC")) + expires_delta
    to_encode.update({"exp": expire, "type": token_type, "jti": str(uuid4())})
    encoded_jwt = encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return encoded_jwt


def create_access_token(data: dict):
    return _create_token(
        data,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(data: dict):
    return _create_token(
        data,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

def verify_password(plain_password, hashed_password):
    try:
        return pwn_context.verify(plain_password, hashed_password)
    except Exception:
        return False
    
def get_password_hash(password):
    return pwn_context.hash(password)


async def _get_user_from_token(
    session: AsyncSession,
    token: str,
    *,
    expected_type: str,
):
    credentials_exception = HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email_sub: str = payload.get("sub")
        if email_sub is None or payload.get("type") != expected_type:
            raise credentials_exception
    except DecodeError:
        raise credentials_exception
    
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    current_user = await session.scalar(select(User).where(User.email == email_sub))
    if current_user is None:
        raise credentials_exception
    return current_user


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    token: str = Depends(oauth_scheme),
):
    return await _get_user_from_token(
        session,
        token,
        expected_type="access",
    )


async def get_current_user_from_refresh_token(
    session: AsyncSession = Depends(get_session),
    token: str = Depends(oauth_scheme),
):
    return await _get_user_from_token(
        session,
        token,
        expected_type="refresh",
    )


oauth_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    refreshUrl="/auth/refresh",
    auto_error=False,
)


async def get_current_user_optional(
    session: AsyncSession = Depends(get_session),
    token: str | None = Depends(oauth_scheme_optional),
) -> User | None:
    if not token:
        return None
    try:
        return await _get_user_from_token(session, token, expected_type="access")
    except HTTPException:
        return None

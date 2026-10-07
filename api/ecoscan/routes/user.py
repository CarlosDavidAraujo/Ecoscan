from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ecoscan.aws.dynamodb import record_audit_log
from ecoscan.database import get_session
from ecoscan.models import User
from ecoscan.schemas import (
    ProfileUpdateResponseSchema,
    UserResponseSchema,
    UserSchema,
    UserUpdateSchema,
)
from ecoscan.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
)


router = APIRouter(prefix="/users", tags=["users"])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/",
    status_code=HTTPStatus.CREATED,
    response_model=UserResponseSchema,
)
async def create_user(user: UserSchema, session: Session) -> User:
    existing_user = await session.scalar(
        select(User).where(
            or_(User.email == user.email, User.name == user.name)
        )
    )
    if existing_user:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Nome de usuario ou email ja existe.",
        )

    new_user = User(
        name=user.name,
        email=user.email,
        password=get_password_hash(user.password),
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    await record_audit_log(
        action="USER_REGISTER",
        user_id=str(new_user.id),
        resource="users",
        details={"name": new_user.name, "email": new_user.email},
    )

    return new_user


@router.get(
    "/",
    status_code=HTTPStatus.OK,
    response_model=UserResponseSchema,
)
async def get_user(user: CurrentUser) -> User:
    return user


@router.put(
    "/",
    status_code=HTTPStatus.OK,
    response_model=ProfileUpdateResponseSchema,
)
async def update_user(
    user_update: UserUpdateSchema,
    session: Session,
    current_user: CurrentUser,
) -> dict[str, object]:
    duplicate = await session.scalar(
        select(User).where(
            User.id != current_user.id,
            or_(
                User.email == user_update.email,
                User.name == user_update.name,
            ),
        )
    )
    if duplicate:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Nome de usuario ou email ja existe.",
        )

    current_user.name = user_update.name
    current_user.email = user_update.email
    session.add(current_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Nome de usuario ou email ja existe.",
        ) from exc
    await session.refresh(current_user)

    return {
        "user": current_user,
        "access_token": create_access_token({"sub": current_user.email}),
        "refresh_token": create_refresh_token({"sub": current_user.email}),
        "token_type": "bearer",
    }

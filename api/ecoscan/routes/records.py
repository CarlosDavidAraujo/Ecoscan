from __future__ import annotations

from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ecoscan.aws.cache import delete_cache, get_cache, set_cache
from ecoscan.aws.s3 import create_thumbnail, delete_from_s3, upload_to_s3
from ecoscan.database import get_session
from ecoscan.models import Identification, User
from ecoscan.schemas import IdentificationResponseSchema
from ecoscan.security import get_current_user


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/octet-stream",
    "image/bmp",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}

history_router = APIRouter(prefix="/history", tags=["history"])
library_router = APIRouter(prefix="/library", tags=["library"])

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _serialize(record: Identification) -> IdentificationResponseSchema:
    image_url = record.image_url if record.image_url else f"/history/{record.id}/image"
    thumbnail_url = record.thumbnail_url if record.thumbnail_url else image_url
    return IdentificationResponseSchema(
        id=record.id,
        plant_name=record.plant_name,
        plant_slug=record.plant_slug,
        confidence=record.confidence,
        recognized=record.recognized,
        created_at=record.created_at,
        in_library=record.in_library,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
    )


async def _owned_record(
    identification_id: UUID,
    session: AsyncSession,
    current_user: User,
) -> Identification:
    record = await session.scalar(
        select(Identification).where(
            Identification.id == identification_id,
            Identification.user_id == current_user.id,
        )
    )
    if record is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Identificacao nao encontrada.",
        )
    return record


@history_router.post(
    "",
    status_code=HTTPStatus.CREATED,
    response_model=IdentificationResponseSchema,
)
async def create_history_record(
    session: Session,
    current_user: CurrentUser,
    image: Annotated[UploadFile, File(description="Imagem identificada.")],
    plant_name: Annotated[str, Form(min_length=1, max_length=255)],
    confidence: Annotated[float, Form(ge=0, le=1)],
    recognized: Annotated[bool, Form()],
    plant_slug: Annotated[str | None, Form(max_length=255)] = None,
    add_to_library: Annotated[bool, Form()] = True,
) -> IdentificationResponseSchema:
    content_type = (image.content_type or "application/octet-stream").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        await image.close()
        raise HTTPException(
            status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            detail="Formato de imagem nao suportado.",
        )

    try:
        image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    finally:
        await image.close()

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            detail="A imagem excede o limite de 10 MB.",
        )

    # 1. Armazenamento S3 (Original + Thumbnail gerado via Pillow)
    from uuid import uuid4

    record_id = uuid4()
    s3_key_original = f"identifications/{current_user.id}/{record_id}.jpg"
    s3_key_thumb = f"identifications/{current_user.id}/{record_id}_thumb.jpg"

    image_url = upload_to_s3(image_bytes, s3_key_original, content_type)
    try:
        thumb_bytes = create_thumbnail(image_bytes, max_size=(300, 300))
        thumbnail_url = upload_to_s3(thumb_bytes, s3_key_thumb, content_type)
    except Exception:
        thumbnail_url = image_url

    record = Identification(
        id=record_id,
        plant_name=plant_name,
        plant_slug=plant_slug,
        confidence=confidence,
        recognized=recognized,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        image_data=image_bytes,
        image_content_type=content_type,
        user_id=current_user.id,
        in_library=add_to_library,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)

    # 2. Invalidação de Cache Redis
    await delete_cache(f"user_history:{current_user.id}")
    if add_to_library:
        await delete_cache(f"user_library:{current_user.id}")

    return _serialize(record)


@history_router.get(
    "",
    response_model=list[IdentificationResponseSchema],
)
async def list_history(
    session: Session,
    current_user: CurrentUser,
) -> list[IdentificationResponseSchema]:
    cache_key = f"user_history:{current_user.id}"
    cached_data = await get_cache(cache_key)
    if cached_data is not None:
        return [IdentificationResponseSchema(**item) for item in cached_data]

    records = await session.scalars(
        select(Identification)
        .where(Identification.user_id == current_user.id)
        .order_by(Identification.created_at.desc())
    )
    serialized = [_serialize(record) for record in records.all()]
    await set_cache(
        cache_key,
        [item.model_dump(mode="json") for item in serialized],
        ttl_seconds=600,
    )
    return serialized


@history_router.get("/{identification_id}/image")
async def get_history_image(
    identification_id: UUID,
    session: Session,
    current_user: CurrentUser,
) -> Response:
    record = await _owned_record(identification_id, session, current_user)
    if record.image_url and record.image_url.startswith(("http://", "https://")):
        return RedirectResponse(url=record.image_url, status_code=HTTPStatus.TEMPORARY_REDIRECT)

    return Response(
        content=record.image_data or b"",
        media_type=record.image_content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@history_router.delete(
    "/{identification_id}",
    status_code=HTTPStatus.NO_CONTENT,
)
async def delete_history_record(
    identification_id: UUID,
    session: Session,
    current_user: CurrentUser,
) -> Response:
    record = await _owned_record(identification_id, session, current_user)

    # Remove do S3 se for chave gerenciada
    s3_key_original = f"identifications/{current_user.id}/{record.id}.jpg"
    s3_key_thumb = f"identifications/{current_user.id}/{record.id}_thumb.jpg"
    delete_from_s3(s3_key_original)
    delete_from_s3(s3_key_thumb)

    await session.delete(record)
    await session.commit()

    # Invalidação de Cache
    await delete_cache(f"user_history:{current_user.id}")
    await delete_cache(f"user_library:{current_user.id}")
    return Response(status_code=HTTPStatus.NO_CONTENT)


@library_router.get(
    "",
    response_model=list[IdentificationResponseSchema],
)
async def list_library(
    session: Session,
    current_user: CurrentUser,
) -> list[IdentificationResponseSchema]:
    cache_key = f"user_library:{current_user.id}"
    cached_data = await get_cache(cache_key)
    if cached_data is not None:
        return [IdentificationResponseSchema(**item) for item in cached_data]

    records = await session.scalars(
        select(Identification)
        .where(
            Identification.user_id == current_user.id,
            Identification.in_library.is_(True),
        )
        .order_by(Identification.created_at.desc())
    )
    serialized = [_serialize(record) for record in records.all()]
    await set_cache(
        cache_key,
        [item.model_dump(mode="json") for item in serialized],
        ttl_seconds=1800,
    )
    return serialized


@library_router.put(
    "/{identification_id}",
    response_model=IdentificationResponseSchema,
)
async def add_to_library(
    identification_id: UUID,
    session: Session,
    current_user: CurrentUser,
) -> IdentificationResponseSchema:
    record = await _owned_record(identification_id, session, current_user)
    record.in_library = True
    session.add(record)
    await session.commit()
    await session.refresh(record)

    await delete_cache(f"user_library:{current_user.id}")
    return _serialize(record)


@library_router.delete(
    "/{identification_id}",
    status_code=HTTPStatus.NO_CONTENT,
)
async def remove_from_library(
    identification_id: UUID,
    session: Session,
    current_user: CurrentUser,
) -> Response:
    record = await _owned_record(identification_id, session, current_user)
    record.in_library = False
    session.add(record)
    await session.commit()

    await delete_cache(f"user_library:{current_user.id}")
    return Response(status_code=HTTPStatus.NO_CONTENT)

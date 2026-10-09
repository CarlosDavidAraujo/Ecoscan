from __future__ import annotations

from typing import Annotated

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ecoscan.aws.cache import get_cache, set_cache
from ecoscan.aws.dynamodb import record_audit_log
from ecoscan.aws.messaging import publish_image_processing_event
from ecoscan.aws.s3 import upload_to_s3
from ecoscan.database import get_session
from ecoscan.models import User
from ecoscan.plant_classifier import (
    ClassificationError,
    InvalidImageError,
    PlantClassifier,
)
from ecoscan.security import get_current_user_optional


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/octet-stream",
    "image/bmp",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}

router = APIRouter(prefix="/plants", tags=["plant recognition"])


class PlantPrediction(BaseModel):
    class_id: int
    slug: str
    name: str
    confidence: float = Field(ge=0, le=1)


class ModelInformation(BaseModel):
    task: str
    architecture: str
    image_size: int


class IdentificationResponse(BaseModel):
    success: bool
    recognized: bool
    plant: PlantPrediction | None
    alternatives: list[PlantPrediction]
    threshold: float
    model: ModelInformation


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_file: str
    device: str
    detail: str | None = None


def get_classifier(request: Request) -> PlantClassifier:
    classifier = getattr(request.app.state, "plant_classifier", None)
    if classifier is None:
        raise HTTPException(
            status_code=503,
            detail="O classificador de plantas nao esta disponivel.",
        )
    return classifier


ClassifierDependency = Annotated[PlantClassifier, Depends(get_classifier)]


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    classifier: ClassifierDependency,
) -> dict[str, object]:
    return {
        "status": "ready" if classifier.ready else "unavailable",
        "model_loaded": classifier.ready,
        "model_file": classifier.model_path.name,
        "device": classifier.device,
        "detail": getattr(request.app.state, "plant_classifier_error", None),
    }


@router.post("/identify", response_model=IdentificationResponse)
async def identify_plant(
    classifier: ClassifierDependency,
    image: Annotated[
        UploadFile,
        File(description="Foto contendo uma planta principal."),
    ],
    confidence_threshold: Annotated[
        float,
        Query(ge=0, le=1, description="Confianca minima para reconhecer."),
    ] = 0.60,
    top_k: Annotated[
        int,
        Query(ge=1, le=10, description="Quantidade de alternativas."),
    ] = 3,
) -> dict[str, object]:
    if not classifier.ready:
        raise HTTPException(
            status_code=503,
            detail="O modelo best.pt ainda nao foi disponibilizado.",
        )

    content_type = (image.content_type or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        await image.close()
        raise HTTPException(
            status_code=415,
            detail="Formato nao suportado. Envie JPG, PNG, WEBP, BMP ou TIFF.",
        )

    try:
        image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    finally:
        await image.close()

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="A imagem excede o limite de 10 MB.",
        )

    try:
        return await run_in_threadpool(
            classifier.predict,
            image_bytes,
            confidence_threshold=confidence_threshold,
            top_k=top_k,
        )
    except InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ClassificationError as exc:
        raise HTTPException(
            status_code=500,
            detail="Nao foi possivel classificar a imagem.",
        ) from exc


@router.post("/identify-async", status_code=202)
async def identify_plant_async(
    image: Annotated[
        UploadFile,
        File(description="Foto da planta para processamento desacoplado."),
    ],
    confidence_threshold: Annotated[
        float,
        Query(ge=0, le=1, description="Confianca minima para reconhecer."),
    ] = 0.60,
    add_to_library: Annotated[
        bool,
        Query(description="Adicionar automaticamente ao Meu Jardim quando concluído."),
    ] = True,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> dict[str, object]:
    """
    Desacoplamento Assíncrono com SNS/SQS (Requisito 6 da AWS):
    1. Salva a foto bruta no S3.
    2. Publica evento no Amazon SNS (que encaminha para a fila SQS).
    3. Responde instantaneamente (HTTP 202 Accepted) liberando o Webservice.
    4. Um Worker desacoplado realiza o rescaling da imagem, executa a inferência YOLO11 e salva no RDS.
    """
    content_type = (image.content_type or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        await image.close()
        raise HTTPException(
            status_code=415,
            detail="Formato nao suportado. Envie JPG, PNG, WEBP, BMP ou TIFF.",
        )

    try:
        image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    finally:
        await image.close()

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="A imagem excede o limite de 10 MB.",
        )

    job_id = str(uuid4())
    user_id = str(current_user.id) if current_user else f"guest_{uuid4()}"
    s3_key = f"identifications/{user_id}/{job_id}_raw.jpg"

    # 1. Envia a imagem original para o S3
    upload_to_s3(image_bytes, s3_key, content_type=content_type)

    # 2. Inicializa status do trabalho no Redis
    initial_status = {
        "job_id": job_id,
        "status": "PENDING",
        "user_id": user_id,
        "s3_key": s3_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await set_cache(f"job:{job_id}", initial_status, ttl_seconds=3600)

    # 3. Publica evento no Amazon SNS (encaminhado para o Amazon SQS)
    message_id = publish_image_processing_event({
        "job_id": job_id,
        "user_id": user_id,
        "s3_key": s3_key,
        "content_type": content_type,
        "confidence_threshold": confidence_threshold,
        "add_to_library": add_to_library,
    })

    # 4. Registra auditoria no Amazon DynamoDB
    await record_audit_log(
        action="JOB_SUBMITTED_ASYNC",
        user_id=user_id,
        resource="sns_publisher",
        details={
            "job_id": job_id,
            "s3_key": s3_key,
            "sns_message_id": message_id,
        },
    )

    return {
        "job_id": job_id,
        "status": "PENDING",
        "poll_url": f"/plants/jobs/{job_id}",
        "sns_message_id": message_id,
        "message": "Imagem enfileirada no Amazon SNS/SQS com sucesso para processamento desacoplado.",
    }


@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Retorna o status atual de um trabalho desacoplado (PENDING, PROCESSING ou COMPLETED)."""
    from sqlalchemy import select
    from ecoscan.models import Identification

    # 1. Consulta primeiro no ElastiCache Redis
    cached = await get_cache(f"job:{job_id}")
    if cached:
        return cached

    # 2. Fallback: consulta no Amazon RDS se o cache tiver expirado
    try:
        record_uuid = UUID(job_id)
        record = await session.scalar(
            select(Identification).where(Identification.id == record_uuid)
        )
        if record:
            return {
                "job_id": job_id,
                "status": "COMPLETED",
                "plant_name": record.plant_name,
                "plant_slug": record.plant_slug,
                "confidence": record.confidence,
                "recognized": record.recognized,
                "image_url": record.image_url,
                "thumbnail_url": record.thumbnail_url,
            }
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Job de identificação não encontrado.")


@router.get("/catalog")
async def get_catalog(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Retorna o catálogo completo de cuidados com as plantas do RDS, acelerado por cache Redis."""
    from sqlalchemy import select

    from ecoscan.aws.cache import get_cache, set_cache
    from ecoscan.models import CatalogSpecies
    from ecoscan.plant_catalog import PLANT_CARE_CATALOG

    cache_key = "plants:catalog"
    cached = await get_cache(cache_key)
    if cached is not None:
        return {"source": "cache", "catalog": cached}

    # Consulta no Amazon RDS
    result = await session.scalars(select(CatalogSpecies).order_by(CatalogSpecies.common_name))
    species_list = result.all()

    if species_list:
        catalog_dict = {
            item.slug: {
                "slug": item.slug,
                "common_name": item.common_name,
                "scientific_name": item.scientific_name,
                "family": item.family,
                "origin": item.origin,
                "abundance": item.abundance,
                "description": item.description,
                "sunlight": item.sunlight,
                "watering": item.watering,
                "fertilizing": item.fertilizing,
                "soil": item.soil,
                "climate": item.climate,
                "pruning": item.pruning,
            }
            for item in species_list
        }
    else:
        catalog_dict = PLANT_CARE_CATALOG

    await set_cache(cache_key, catalog_dict, ttl_seconds=86400)
    return {"source": "database", "catalog": catalog_dict}


@router.get("/catalog/{slug}")
async def get_catalog_item(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Retorna o guia botânico de uma espécie específica do RDS com cache Redis."""
    from sqlalchemy import select

    from ecoscan.aws.cache import get_cache, set_cache
    from ecoscan.models import CatalogSpecies
    from ecoscan.plant_catalog import get_plant_care_guide

    normalized_slug = slug.strip().lower()
    cache_key = f"plants:catalog:{normalized_slug}"
    cached = await get_cache(cache_key)
    if cached is not None:
        return {"source": "cache", "plant": cached}

    # Consulta no Amazon RDS
    item = await session.scalar(
        select(CatalogSpecies).where(CatalogSpecies.slug == normalized_slug)
    )
    if item is not None:
        guide = {
            "slug": item.slug,
            "common_name": item.common_name,
            "scientific_name": item.scientific_name,
            "family": item.family,
            "origin": item.origin,
            "abundance": item.abundance,
            "description": item.description,
            "sunlight": item.sunlight,
            "watering": item.watering,
            "fertilizing": item.fertilizing,
            "soil": item.soil,
            "climate": item.climate,
            "pruning": item.pruning,
        }
    else:
        guide = get_plant_care_guide(normalized_slug)

    if guide is None:
        raise HTTPException(
            status_code=404,
            detail=f"Guia botânico para a espécie '{slug}' não encontrado.",
        )

    await set_cache(cache_key, guide, ttl_seconds=86400)
    return {"source": "database", "plant": guide}

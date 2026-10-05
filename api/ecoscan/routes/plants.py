from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ecoscan.plant_classifier import (
    ClassificationError,
    InvalidImageError,
    PlantClassifier,
)


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


@router.get("/catalog")
async def get_catalog() -> dict[str, object]:
    """Retorna o catálogo completo de cuidados com as plantas, acelerado por cache Redis."""
    from ecoscan.aws.cache import get_cache, set_cache
    from ecoscan.plant_catalog import PLANT_CARE_CATALOG

    cache_key = "plants:catalog"
    cached = await get_cache(cache_key)
    if cached is not None:
        return {"source": "cache", "catalog": cached}

    await set_cache(cache_key, PLANT_CARE_CATALOG, ttl_seconds=86400)
    return {"source": "database", "catalog": PLANT_CARE_CATALOG}


@router.get("/catalog/{slug}")
async def get_catalog_item(slug: str) -> dict[str, object]:
    """Retorna o guia botânico de uma espécie específica com cache Redis."""
    from ecoscan.aws.cache import get_cache, set_cache
    from ecoscan.plant_catalog import get_plant_care_guide

    cache_key = f"plants:catalog:{slug.lower()}"
    cached = await get_cache(cache_key)
    if cached is not None:
        return {"source": "cache", "plant": cached}

    guide = get_plant_care_guide(slug)
    if guide is None:
        raise HTTPException(
            status_code=404,
            detail=f"Guia botânico para a espécie '{slug}' não encontrado.",
        )

    await set_cache(cache_key, guide, ttl_seconds=86400)
    return {"source": "database", "plant": guide}

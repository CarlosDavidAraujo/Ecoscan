from __future__ import annotations

import asyncio
import io
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from ecoscan.aws.cache import delete_cache, set_cache
from ecoscan.aws.dynamodb import record_audit_log
from ecoscan.aws.messaging import delete_queue_message, receive_queue_messages
from ecoscan.aws.s3 import create_thumbnail, get_s3_client, upload_to_s3
from ecoscan.database import engine
from ecoscan.models import Identification
from ecoscan.plant_classifier import PlantClassifier
from ecoscan.settings import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [EcoScan-Worker] %(message)s",
)
logger = logging.getLogger("ecoscan.worker")

_settings = Settings()
_running = True


def handle_sigterm(*_: Any) -> None:
    global _running
    logger.info("Sinal de parada recebido. Encerrando worker graciosamente...")
    _running = False


signal.signal(signal.SIGINT, handle_sigterm)
signal.signal(signal.SIGTERM, handle_sigterm)


def download_from_s3(key: str) -> bytes | None:
    """Baixa o arquivo de imagem do Amazon S3."""
    s3 = get_s3_client()
    if s3 and _settings.AWS_S3_BUCKET_NAME:
        try:
            response = s3.get_object(
                Bucket=_settings.AWS_S3_BUCKET_NAME,
                Key=key,
            )
            return response["Body"].read()
        except Exception as exc:
            logger.error(f"Erro ao baixar imagem do S3 ({key}): {exc}")

    # Fallback local se estiver usando armazenamento em disco
    local_path = Path("uploads") / key.replace("/", "_")
    if local_path.is_file():
        return local_path.read_bytes()

    return None


def rescale_and_optimize_image(image_bytes: bytes, max_dimension: int = 640) -> bytes:
    """
    Manipulação de Imagem Obrigatória (Requisito 6 da AWS):
    Executa o rescaling proporcional (redimensionamento) e otimização para a rede neural.
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        img_format = img.format or "JPEG"
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Redimensiona proporcionalmente mantendo a proporção (aspect ratio)
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()


async def process_job(
    message: dict[str, Any],
    classifier: PlantClassifier,
) -> bool:
    """Processa um trabalho recebido da fila SQS desacoplada."""
    receipt_handle = message.get("receipt_handle")
    payload = message.get("payload", {})

    job_id = payload.get("job_id")
    user_id_str = payload.get("user_id")
    s3_key = payload.get("s3_key")
    content_type = payload.get("content_type", "image/jpeg")
    confidence_threshold = float(payload.get("confidence_threshold", 0.60))
    add_to_library = bool(payload.get("add_to_library", True))

    if not job_id or not s3_key or not user_id_str:
        logger.warning(f"Mensagem inválida recebida no SQS: {payload}")
        if receipt_handle:
            delete_queue_message(receipt_handle)
        return False

    logger.info(f"==> Iniciando processamento desacoplado do Job {job_id} para usuário {user_id_str}")

    # 1. Atualiza status no Redis para PROCESSING
    await set_cache(
        f"job:{job_id}",
        {
            "job_id": job_id,
            "status": "PROCESSING",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
        ttl_seconds=3600,
    )

    try:
        # 2. Baixa a imagem original do S3
        raw_bytes = download_from_s3(s3_key)
        if not raw_bytes:
            raise RuntimeError(f"Imagem não encontrada no S3 para a chave '{s3_key}'")

        # 3. Manipulação de Arquivo (Requisito 6):
        # A) Rescaling para Thumbnail Web (300x300)
        thumb_bytes = create_thumbnail(raw_bytes, max_size=(300, 300))
        thumb_key = f"identifications/{user_id_str}/{job_id}_thumb.jpg"
        thumbnail_url = upload_to_s3(thumb_bytes, thumb_key, content_type="image/jpeg")

        # B) Rescaling proporcional para inferência na rede neural YOLO11 (640x640)
        optimized_bytes = rescale_and_optimize_image(raw_bytes, max_dimension=640)

        # 4. Inferência com YOLO11 (fora da requisição HTTP)
        prediction = classifier.predict(
            optimized_bytes,
            confidence_threshold=confidence_threshold,
            top_k=3,
        )

        plant_name = prediction.get("plant_name", "Desconhecida")
        plant_slug = prediction.get("plant_slug")
        confidence = float(prediction.get("confidence", 0.0))
        recognized = bool(prediction.get("recognized", False))
        candidates = prediction.get("candidates", [])

        # Constrói URL pública da imagem principal
        image_url = (
            f"https://{_settings.AWS_S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
            if _settings.AWS_S3_BUCKET_NAME
            else f"/uploads/{s3_key.replace('/', '_')}"
        )

        # 5. Persiste o resultado no Amazon RDS PostgreSQL
        user_uuid = UUID(user_id_str)
        record = Identification(
            id=UUID(job_id),
            plant_name=plant_name,
            plant_slug=plant_slug,
            confidence=confidence,
            recognized=recognized,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            image_data=None,  # Binário fica no S3
            image_content_type=content_type,
            user_id=user_uuid,
            in_library=add_to_library,
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)

        # 6. Registra log de auditoria no Amazon DynamoDB
        await record_audit_log(
            action="JOB_PROCESSED_ASYNC",
            user_id=user_id_str,
            resource="sqs_worker",
            details={
                "job_id": job_id,
                "plant_name": plant_name,
                "confidence": confidence,
                "recognized": recognized,
                "s3_key": s3_key,
                "thumbnail_url": thumbnail_url,
            },
        )

        # 7. Invalida cache de histórico e jardim no ElastiCache Redis
        await delete_cache(f"user_history:{user_id_str}")
        if add_to_library:
            await delete_cache(f"user_library:{user_id_str}")

        # 8. Atualiza status no Redis com resultado COMPLETED
        result_payload = {
            "job_id": job_id,
            "status": "COMPLETED",
            "plant_name": plant_name,
            "plant_slug": plant_slug,
            "confidence": confidence,
            "recognized": recognized,
            "image_url": image_url,
            "thumbnail_url": thumbnail_url,
            "candidates": candidates,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        await set_cache(f"job:{job_id}", result_payload, ttl_seconds=86400)

        # 9. Deleta a mensagem da fila SQS
        if receipt_handle:
            delete_queue_message(receipt_handle)

        logger.info(
            f"✅ [SUCESSO] Job {job_id} concluído! "
            f"Planta detectada: {plant_name} ({confidence*100:.1f}%)"
        )
        return True

    except Exception as exc:
        logger.error(f"❌ [ERRO] Falha ao processar Job {job_id}: {exc}", exc_info=True)
        # Salva o erro no cache para o frontend saber o motivo
        await set_cache(
            f"job:{job_id}",
            {
                "job_id": job_id,
                "status": "FAILED",
                "error": str(exc),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            ttl_seconds=3600,
        )
        return False


async def run_worker() -> None:
    """Loop principal do Worker que escuta o Amazon SQS."""
    logger.info("==========================================================")
    logger.info("==> EcoScan: Inicializando Worker Desacoplado (SQS/SNS)...")
    logger.info(f"==> Tópico SNS: {_settings.AWS_SNS_TOPIC_ARN}")
    logger.info(f"==> Fila SQS:   {_settings.AWS_SQS_QUEUE_URL}")
    logger.info("==========================================================")

    # Carrega o modelo YOLO11 uma única vez na inicialização do worker
    classifier = PlantClassifier.from_environment()
    try:
        classifier.load()
        logger.info("==> Modelo YOLO11 carregado com sucesso no Worker.")
    except Exception as exc:
        logger.error(f"Não foi possível carregar o modelo YOLO11: {exc}")
        return

    while _running:
        try:
            # Long Polling de 10 segundos na fila SQS
            messages = await asyncio.to_thread(
                receive_queue_messages,
                max_messages=5,
                wait_time_seconds=10,
            )

            if messages:
                logger.info(f"Recebidas {len(messages)} mensagem(ns) da fila SQS.")
                for msg in messages:
                    if not _running:
                        break
                    await process_job(msg, classifier)
            else:
                # Nenhuma mensagem no momento, continua escutando
                await asyncio.sleep(1)

        except Exception as exc:
            logger.error(f"Erro no ciclo do worker: {exc}")
            await asyncio.sleep(5)

    logger.info("Worker EcoScan finalizado com sucesso.")


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker encerrado.")

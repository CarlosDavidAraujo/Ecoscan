from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image

from ecoscan.settings import Settings

logger = logging.getLogger(__name__)

_settings = Settings()


def get_s3_client() -> Any | None:
    """Retorna um cliente S3 usando boto3, ou None caso boto3 não esteja disponível ou sem bucket."""
    if not _settings.AWS_S3_BUCKET_NAME:
        return None

    try:
        import boto3

        client_kwargs: dict[str, Any] = {
            "region_name": _settings.AWS_REGION,
        }
        if _settings.AWS_ACCESS_KEY_ID and _settings.AWS_SECRET_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = _settings.AWS_ACCESS_KEY_ID
            client_kwargs["aws_secret_access_key"] = _settings.AWS_SECRET_ACCESS_KEY
        if _settings.AWS_SESSION_TOKEN:
            client_kwargs["aws_session_token"] = _settings.AWS_SESSION_TOKEN
        if _settings.AWS_S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = _settings.AWS_S3_ENDPOINT_URL

        return boto3.client("s3", **client_kwargs)
    except Exception as exc:
        logger.warning(f"Não foi possível inicializar cliente S3 boto3: {exc}")
        return None


def create_thumbnail(image_bytes: bytes, max_size: tuple[int, int] = (300, 300)) -> bytes:
    """Gera uma versão redimensionada (thumbnail) da imagem usando Pillow, otimizada para Web."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        img_format = img.format or "JPEG"
        if img.mode in ("RGBA", "P") and img_format.upper() in ("JPEG", "JPG"):
            img = img.convert("RGB")
        
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        output = io.BytesIO()
        img.save(output, format=img_format, quality=85, optimize=True)
        return output.getvalue()


def upload_to_s3(
    file_bytes: bytes,
    key: str,
    content_type: str = "image/jpeg",
) -> str:
    """
    Faz upload de bytes de arquivo para o S3.
    Retorna a URL do arquivo no S3.
    Se o S3 não estiver configurado, salva em diretório local de fallback.
    """
    s3_client = get_s3_client()

    if s3_client and _settings.AWS_S3_BUCKET_NAME:
        try:
            s3_client.put_object(
                Bucket=_settings.AWS_S3_BUCKET_NAME,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
            )
            # URL no formato padrão da AWS
            region = _settings.AWS_REGION
            bucket = _settings.AWS_S3_BUCKET_NAME
            if region == "us-east-1":
                return f"https://{bucket}.s3.amazonaws.com/{key}"
            return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        except Exception as exc:
            logger.error(f"Erro ao enviar arquivo para o S3 ({key}): {exc}")

    # Fallback local se S3 não estiver configurado
    local_dir = Path("uploads")
    local_dir.mkdir(parents=True, exist_ok=True)
    file_path = local_dir / key.replace("/", "_")
    file_path.write_bytes(file_bytes)
    return f"/uploads/{file_path.name}"


def delete_from_s3(key: str) -> bool:
    """Remove um arquivo do bucket S3 ou do armazenamento local."""
    s3_client = get_s3_client()

    if s3_client and _settings.AWS_S3_BUCKET_NAME:
        try:
            s3_client.delete_object(
                Bucket=_settings.AWS_S3_BUCKET_NAME,
                Key=key,
            )
            return True
        except Exception as exc:
            logger.warning(f"Erro ao deletar objeto do S3 ({key}): {exc}")
            return False

    local_path = Path("uploads") / key.replace("/", "_")
    if local_path.exists():
        local_path.unlink()
        return True

    return False

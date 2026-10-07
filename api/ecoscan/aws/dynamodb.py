from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import anyio

from ecoscan.settings import Settings

logger = logging.getLogger(__name__)

_settings = Settings()
_dynamodb_resource = None


def get_dynamodb_resource() -> Any | None:
    """Retorna o recurso boto3 para o Amazon DynamoDB."""
    global _dynamodb_resource

    if not _settings.DYNAMODB_ENABLED:
        return None

    if _dynamodb_resource is not None:
        return _dynamodb_resource

    try:
        import boto3

        resource_kwargs: dict[str, Any] = {
            "region_name": _settings.AWS_REGION,
        }
        if _settings.AWS_ACCESS_KEY_ID and _settings.AWS_SECRET_ACCESS_KEY:
            resource_kwargs["aws_access_key_id"] = _settings.AWS_ACCESS_KEY_ID
            resource_kwargs["aws_secret_access_key"] = _settings.AWS_SECRET_ACCESS_KEY
        if _settings.AWS_SESSION_TOKEN:
            resource_kwargs["aws_session_token"] = _settings.AWS_SESSION_TOKEN
        if _settings.DYNAMODB_ENDPOINT_URL:
            resource_kwargs["endpoint_url"] = _settings.DYNAMODB_ENDPOINT_URL

        _dynamodb_resource = boto3.resource("dynamodb", **resource_kwargs)
        return _dynamodb_resource
    except Exception as exc:
        logger.warning(f"Não foi possível inicializar recurso DynamoDB: {exc}")
        return None


def ensure_table_exists() -> bool:
    """Verifica se a tabela de auditoria existe no DynamoDB ou tenta criá-la sob demanda."""
    resource = get_dynamodb_resource()
    if resource is None:
        return False

    try:
        table = resource.Table(_settings.DYNAMODB_TABLE_NAME)
        table.load()
        return True
    except Exception:
        try:
            resource.create_table(
                TableName=_settings.DYNAMODB_TABLE_NAME,
                KeySchema=[{"AttributeName": "log_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "log_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            logger.info(f"Tabela '{_settings.DYNAMODB_TABLE_NAME}' criada com sucesso no DynamoDB.")
            return True
        except Exception as exc:
            logger.warning(f"Tabela DynamoDB não existe e não pôde ser criada automaticamente: {exc}")
            return False


def _sanitize_for_dynamodb(obj: Any) -> Any:
    """Converte tipos incompatíveis com DynamoDB (ex: floats para Decimal, tipos não-primitivos para str)."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: _sanitize_for_dynamodb(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_dynamodb(i) for i in obj]
    if isinstance(obj, (int, str, bool)):
        return obj
    return str(obj)


def _put_audit_item_sync(item: dict[str, Any]) -> bool:
    """Grava o registro de auditoria no DynamoDB de forma síncrona."""
    resource = get_dynamodb_resource()
    if resource is None:
        return False

    try:
        table = resource.Table(_settings.DYNAMODB_TABLE_NAME)
        table.put_item(Item=item)
        logger.info(f"Log de auditoria registrado no DynamoDB: {item.get('action')} - {item.get('log_id')}")
        return True
    except Exception as exc:
        logger.warning(f"Falha ao registrar log no DynamoDB ({item.get('action')}): {exc}")
        return False


async def record_audit_log(
    action: str,
    user_id: str | None = None,
    resource: str | None = None,
    details: dict[str, Any] | None = None,
    status: str = "SUCCESS",
    ip_address: str | None = None,
) -> bool:
    """Grava um evento de auditoria no Amazon DynamoDB de maneira assíncrona e não-bloqueante."""
    if not _settings.DYNAMODB_ENABLED:
        return False

    item: dict[str, Any] = {
        "log_id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "user_id": str(user_id) if user_id else "ANONYMOUS",
        "resource": resource or "general",
        "status": status,
    }

    if details:
        item["details"] = _sanitize_for_dynamodb(details)
    if ip_address:
        item["ip_address"] = ip_address

    # Executa em thread separada para não bloquear o loop de eventos assíncrono do FastAPI
    return await anyio.to_thread.run_sync(_put_audit_item_sync, item)


def _scan_audit_logs_sync(limit: int = 50) -> list[dict[str, Any]]:
    """Consulta os últimos logs de auditoria da tabela DynamoDB."""
    resource = get_dynamodb_resource()
    if resource is None:
        return []

    try:
        table = resource.Table(_settings.DYNAMODB_TABLE_NAME)
        response = table.scan(Limit=limit)
        items = response.get("Items", [])
        # Ordena pelo timestamp decrescente
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items
    except Exception as exc:
        logger.warning(f"Erro ao consultar logs de auditoria no DynamoDB: {exc}")
        return []


async def list_audit_logs(limit: int = 50) -> list[dict[str, Any]]:
    """Retorna os registros de auditoria mais recentes do DynamoDB de forma assíncrona."""
    return await anyio.to_thread.run_sync(_scan_audit_logs_sync, limit)

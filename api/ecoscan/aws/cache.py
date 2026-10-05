from __future__ import annotations

import json
import logging
from typing import Any

from ecoscan.settings import Settings

logger = logging.getLogger(__name__)

_settings = Settings()
_redis_client = None


async def get_redis_client():
    """Retorna o cliente assíncrono do Redis/ElastiCache."""
    global _redis_client

    if not _settings.REDIS_ENABLED:
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(
            _settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        return _redis_client
    except Exception as exc:
        logger.warning(f"Não foi possível inicializar cliente Redis: {exc}")
        return None


async def get_cache(key: str) -> Any | None:
    """Busca um valor no cache e o deserializa de JSON. Retorna None se não encontrar ou falhar."""
    client = await get_redis_client()
    if client is None:
        return None

    try:
        data = await client.get(key)
        if data is not None:
            return json.loads(data)
    except Exception as exc:
        logger.warning(f"Erro ao ler chave '{key}' do cache Redis: {exc}")

    return None


async def set_cache(key: str, value: Any, ttl_seconds: int = 3600) -> bool:
    """Serializa um valor em JSON e grava no cache Redis com tempo de expiração (TTL)."""
    client = await get_redis_client()
    if client is None:
        return False

    try:
        serialized = json.dumps(value, default=str)
        await client.set(key, serialized, ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.warning(f"Erro ao gravar chave '{key}' no cache Redis: {exc}")
        return False


async def delete_cache(key: str) -> bool:
    """Remove uma chave específica do cache Redis."""
    client = await get_redis_client()
    if client is None:
        return False

    try:
        await client.delete(key)
        return True
    except Exception as exc:
        logger.warning(f"Erro ao remover chave '{key}' do cache Redis: {exc}")
        return False


async def delete_keys_by_pattern(pattern: str) -> int:
    """Remove todas as chaves que correspondam a um padrão (ex: 'user_library:123*')."""
    client = await get_redis_client()
    if client is None:
        return 0

    try:
        keys = []
        async for key in client.scan_iter(match=pattern):
            keys.append(key)

        if keys:
            deleted = await client.delete(*keys)
            return deleted
    except Exception as exc:
        logger.warning(f"Erro ao remover chaves com padrão '{pattern}' no Redis: {exc}")

    return 0

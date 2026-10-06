from __future__ import annotations

import json
import logging
from typing import Any

from ecoscan.settings import Settings

logger = logging.getLogger(__name__)

_settings = Settings()
_glide_client = None
_redis_client = None


def _resolve_connection_target() -> tuple[str, int, bool]:
    """Extrai host, porta e TLS das configurações para o Valkey-GLIDE."""
    if _settings.REDIS_HOST:
        return _settings.REDIS_HOST, _settings.REDIS_PORT, _settings.REDIS_USE_TLS

    raw = _settings.REDIS_URL or ""
    use_tls = raw.startswith("rediss://") or _settings.REDIS_USE_TLS

    # Remove o prefixo do protocolo
    cleaned = raw.replace("rediss://", "").replace("redis://", "").split("/")[0]
    if ":" in cleaned:
        parts = cleaned.split(":")
        host = parts[0]
        port = int(parts[1]) if parts[1].isdigit() else 6379
    else:
        host = cleaned or "localhost"
        port = 6379

    # Em endpoints da AWS no formato .cache.amazonaws.com com TLS ativo
    if "cache.amazonaws.com" in host:
        use_tls = True

    return host, port, use_tls


async def get_glide_client():
    """Retorna o cliente nativo da AWS Valkey-GLIDE configurado para o ElastiCache."""
    global _glide_client

    if not _settings.REDIS_ENABLED:
        return None

    if _glide_client is not None:
        return _glide_client

    try:
        from glide import GlideClusterClient, GlideClusterClientConfiguration, NodeAddress

        host, port, use_tls = _resolve_connection_target()
        logger.info(f"Conectando ao ElastiCache com Valkey-GLIDE em {host}:{port} (TLS={use_tls})...")

        addresses = [NodeAddress(host, port)]
        config = GlideClusterClientConfiguration(addresses=addresses, use_tls=use_tls)
        _glide_client = await GlideClusterClient.create(config)
        logger.info("Cliente Valkey-GLIDE conectado com sucesso ao ElastiCache!")
        return _glide_client
    except ImportError:
        logger.debug("valkey-glide não instalado, utilizando fallback redis.asyncio.")
        return None
    except Exception as exc:
        logger.warning(f"Não foi possível conectar com Valkey-GLIDE: {exc}")
        return None


async def get_redis_client():
    """Fallback usando redis.asyncio se o valkey-glide não estiver disponível."""
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
        logger.warning(f"Não foi possível inicializar fallback Redis: {exc}")
        return None


async def get_cache(key: str) -> Any | None:
    """Busca um valor no cache (GLIDE preferencial, fallback redis) e o deserializa de JSON."""
    # 1. Tenta com Valkey GLIDE
    glide = await get_glide_client()
    if glide is not None:
        try:
            raw = await glide.get(key)
            if raw is not None:
                text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                return json.loads(text)
            return None
        except Exception as exc:
            logger.warning(f"Erro ao ler chave '{key}' via Valkey-GLIDE: {exc}")

    # 2. Fallback para redis-py
    redis = await get_redis_client()
    if redis is not None:
        try:
            data = await redis.get(key)
            if data is not None:
                return json.loads(data)
        except Exception as exc:
            logger.warning(f"Erro ao ler chave '{key}' via Redis: {exc}")

    return None


async def set_cache(key: str, value: Any, ttl_seconds: int = 3600) -> bool:
    """Serializa um valor em JSON e grava no cache com tempo de expiração (TTL)."""
    serialized = json.dumps(value, default=str)

    # 1. Tenta com Valkey GLIDE
    glide = await get_glide_client()
    if glide is not None:
        try:
            # Comando padrão com expiração no Valkey/Redis
            await glide.custom_command(["SET", key, serialized, "EX", str(ttl_seconds)])
            return True
        except Exception:
            try:
                await glide.set(key, serialized)
                return True
            except Exception as exc:
                logger.warning(f"Erro ao gravar chave '{key}' via Valkey-GLIDE: {exc}")

    # 2. Fallback para redis-py
    redis = await get_redis_client()
    if redis is not None:
        try:
            await redis.set(key, serialized, ex=ttl_seconds)
            return True
        except Exception as exc:
            logger.warning(f"Erro ao gravar chave '{key}' via Redis: {exc}")

    return False


async def delete_cache(key: str) -> bool:
    """Remove uma chave específica do cache."""
    # 1. Tenta com Valkey GLIDE
    glide = await get_glide_client()
    if glide is not None:
        try:
            await glide.delete([key])
            return True
        except Exception as exc:
            logger.warning(f"Erro ao remover chave '{key}' via Valkey-GLIDE: {exc}")

    # 2. Fallback para redis-py
    redis = await get_redis_client()
    if redis is not None:
        try:
            await redis.delete(key)
            return True
        except Exception as exc:
            logger.warning(f"Erro ao remover chave '{key}' via Redis: {exc}")

    return False


async def delete_keys_by_pattern(pattern: str) -> int:
    """Remove todas as chaves que correspondam a um padrão."""
    redis = await get_redis_client()
    if redis is not None:
        try:
            keys = []
            async for key in redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                return await redis.delete(*keys)
        except Exception as exc:
            logger.warning(f"Erro ao remover chaves com padrão '{pattern}' no Redis: {exc}")

    return 0

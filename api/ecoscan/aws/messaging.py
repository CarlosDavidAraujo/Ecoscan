from __future__ import annotations

import json
import logging
from typing import Any

from ecoscan.settings import Settings

logger = logging.getLogger(__name__)

_settings = Settings()
_sns_client = None
_sqs_client = None


def get_sns_client() -> Any | None:
    """Retorna o cliente boto3 para o Amazon SNS."""
    global _sns_client

    if not _settings.MESSAGING_ENABLED or not _settings.AWS_SNS_TOPIC_ARN:
        return None

    if _sns_client is not None:
        return _sns_client

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

        _sns_client = boto3.client("sns", **client_kwargs)
        return _sns_client
    except Exception as exc:
        logger.warning(f"Não foi possível inicializar cliente SNS: {exc}")
        return None


def get_sqs_client() -> Any | None:
    """Retorna o cliente boto3 para o Amazon SQS."""
    global _sqs_client

    if not _settings.MESSAGING_ENABLED or not _settings.AWS_SQS_QUEUE_URL:
        return None

    if _sqs_client is not None:
        return _sqs_client

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

        _sqs_client = boto3.client("sqs", **client_kwargs)
        return _sqs_client
    except Exception as exc:
        logger.warning(f"Não foi possível inicializar cliente SQS: {exc}")
        return None


def publish_image_processing_event(payload: dict[str, Any]) -> str | None:
    """
    Publica um evento no Amazon SNS notificando que uma nova imagem de planta
    precisa ser manipulada e classificada. O SQS receberá este evento via subscrição.
    """
    client = get_sns_client()
    if client is None or not _settings.AWS_SNS_TOPIC_ARN:
        logger.warning("SNS não configurado ou desabilitado. Publicação ignorada.")
        return None

    try:
        message_body = json.dumps(payload, default=str)
        response = client.publish(
            TopicArn=_settings.AWS_SNS_TOPIC_ARN,
            Message=message_body,
            Subject="PlantImageProcessingEvent",
        )
        message_id = response.get("MessageId")
        logger.info(f"Evento publicado no SNS com sucesso (MessageId: {message_id}, Job: {payload.get('job_id')})")
        return message_id
    except Exception as exc:
        logger.error(f"Erro ao publicar evento no SNS: {exc}")
        return None


def receive_queue_messages(
    max_messages: int = 5,
    wait_time_seconds: int = 20,
) -> list[dict[str, Any]]:
    """
    Consome mensagens da fila Amazon SQS usando Long Polling.
    Desencapsula o payload original enviado pelo SNS.
    """
    client = get_sqs_client()
    if client is None or not _settings.AWS_SQS_QUEUE_URL:
        return []

    try:
        response = client.receive_message(
            QueueUrl=_settings.AWS_SQS_QUEUE_URL,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
            VisibilityTimeout=60,
        )

        raw_messages = response.get("Messages", [])
        parsed_results: list[dict[str, Any]] = []

        for msg in raw_messages:
            receipt_handle = msg.get("ReceiptHandle")
            raw_body = msg.get("Body", "{}")

            try:
                body_data = json.loads(raw_body)
                # O SNS encapsula a mensagem dentro do atributo 'Message'
                if isinstance(body_data, dict) and "Message" in body_data:
                    inner_payload = json.loads(body_data["Message"])
                else:
                    inner_payload = body_data
            except Exception:
                inner_payload = {"raw": raw_body}

            parsed_results.append({
                "message_id": msg.get("MessageId"),
                "receipt_handle": receipt_handle,
                "payload": inner_payload,
            })

        return parsed_results
    except Exception as exc:
        logger.error(f"Erro ao ler mensagens do SQS: {exc}")
        return []


def delete_queue_message(receipt_handle: str) -> bool:
    """Remove uma mensagem da fila SQS após processamento com sucesso."""
    client = get_sqs_client()
    if client is None or not _settings.AWS_SQS_QUEUE_URL:
        return False

    try:
        client.delete_message(
            QueueUrl=_settings.AWS_SQS_QUEUE_URL,
            ReceiptHandle=receipt_handle,
        )
        return True
    except Exception as exc:
        logger.error(f"Erro ao deletar mensagem da fila SQS: {exc}")
        return False

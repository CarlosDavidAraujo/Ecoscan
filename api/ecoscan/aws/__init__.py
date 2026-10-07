"""Módulo de integração com serviços AWS (S3, ElastiCache Redis, DynamoDB, SNS/SQS)."""

from ecoscan.aws.cache import delete_cache, get_cache, set_cache
from ecoscan.aws.dynamodb import list_audit_logs, record_audit_log
from ecoscan.aws.s3 import create_thumbnail, delete_from_s3, get_s3_url, upload_to_s3

__all__ = [
    "upload_to_s3",
    "delete_from_s3",
    "get_s3_url",
    "create_thumbnail",
    "get_cache",
    "set_cache",
    "delete_cache",
    "record_audit_log",
    "list_audit_logs",
]

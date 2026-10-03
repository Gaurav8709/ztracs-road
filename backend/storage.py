"""
Z-TRACS Storage Abstraction Module
Provides storage routing between local filesystem storage and AWS S3 object storage.
Exposes storage methods, presigned upload URL generators, and health verification.
"""

from backend.s3_client import (
    get_s3_config,
    is_s3_enabled,
    get_s3_client,
    upload_file,
    upload_bytes,
    download_file,
    get_file_bytes,
    get_file_stream,
    file_exists,
    generate_presigned_url,
    generate_presigned_upload_url,
    test_s3_connection,
    sync_local_assets_to_s3,
)

__all__ = [
    "get_s3_config",
    "is_s3_enabled",
    "get_s3_client",
    "upload_file",
    "upload_bytes",
    "download_file",
    "get_file_bytes",
    "get_file_stream",
    "file_exists",
    "generate_presigned_url",
    "generate_presigned_upload_url",
    "test_s3_connection",
    "sync_local_assets_to_s3",
]

"""
Z-TRACS Road Intelligence - AWS S3 Storage Client
Provides seamless cloud object storage for inspection videos, evidence imagery,
and generated PDF inspection reports.
Supports pre-signed direct uploads, streaming downloads with byte ranges,
and fallback to local disk storage when running in offline/local mode.
"""
import os
import mimetypes
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

_S3_CLIENT = None


def get_s3_config() -> Dict[str, str]:
    return {
        "access_key": os.getenv("AWS_ACCESS_KEY_ID", ""),
        "secret_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "bucket": os.getenv("S3_BUCKET_NAME", "ztracsroads"),
        "use_s3": os.getenv("USE_S3_STORAGE", "false").lower() in ("true", "1", "yes"),
    }


def is_s3_enabled() -> bool:
    """Return True if S3 storage is enabled and valid credentials exist."""
    cfg = get_s3_config()
    return bool(cfg["use_s3"] and cfg["access_key"] and cfg["secret_key"] and cfg["bucket"])


def get_s3_client():
    """Thread-safe / reused S3 client instance."""
    global _S3_CLIENT
    cfg = get_s3_config()
    if not cfg["access_key"] or not cfg["secret_key"]:
        return None
    if _S3_CLIENT is None:
        boto_config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            region_name=cfg["region"]
        )
        _S3_CLIENT = boto3.client(
            "s3",
            aws_access_key_id=cfg["access_key"],
            aws_secret_access_key=cfg["secret_key"],
            region_name=cfg["region"],
            config=boto_config,
        )
    return _S3_CLIENT


def upload_file(local_path: str, s3_key: str, content_type: Optional[str] = None) -> bool:
    """Upload a local file to S3."""
    client = get_s3_client()
    if not client:
        return False
    cfg = get_s3_config()
    extra_args = {}
    if not content_type:
        content_type, _ = mimetypes.guess_type(local_path)
    if content_type:
        extra_args["ContentType"] = content_type

    clean_key = s3_key.lstrip("/")
    try:
        client.upload_file(
            Filename=local_path,
            Bucket=cfg["bucket"],
            Key=clean_key,
            ExtraArgs=extra_args if extra_args else None
        )
        return True
    except ClientError as e:
        print(f"[S3] Upload error for {clean_key}: {e}")
        return False


def upload_bytes(data: bytes, s3_key: str, content_type: Optional[str] = None) -> bool:
    """Upload byte content directly to S3."""
    client = get_s3_client()
    if not client:
        return False
    cfg = get_s3_config()
    extra_args = {}
    if not content_type:
        content_type, _ = mimetypes.guess_type(s3_key)
    if content_type:
        extra_args["ContentType"] = content_type

    clean_key = s3_key.lstrip("/")
    try:
        client.put_object(
            Bucket=cfg["bucket"],
            Key=clean_key,
            Body=data,
            **extra_args
        )
        return True
    except ClientError as e:
        print(f"[S3] Upload bytes error for {clean_key}: {e}")
        return False


def download_file(s3_key: str, local_path: str) -> bool:
    """Download an S3 object to local disk."""
    client = get_s3_client()
    if not client:
        return False
    cfg = get_s3_config()
    clean_key = s3_key.lstrip("/")
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        client.download_file(
            Bucket=cfg["bucket"],
            Key=clean_key,
            Filename=local_path
        )
        return True
    except ClientError as e:
        print(f"[S3] Download error for {clean_key}: {e}")
        return False


def get_file_bytes(s3_key: str) -> Optional[bytes]:
    """Retrieve file bytes from S3."""
    client = get_s3_client()
    if not client:
        return None
    cfg = get_s3_config()
    clean_key = s3_key.lstrip("/")
    try:
        res = client.get_object(Bucket=cfg["bucket"], Key=clean_key)
        return res["Body"].read()
    except ClientError:
        return None


def get_file_stream(s3_key: str, range_header: Optional[str] = None):
    """Retrieve object stream and metadata from S3, supporting HTTP Range requests."""
    client = get_s3_client()
    if not client:
        return None
    cfg = get_s3_config()
    clean_key = s3_key.lstrip("/")
    params = {"Bucket": cfg["bucket"], "Key": clean_key}
    if range_header:
        params["Range"] = range_header
    try:
        return client.get_object(**params)
    except ClientError as e:
        print(f"[S3] Stream error for {clean_key}: {e}")
        return None


def file_exists(s3_key: str) -> bool:
    """Check if an object exists in S3."""
    client = get_s3_client()
    if not client:
        return False
    cfg = get_s3_config()
    clean_key = s3_key.lstrip("/")
    try:
        client.head_object(Bucket=cfg["bucket"], Key=clean_key)
        return True
    except ClientError:
        return False


def generate_presigned_url(s3_key: str, expires_in: int = 600, http_method: str = "get_object") -> Optional[str]:
    """Generate a pre-signed URL for direct browser access."""
    client = get_s3_client()
    if not client:
        return None
    cfg = get_s3_config()
    clean_key = s3_key.lstrip("/")
    try:
        url = client.generate_presigned_url(
            ClientMethod=http_method,
            Params={"Bucket": cfg["bucket"], "Key": clean_key},
            ExpiresIn=expires_in
        )
        return url
    except ClientError as e:
        print(f"[S3] Presigned URL error for {clean_key}: {e}")
        return None


def generate_presigned_upload_url(s3_key: str, content_type: Optional[str] = None, expires_in: int = 600) -> Optional[Dict[str, Any]]:
    """Generate a pre-signed URL for direct client-to-S3 PUT upload."""
    client = get_s3_client()
    if not client:
        return None
    cfg = get_s3_config()
    clean_key = s3_key.lstrip("/")
    params = {"Bucket": cfg["bucket"], "Key": clean_key}
    if content_type:
        params["ContentType"] = content_type
    try:
        url = client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=expires_in
        )
        return {
            "upload_url": url,
            "method": "PUT",
            "s3_key": clean_key,
            "bucket": cfg["bucket"],
            "expires_in": expires_in,
            "headers": {"Content-Type": content_type} if content_type else {}
        }
    except ClientError as e:
        print(f"[S3] Presigned upload error for {clean_key}: {e}")
        return None


def test_s3_connection() -> Dict[str, Any]:
    """Test S3 credentials and connectivity."""
    client = get_s3_client()
    cfg = get_s3_config()
    if not client:
        return {"status": "disabled", "error": "AWS credentials or bucket not configured"}

    test_key = "system/healthcheck.txt"
    try:
        # 1. Put
        client.put_object(
            Bucket=cfg["bucket"],
            Key=test_key,
            Body=b"Z-TRACS S3 Connectivity OK",
            ContentType="text/plain"
        )
        # 2. Get
        res = client.get_object(Bucket=cfg["bucket"], Key=test_key)
        body = res["Body"].read()
        # 3. Delete
        client.delete_object(Bucket=cfg["bucket"], Key=test_key)
        return {
            "status": "connected",
            "bucket": cfg["bucket"],
            "region": cfg["region"],
            "test_read": body.decode("utf-8", errors="replace"),
        }
    except Exception as e:
        return {
            "status": "error",
            "bucket": cfg["bucket"],
            "region": cfg["region"],
            "error": str(e),
        }


def sync_local_assets_to_s3(static_dir: str) -> Dict[str, int]:
    """Sync static media (evidence images, demo videos, reports) up to S3 if not already present."""
    if not is_s3_enabled():
        return {"uploaded": 0, "skipped": 0, "errors": 0}

    stats = {"uploaded": 0, "skipped": 0, "errors": 0}
    for root, _, files in os.walk(static_dir):
        for f in files:
            if f.startswith(".") or f.endswith(".DS_Store"):
                continue
            local_path = os.path.join(root, f)
            rel_path = os.path.relpath(local_path, static_dir)
            s3_key = rel_path.replace(os.sep, "/")

            if file_exists(s3_key):
                stats["skipped"] += 1
            else:
                ok = upload_file(local_path, s3_key)
                if ok:
                    stats["uploaded"] += 1
                else:
                    stats["errors"] += 1
    return stats

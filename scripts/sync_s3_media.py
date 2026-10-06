#!/usr/bin/env python3
"""
Z-TRACS S3 Media Sync & Bucket Re-Seeding Utility
------------------------------------------------
Uploads all local media assets (videos, evidence frames, reports) to the configured
AWS S3 bucket ('ztracsroads') when USE_S3_STORAGE=true.

Usage:
  python scripts/sync_s3_media.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Auto-load .env file
env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from backend.s3_client import (
    get_s3_config,
    is_s3_enabled,
    test_s3_connection,
    upload_file,
    file_exists
)
from backend.seed_data import seed_demo_data

def sync_media_to_s3(force_reupload: bool = False):
    print("=" * 70)
    print("  Z-TRACS S3 MEDIA & BUCKET RE-SEEDING UTILITY")
    print("=" * 70)

    cfg = get_s3_config()
    print(f"📊 Storage Mode : {'AWS S3 (Cloud)' if cfg['use_s3'] else 'Local Filesystem'}")
    print(f"🪣 Target Bucket: {cfg['bucket']}")
    print(f"🌍 AWS Region   : {cfg['region']}")
    print(f"🔑 AWS Key ID   : {cfg['access_key'][:6]}...{cfg['access_key'][-4:] if len(cfg['access_key']) > 10 else ''}")

    if not cfg["use_s3"]:
        print("\n⚠️  NOTICE: USE_S3_STORAGE is currently set to 'false' in .env.")
        print("   To enable AWS S3 cloud storage and upload files to your bucket:")
        print("   1. Open .env file")
        print("   2. Set: USE_S3_STORAGE=true")
        print("   3. Configure: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME")
        print("=" * 70)
        return

    # Verify S3 Connection
    print("\n🔍 Testing connection to AWS S3 bucket...")
    res = test_s3_connection()
    if res.get("status") != "connected":
        print(f"❌ S3 Connection Failed: {res.get('error')}")
        print("   Please check your AWS credentials and bucket name in .env.")
        print("=" * 70)
        return

    print("✅ Successfully connected to AWS S3 bucket!")

    # 1. Ensure local demo assets exist
    print("\n🌱 Checking local demo assets & media files...")
    seed_demo_data(force=False)

    static_dir = os.path.join(PROJECT_ROOT, "static")
    uploaded = 0
    skipped = 0
    errors = 0

    print("\n🚀 Uploading media files to S3 bucket...")
    for root, _, files in os.walk(static_dir):
        for f in files:
            if f.startswith(".") or f.endswith(".DS_Store"):
                continue
            local_path = os.path.join(root, f)
            rel_path = os.path.relpath(local_path, static_dir)
            s3_key = rel_path.replace(os.sep, "/")

            if not force_reupload and file_exists(s3_key):
                print(f"  ⏭️ [SKIPPED]  {s3_key} (Already exists in S3)")
                skipped += 1
            else:
                ok = upload_file(local_path, s3_key)
                if ok:
                    print(f"  ✅ [UPLOADED] {s3_key}")
                    uploaded += 1
                else:
                    print(f"  ❌ [FAILED]   {s3_key}")
                    errors += 1

    print("\n" + "=" * 70)
    print("✅ [S3 SYNC COMPLETE]")
    print(f"   Uploaded: {uploaded} files")
    print(f"   Skipped : {skipped} files")
    print(f"   Errors  : {errors} files")
    print("=" * 70)

if __name__ == "__main__":
    sync_media_to_s3(force_reupload=True)

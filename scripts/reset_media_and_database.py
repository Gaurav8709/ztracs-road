import os
import sys
import shutil

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

from backend.database import get_connection
from backend.seed_data import seed_demo_data


def reset_all_user_media_and_db():
    print("=" * 70)
    print("Z-TRACS DATABASE & MEDIA RESET UTILITY")
    print("=" * 70)

    # 1. Reset Database
    conn = get_connection()
    cursor = conn.cursor()

    print("🗑️  Cleaning database tables (detections, alerts, metrics, inspections)...")
    cursor.execute("DELETE FROM segment_metrics WHERE inspection_id != 'DEMO-001'")
    cursor.execute("DELETE FROM alerts WHERE inspection_id != 'DEMO-001'")
    cursor.execute("DELETE FROM detections WHERE inspection_id != 'DEMO-001'")
    cursor.execute("DELETE FROM inspections WHERE id != 'DEMO-001'")
    conn.commit()
    conn.close()

    # Reseed clean DEMO-001 dataset
    print("🌱 Re-seeding clean Golden Demo dataset (DEMO-001)...")
    seed_demo_data(force=True)

    # 2. Clear Uploaded Video Files
    video_dir = os.path.join(PROJECT_ROOT, "static", "media", "video")
    if os.path.exists(video_dir):
        print(f"🧹 Sweeping user-uploaded video files in '{video_dir}'...")
        for item in os.listdir(video_dir):
            if item.lower() == "demo_road.mp4" or item.startswith("."):
                continue
            file_path = os.path.join(video_dir, item)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    print(f" -> Removed uploaded video: {item}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
            except Exception as e:
                print(f" ⚠️ Could not remove {item}: {e}")

    # 3. Clear Downloads & Forensics Folders
    for target_folder in ["downloads", "forensics"]:
        folder_path = os.path.join(PROJECT_ROOT, target_folder)
        if os.path.exists(folder_path):
            print(f"🧹 Clearing directory '{target_folder}/'...")
            for item in os.listdir(folder_path):
                if item.startswith("."):
                    continue
                p = os.path.join(folder_path, item)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                    elif os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                except Exception as e:
                    print(f" ⚠️ Could not clear {p}: {e}")

    print("\n✅ [RESET COMPLETE] Database and media files cleaned successfully!")
    print("   Pristine state restored: DEMO-001 active.")
    print("=" * 70)


if __name__ == "__main__":
    reset_all_user_media_and_db()

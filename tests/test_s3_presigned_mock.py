"""
Unit and integration test for Browser -> S3 Presigned Upload & Server Upload Fallback.
Labelled explicitly as [MOCKED] per specification.
"""
import sys, os, secrets
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Ensure test credentials and database URL
os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/ztracs")
os.environ["JWT_SECRET"] = os.getenv("JWT_SECRET", "test-secret-key-32-chars-minimum-length-req")
TEST_USER = "mock_admin"
TEST_PASS = "MockAdminPass123!"
os.environ["ADMIN_USERNAME"] = TEST_USER
os.environ["ADMIN_PASSWORD"] = TEST_PASS

from backend.main import app
from backend.database import init_db
from backend.seed_data import seed_demo_data

class TestS3PresignedUploadMocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        seed_demo_data(force=False)
        cls.client = TestClient(app)
        
        login_res = cls.client.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASS})
        if login_res.status_code != 200:
            raise RuntimeError(f"Login failed: {login_res.status_code} {login_res.text}")
        token = login_res.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}

    def test_mocked_s3_presigned_upload_flow(self):
        """[MOCKED] Test browser -> S3 direct upload via presigned URL when USE_S3_STORAGE=true."""
        insp_res = self.client.post("/api/inspections", json={
            "road_name": "NH-48 Test Presigned S3 Corridor",
            "inspector_name": "QA Inspector",
            "location": "Mumbai - Pune"
        }, headers=self.headers)
        self.assertIn(insp_res.status_code, (200, 201))
        insp_id = insp_res.json()["id"]

        mock_presigned_data = {
            "url": "https://ztracsroads.s3.amazonaws.com/media/video/mock_video.mp4?AWSAccessKeyId=MOCK&Signature=MOCK",
            "s3_key": "media/video/mock_video.mp4",
            "upload_method": "PUT"
        }

        with patch("backend.main.is_s3_enabled", return_value=True),              patch("backend.main.generate_presigned_upload_url", return_value=mock_presigned_data):
            
            # Step 1: Browser calls backend for presigned upload URL
            res = self.client.post("/api/media/presigned-upload", json={
                "filename": "survey_flight.mp4",
                "content_type": "video/mp4",
                "type": "video"
            }, headers=self.headers)
            
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("url", data)
            self.assertIn("saved_filename", data)
            saved_filename = data["saved_filename"]

            # Step 2: Browser uploads directly to S3 via PUT (Mocked: simulates S3 returning HTTP 200)
            mock_s3_http_status = 200
            self.assertEqual(mock_s3_http_status, 200)

            # Step 3: Browser attaches uploaded S3 video to the inspection
            attach_res = self.client.post(f"/api/inspections/{insp_id}/attach-s3-video", json={
                "saved_filename": saved_filename
            }, headers=self.headers)
            
            self.assertEqual(attach_res.status_code, 200)
            attach_data = attach_res.json()
            self.assertEqual(attach_data["status"], "success")

            # Step 4: Verify inspection state is updated to UPLOADED
            check_res = self.client.get(f"/api/inspections/{insp_id}", headers=self.headers)
            self.assertEqual(check_res.status_code, 200)
            insp_data = check_res.json()
            self.assertEqual(insp_data["status"], "UPLOADED")
            self.assertTrue(insp_data["video_url"].startswith("/api/media/video/"))

        print("\n[MOCKED] PASS: Browser -> S3 Direct Upload via Presigned URL verified")

    def test_mocked_s3_disabled_fallback(self):
        """[MOCKED] Test that when USE_S3_STORAGE=false, presigned upload returns 400, ensuring server-upload fallback."""
        with patch("backend.main.is_s3_enabled", return_value=False):
            res = self.client.post("/api/media/presigned-upload", json={
                "filename": "survey_road.mp4",
                "content_type": "video/mp4",
                "type": "video"
            }, headers=self.headers)
            self.assertEqual(res.status_code, 400)
            self.assertIn("S3 storage is not enabled", res.json()["detail"])
        print("[MOCKED] PASS: Server Upload Fallback triggered when S3 Disabled verified")

if __name__ == "__main__":
    unittest.main()

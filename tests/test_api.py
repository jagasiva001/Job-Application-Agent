"""End-to-end API tests. They need the real web stack (pip install -r requirements.txt -r requirements-dev.txt)."""
import base64
import os
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
    HAVE_STACK = True
except ImportError:  # pragma: no cover
    HAVE_STACK = False

JOB = {"url": "https://x.com/1", "company": "Acme", "title": "Junior DevOps Engineer", "location": "Bengaluru",
       "description": "Fresher. Python Docker Linux AWS. 0-1 year experience."}
FORM = {"full_name": "Asha", "roles": "devops engineer", "locations": "bengaluru", "skills": "python, docker, aws, linux",
        "remote": "yes", "experience": "Fresher", "daily_cap": "25"}


@unittest.skipUnless(HAVE_STACK, "fastapi not installed")
class Api(unittest.TestCase):
    def setUp(self):
        from jobengine import config
        import main
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.config = config
        config.DB_PATH, config.APP_PASSWORD = self.path, ""
        self.client = TestClient(main.app)
        self.client.__enter__()  # runs lifespan -> init_db

    def tearDown(self):
        self.client.__exit__(None, None, None)
        os.unlink(self.path)

    def test_full_flow(self):
        c = self.client
        self.assertEqual(c.get("/health").json()["status"], "ok")
        self.assertEqual(c.post("/profile", data=FORM, follow_redirects=False).status_code, 303)
        self.assertIn('value="Asha"', c.get("/").text)  # profile is pre-filled
        self.assertEqual(c.post("/jobs", json=[JOB]).json()["added"], 1)
        job = c.get("/api/jobs").json()[0]
        self.assertEqual(job["status"], "AWAITING_APPROVAL")
        self.assertEqual(c.post("/jobs/999/approve").status_code, 404)
        self.assertEqual(c.post(f"/jobs/{job['id']}/approve").status_code, 200)
        self.assertEqual(c.post(f"/jobs/{job['id']}/approve").status_code, 409)
        self.assertEqual(c.post("/run-batch").json()["queued"], 1)
        self.assertIn("cover_letter", c.get(f"/jobs/{job['id']}/packet").json())
        self.assertEqual(c.post(f"/applications/{job['id']}/status", json={"status": "APPLIED"}).status_code, 200)
        self.assertIn("Junior DevOps", c.get("/export.csv").text)
        self.assertNotIn("resume_text", c.get("/api/profile").json())

    def test_resume_upload(self):
        r = self.client.post("/profile", data=FORM, files={"resume": ("cv.txt", b"Kubernetes engineer")},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        r = self.client.post("/profile", data=FORM, files={"resume": ("cv.exe", b"x")}, follow_redirects=False)
        self.assertEqual(r.status_code, 400)

    def test_cross_site_post_blocked(self):
        r = self.client.post("/score", headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_login_when_password_set(self):
        self.config.APP_PASSWORD = "pw"
        self.assertEqual(self.client.get("/health").status_code, 401)
        good = {"Authorization": "Basic " + base64.b64encode(b"admin:pw").decode()}
        self.assertEqual(self.client.get("/health", headers=good).status_code, 200)


if __name__ == "__main__":
    unittest.main()

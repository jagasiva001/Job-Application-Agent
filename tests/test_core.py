import io
import unittest

from jobengine import connectors, resume, scoring, security, ui
from jobengine.packet import build_packet
from jobengine.skills import extract_skills
from jobengine.textutil import clean_url, has_term, is_http_url, job_key

PROFILE = dict(
    skills="python, fastapi, aws, docker, linux", roles="devops engineer, ai engineer", locations="bengaluru",
    remote=1, hybrid=1, onsite=1, experience="Fresher", sponsorship="No",
    resume_text="Built RAG pipelines with Python and FastAPI.\nDeployed Docker containers with Jenkins CI/CD on AWS.\n",
)
GOOD = dict(title="Junior DevOps Engineer", company="Acme", location="Bengaluru (hybrid)",
            description="Fresher friendly. Python, Docker, Linux, AWS. 0-1 year experience.")
SENIOR = dict(title="Senior DevOps Engineer", company="Big", location="Bengaluru",
              description="5+ years of experience with Kubernetes, Terraform, AWS and Python.")
UNRELATED = dict(title="Sales Executive", company="Shop", location="Mumbai",
                 description="Cold calling and CRM. 2 years experience in sales. On-site in Mumbai.")


class TextUtil(unittest.TestCase):
    def test_whole_word_matching(self):
        self.assertFalse(has_term("maintain training email", "ai"))
        self.assertTrue(has_term("ai-driven products", "ai"))
        self.assertTrue(has_term("we use c++ daily", "c++"))
        self.assertFalse(has_term("javascript developer", "java"))

    def test_urls(self):
        self.assertTrue(is_http_url("https://x.com/a"))
        self.assertFalse(is_http_url("javascript:alert(1)"))
        self.assertEqual(clean_url("HTTPS://X.com/jobs/1/?utm_source=a&id=7#frag"), "https://x.com/jobs/1?id=7")

    def test_job_key_ignores_source_and_url(self):
        self.assertEqual(job_key("Acme", "DevOps  Engineer", "Bengaluru"), job_key("acme", "devops engineer", "BENGALURU"))

    def test_skill_extraction(self):
        s = extract_skills("We use K8s, Terraform and shell scripting; retrieval augmented generation a plus")
        self.assertTrue({"kubernetes", "terraform", "bash", "rag"} <= set(s))


class Scoring(unittest.TestCase):
    def score(self, profile, job):
        return scoring.score_jobs(profile, [job])[0]

    def test_good_match_passes_and_senior_is_capped(self):
        self.assertGreaterEqual(self.score(PROFILE, GOOD).score, 65)
        r = self.score(PROFILE, SENIOR)
        self.assertLessEqual(r.score, 40)
        self.assertTrue(any("5+ years" in x for x in r.reasons))
        self.assertTrue({"kubernetes", "terraform"} <= set(r.gaps))

    def test_unrelated_job_is_low(self):
        self.assertLess(self.score(PROFILE, UNRELATED).score, 40)

    def test_empty_profile_gets_no_free_points(self):
        self.assertLess(self.score({}, GOOD).score, 25)

    def test_no_substring_false_positive(self):
        job = dict(title="Office Admin", company="X", location="", description="maintain training email records")
        r = self.score(dict(skills="ai", experience="Fresher"), job)
        self.assertFalse(any(x.startswith("Matches") for x in r.reasons))

    def test_sponsorship_cap(self):
        job = dict(GOOD, description=GOOD["description"] + " We are unable to sponsor visas.")
        r = self.score(dict(PROFILE, sponsorship="Yes"), job)
        self.assertLessEqual(r.score, 30)

    def test_work_mode_preference(self):
        job = dict(GOOD, location="Remote")
        prefs = dict(PROFILE, remote=0, onsite=0, hybrid=1, locations="")
        self.assertTrue(any("work mode" in x for x in self.score(prefs, job).reasons))

    def test_required_years(self):
        f = scoring.required_years
        self.assertEqual(f("5+ years of experience"), 5)
        self.assertEqual(f("0-1 year experience"), 0)
        self.assertEqual(f("3-5 yrs of experience needed"), 3)
        self.assertEqual(f("Minimum 2 years' experience"), 2)
        self.assertIsNone(f("Founded 10 years ago"))

    def test_embeddings_backend_falls_back_to_tfidf(self):
        r = scoring.score_jobs(PROFILE, [GOOD], backend="embeddings")  # sentence-transformers absent in CI
        self.assertGreater(r[0].score, 0)


class Resume(unittest.TestCase):
    def test_txt(self):
        self.assertIn("hello", resume.extract_text("a.txt", b"hello world"))

    def test_pdf(self):
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(72, 750, "Python and Docker engineer")
        c.save()
        self.assertIn("Docker", resume.extract_text("cv.pdf", buf.getvalue()))

    def test_docx(self):
        import docx
        d = docx.Document()
        d.add_paragraph("Kubernetes and Terraform experience")
        buf = io.BytesIO()
        d.save(buf)
        self.assertIn("Terraform", resume.extract_text("cv.docx", buf.getvalue()))

    def test_unsupported(self):
        with self.assertRaises(ValueError):
            resume.extract_text("cv.exe", b"x")


class Connectors(unittest.TestCase):
    def test_greenhouse_parse(self):
        data = {"jobs": [{"title": "SRE", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                          "location": {"name": "Bengaluru"}, "content": "&lt;p&gt;Python &amp;amp; AWS&lt;/p&gt;"}]}
        j = connectors.parse_greenhouse(data, "acme")[0]
        self.assertEqual((j["title"], j["location"]), ("SRE", "Bengaluru"))
        self.assertNotIn("<", j["description"])
        self.assertIn("Python", j["description"])

    def test_lever_parse(self):
        data = [{"text": "ML Engineer", "hostedUrl": "https://jobs.lever.co/acme/1",
                 "categories": {"location": "Remote"}, "descriptionPlain": "PyTorch"}]
        j = connectors.parse_lever(data, "acme")[0]
        self.assertEqual((j["title"], j["location"], j["description"]), ("ML Engineer", "Remote", "PyTorch"))

    def test_bad_input_rejected_before_any_request(self):
        with self.assertRaises(ValueError):
            connectors.fetch("greenhouse", "../etc/passwd")
        with self.assertRaises(ValueError):
            connectors.fetch("workday", "acme")


class UI(unittest.TestCase):
    def test_escapes_and_prefills(self):
        html = ui.render_home({"full_name": '<script>alert(1)</script>"', "roles": "DevOps", "experience": "1-3 years"})
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('value="DevOps"', html)
        self.assertIn("<option selected>1-3 years</option>", html)
        self.assertNotIn("{{", html)
        self.assertNotIn("[[", html)

    def test_checkbox_state_is_respected(self):
        self.assertIn('name="remote" value="yes" checked', ui.render_home({}))  # new user: all on
        html = ui.render_home({"remote": 0, "hybrid": 1, "onsite": 0})
        self.assertNotIn('name="remote" value="yes" checked', html)
        self.assertIn('name="hybrid" value="yes" checked', html)


class Security(unittest.TestCase):
    def test_origin(self):
        self.assertTrue(security.origin_ok(None, "127.0.0.1:8000"))
        self.assertTrue(security.origin_ok("http://127.0.0.1:8000", "127.0.0.1:8000"))
        self.assertFalse(security.origin_ok("http://evil.example", "127.0.0.1:8000"))

    def test_basic_auth(self):
        import base64
        ok = "Basic " + base64.b64encode(b"admin:pw").decode()
        bad = "Basic " + base64.b64encode(b"admin:nope").decode()
        self.assertTrue(security.basic_auth_ok(None, "admin", ""))      # auth disabled
        self.assertTrue(security.basic_auth_ok(ok, "admin", "pw"))
        self.assertFalse(security.basic_auth_ok(bad, "admin", "pw"))
        self.assertFalse(security.basic_auth_ok(None, "admin", "pw"))
        self.assertFalse(security.basic_auth_ok("Basic !!!", "admin", "pw"))


class Packet(unittest.TestCase):
    def test_packet_uses_only_real_skills(self):
        job = dict(title="DevOps Engineer", company="Acme", description="Docker, Jenkins and Kubernetes required")
        p = build_packet(dict(PROFILE, full_name="Asha"), job)
        self.assertIn("docker", p["matched_skills"])
        self.assertIn("kubernetes", p["skills_to_learn"])
        self.assertNotIn("kubernetes", p["cover_letter"].lower())
        self.assertIn("Acme", p["cover_letter"])
        self.assertTrue(any("Docker" in b for b in p["resume_bullets"]))


if __name__ == "__main__":
    unittest.main()

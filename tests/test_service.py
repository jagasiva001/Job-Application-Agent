import os
import sqlite3
import tempfile
import unittest

from jobengine import db, service

GOOD = dict(url="https://x.com/1?utm_source=a", company="Acme", title="Junior DevOps Engineer", location="Bengaluru",
            description="Fresher. Python Docker Linux AWS. 0-1 year experience.")
MATCHING = dict(full_name="Asha", roles="devops engineer", locations="bengaluru", skills="python, docker, aws, linux",
                remote="yes", hybrid="yes", onsite="yes", experience="Fresher", daily_cap=25,
                resume_text="Deployed Docker containers on AWS.")
OTHER = dict(roles="nurse", skills="nursing", experience="Fresher", daily_cap=25)


class ServiceCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db.init_db(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def job(self, n):
        return dict(url=f"https://x.com/{n}", company="Acme", title=f"DevOps Engineer {n}", location="Bengaluru",
                    description="Python Docker AWS Linux fresher")


class Profile(ServiceCase):
    def test_flags_salary_and_skill_extraction(self):
        with db.connect(self.path) as c:
            service.save_profile(c, dict(MATCHING, hybrid="no", onsite="no", salary_min="3,00,000", skills=""))
            p = service.get_profile(c)
        self.assertEqual((p["remote"], p["hybrid"], p["onsite"]), (1, 0, 0))
        self.assertEqual(p["salary_min"], 300000)
        self.assertIn("docker", p["skills"])  # pulled from resume because skills was blank

    def test_profile_change_rescores_open_jobs(self):
        with db.connect(self.path) as c:
            service.save_profile(c, OTHER)
            service.ingest_jobs(c, [GOOD])
            service.rescore_open(c)
            self.assertEqual(service.list_jobs(c)[0]["status"], "LOW_MATCH")
            service.save_profile(c, MATCHING)
            self.assertEqual(service.list_jobs(c)[0]["status"], "AWAITING_APPROVAL")


class PrefillFields(ServiceCase):
    def test_links_validated_resume_file_kept_and_flag(self):
        with db.connect(self.path) as c:
            service.save_profile(c, dict(MATCHING, linkedin="https://linkedin.com/in/a", github="javascript:alert(1)",
                                         resume_file="/tmp/resume.pdf"))
            service.save_profile(c, MATCHING)  # later save without a new file keeps the stored path
            p = service.get_profile(c)
            self.assertEqual((p["linkedin"], p["github"], p["resume_file"]), ("", "", "/tmp/resume.pdf"))
            service.ingest_jobs(c, [dict(GOOD, url="https://jobs.lever.co/acme/1"), dict(GOOD, url="https://other.com/2", title="Other")])
            service.rescore_open(c)
            for j in service.list_jobs(c):
                service.approve(c, j["id"])
            service.queue_batch(c, "2026-10-04")
            flags = {a["url"]: a["prefill"] for a in service.list_applications(c)}
            self.assertEqual(flags, {"https://jobs.lever.co/acme/1": True, "https://other.com/2": False})
            self.assertEqual(service.prefill_check(c, 999), "not_found")
            self.assertEqual(service.prefill_check(c, 2), "unsupported_site")
            service.set_application_status(c, 1, "APPLIED", "2026-10-04")
            self.assertEqual(service.prefill_check(c, 1), "bad_state")


class Jobs(ServiceCase):
    def test_ingest_dedupes_and_rejects_bad_urls(self):
        with db.connect(self.path) as c:
            r = service.ingest_jobs(c, [GOOD, dict(GOOD, url="https://y.com/other", source="board2"),
                                        dict(GOOD, url="javascript:alert(1)", title="Evil")])
            self.assertEqual(r, {"added": 1, "duplicates": 1, "rejected": 1})
            self.assertEqual(service.list_jobs(c)[0]["url"], "https://x.com/1")  # tracking param removed

    def test_approve_reject_state_checks(self):
        with db.connect(self.path) as c:
            service.save_profile(c, MATCHING)
            service.ingest_jobs(c, [GOOD])
            service.rescore_open(c)
            self.assertEqual(service.approve(c, 999), "not_found")
            self.assertEqual(service.approve(c, 1), "ok")
            self.assertEqual(service.approve(c, 1), "bad_state")  # already approved
            self.assertEqual(service.reject(c, 1), "ok")
            self.assertEqual(service.reject(c, 1), "bad_state")

    def test_low_match_can_be_approved_by_the_user(self):
        with db.connect(self.path) as c:
            service.save_profile(c, OTHER)
            service.ingest_jobs(c, [GOOD])
            service.rescore_open(c)
            self.assertEqual(service.approve(c, 1), "ok")


class Queue(ServiceCase):
    def prep(self, c, n_jobs, cap):
        service.save_profile(c, dict(MATCHING, daily_cap=cap))
        service.ingest_jobs(c, [self.job(i) for i in range(n_jobs)])
        service.rescore_open(c)
        for j in service.list_jobs(c):
            self.assertEqual(service.approve(c, j["id"]), "ok")

    def test_cap_counts_prepared_packets_per_day(self):
        with db.connect(self.path) as c:
            self.prep(c, 3, 2)
            self.assertEqual(service.queue_batch(c, "2026-10-04")["queued"], 2)
            self.assertEqual(service.queue_batch(c, "2026-10-04")["queued"], 0)
            self.assertEqual(service.queue_batch(c, "2026-10-05")["queued"], 1)

    def test_tracker_flow_and_report(self):
        with db.connect(self.path) as c:
            self.prep(c, 1, 5)
            service.queue_batch(c, "2026-10-04")
            self.assertIn("cover_letter", service.get_packet(c, 1))
            self.assertEqual(service.set_application_status(c, 1, "APPLIED", "2026-10-04", "2026-10-11"), "ok")
            self.assertEqual(service.set_application_status(c, 1, "BOGUS", "2026-10-04"), "bad_status")
            self.assertEqual(service.set_application_status(c, 1, "OFFER", "2026-10-04", "11/10/2026"), "bad_date")
            self.assertEqual(service.set_application_status(c, 77, "APPLIED", "2026-10-04"), "not_found")
            r = service.report(c, "2026-10-04")
            self.assertEqual((r["queued_today"], r["applied_today"]), (1, 1))
            self.assertEqual(service.list_jobs(c)[0]["status"], "APPLIED")

    def test_csv_blocks_formula_injection(self):
        with db.connect(self.path) as c:
            service.save_profile(c, MATCHING)
            service.ingest_jobs(c, [dict(self.job(1), title='=HYPERLINK("http://evil","x") DevOps')])
            service.rescore_open(c)
            service.approve(c, 1)
            service.queue_batch(c, "2026-10-04")
            out = service.export_csv(c)
        self.assertIn("'=HYPERLINK", out)
        self.assertNotIn("\n=HYPERLINK", out)


class Database(unittest.TestCase):
    def test_connections_are_closed(self):
        with db.connect(":memory:") as c:
            pass
        with self.assertRaises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")

    def test_v3_database_is_migrated(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            raw = sqlite3.connect(path)
            raw.executescript("""
              CREATE TABLE profile(id INTEGER PRIMARY KEY CHECK(id=1), full_name TEXT, resume_text TEXT, roles TEXT,
                locations TEXT, remote INTEGER, hybrid INTEGER, onsite INTEGER, experience TEXT, skills TEXT,
                salary_min TEXT, salary_max TEXT, notice_period TEXT, visa TEXT, sponsorship TEXT, email TEXT, phone TEXT,
                daily_cap INTEGER, auto_apply INTEGER);
              CREATE TABLE jobs(id INTEGER PRIMARY KEY, job_key TEXT UNIQUE, source TEXT, company TEXT, title TEXT,
                location TEXT, url TEXT, description TEXT, score REAL DEFAULT 0, status TEXT DEFAULT 'NEW', reasons TEXT DEFAULT '[]');
              CREATE TABLE applications(id INTEGER PRIMARY KEY, job_id INTEGER UNIQUE, status TEXT, submitted_at TEXT,
                confirmation TEXT, error TEXT);
              INSERT INTO jobs(job_key,title,company,url,status) VALUES('k','T','C','https://x.com','REQUIRES_BROWSER');
              INSERT INTO applications(job_id,status) VALUES(1,'REQUIRES_BROWSER');""")
            raw.commit()
            raw.close()
            db.init_db(path)
            db.init_db(path)  # idempotent
            with db.connect(path) as c:
                cols = {r["name"] for r in c.execute("PRAGMA table_info(applications)")}
                self.assertTrue({"queued_day", "applied_at", "packet", "follow_up"} <= cols)
                pcols = {r["name"] for r in c.execute("PRAGMA table_info(profile)")}
                self.assertTrue({"linkedin", "github", "resume_file"} <= pcols)
                self.assertEqual(c.execute("SELECT status FROM jobs").fetchone()[0], "APPROVED")
                self.assertEqual(c.execute("SELECT COUNT(*) FROM applications").fetchone()[0], 0)
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 4)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

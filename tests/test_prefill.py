import os
import tempfile
import threading
import unittest

from jobengine import prefill
from jobengine.prefill import apply_url, fill_form, format_report, site_for, split_name

GREENHOUSE_HTML = """<html><body><form id="application_form" onsubmit="window.submitted=true;return false;">
<label for="first_name">First Name</label><input id="first_name" name="first_name">
<label for="last_name">Last Name</label><input id="last_name" name="last_name">
<label for="email">Email</label><input id="email" type="email">
<label for="phone">Phone</label><input id="phone" type="tel">
<input type="file" id="cover_letter" name="cover_letter" style="display:none">
<input type="file" id="resume" name="resume" style="display:none">
<label for="q1">LinkedIn Profile</label><input id="q1">
<label for="q2">GitHub</label><input id="q2">
<button type="submit">Submit Application</button></form></body></html>"""

LEVER_HTML = """<html><body><form onsubmit="window.submitted=true;return false;">
<input type="file" name="resume"><input name="name"><input name="email"><input name="phone"><input name="org">
<input name="urls[LinkedIn]"><input name="urls[GitHub]"><div class="h-captcha"></div>
<button type="submit">Submit application</button></form></body></html>"""

PROFILE = {"full_name": "Asha Rao Kumar", "email": "asha@example.com", "phone": "+91 99999 00000",
           "linkedin": "https://linkedin.com/in/asha", "github": "https://github.com/asha"}


class Urls(unittest.TestCase):
    def test_site_detection_is_exact(self):
        self.assertEqual(site_for("https://boards.greenhouse.io/acme/jobs/1"), "greenhouse")
        self.assertEqual(site_for("https://job-boards.greenhouse.io/acme/jobs/1"), "greenhouse")
        self.assertEqual(site_for("https://jobs.lever.co/acme/abc"), "lever")
        for bad in ("https://boards.greenhouse.io.evil.com/x", "https://evil.com/boards.greenhouse.io",
                    "https://boards.greenhouse.io@evil.com/x", "javascript:alert(1)", "https://linkedin.com/jobs/1", ""):
            self.assertIsNone(site_for(bad), bad)

    def test_apply_url_and_name_split(self):
        self.assertEqual(apply_url("https://jobs.lever.co/acme/abc/", "lever"), "https://jobs.lever.co/acme/abc/apply")
        self.assertEqual(apply_url("https://jobs.lever.co/acme/abc/apply", "lever"), "https://jobs.lever.co/acme/abc/apply")
        self.assertEqual(apply_url("https://boards.greenhouse.io/acme/jobs/1#app", "greenhouse"),
                         "https://boards.greenhouse.io/acme/jobs/1")
        self.assertEqual(split_name("Asha Rao Kumar"), ("Asha", "Rao Kumar"))
        self.assertEqual(split_name("Asha"), ("Asha", ""))


class _Loc:
    def __init__(self, n=1): self.n = n
    def count(self): return self.n
    @property
    def first(self): return self
    def fill(self, *a, **k): self.filled = a
    def set_input_files(self, *a, **k): pass
    def click(self, *a, **k): raise AssertionError("pre-fill must never click")
    def press(self, *a, **k): raise AssertionError("pre-fill must never press keys")
    def check(self, *a, **k): raise AssertionError("pre-fill must never tick boxes")
    def select_option(self, *a, **k): raise AssertionError("pre-fill must never choose options")


class _Page:
    def locator(self, sel): return _Loc(0 if "captcha" in sel else 1)
    def get_by_label(self, rx): return _Loc(1)


class NeverSubmits(unittest.TestCase):
    def test_only_fill_and_upload_are_used(self):
        fd, path = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
        try:
            for site in ("greenhouse", "lever"):
                r = fill_form(_Page(), site, dict(PROFILE, resume_file=path))
                self.assertIn("resume", r["filled"])
        finally:
            os.unlink(path)

    def test_report_text(self):
        t = format_report({"site": "lever", "filled": ["email"], "skipped": [("phone", "not in your profile")], "captcha": True})
        self.assertIn("nothing was submitted", t)
        self.assertIn("phone (not in your profile)", t)
        self.assertIn("CAPTCHA", t)


try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close(); _p.stop()
    HAVE_BROWSER = True
except Exception:  # playwright or chromium not installed
    HAVE_BROWSER = False


@unittest.skipUnless(HAVE_BROWSER, "playwright + chromium not installed")
class RealBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        cls.b = cls.p.chromium.launch(headless=True)
        fd, cls.resume = tempfile.mkstemp(suffix=".pdf"); os.write(fd, b"%PDF-1.4 test"); os.close(fd)

    @classmethod
    def tearDownClass(cls):
        cls.b.close(); cls.p.stop(); os.unlink(cls.resume)

    def page(self, html):
        pg = self.b.new_page(); pg.set_content(html); return pg

    def test_greenhouse_fields_resume_and_no_submit(self):
        pg = self.page(GREENHOUSE_HTML)
        r = fill_form(pg, "greenhouse", dict(PROFILE, resume_file=self.resume))
        self.assertEqual(sorted(r["filled"]), sorted(["first_name", "last_name", "email", "phone", "linkedin", "github", "resume"]))
        self.assertEqual(pg.input_value("#first_name"), "Asha")
        self.assertEqual(pg.input_value("#last_name"), "Rao Kumar")
        self.assertEqual(pg.input_value("#q1"), "https://linkedin.com/in/asha")
        self.assertEqual(pg.eval_on_selector("#resume", "e => e.files.length"), 1)       # resume went to the resume input
        self.assertEqual(pg.eval_on_selector("#cover_letter", "e => e.files.length"), 0)  # not the cover-letter input
        self.assertIsNone(pg.evaluate("window.submitted"))                               # never submitted
        self.assertFalse(r["captcha"])

    def test_lever_fields_captcha_and_no_submit(self):
        pg = self.page(LEVER_HTML)
        r = fill_form(pg, "lever", dict(PROFILE, resume_file=self.resume))
        self.assertEqual(pg.input_value("input[name=name]"), "Asha Rao Kumar")
        self.assertEqual(pg.input_value("input[name='urls[GitHub]']"), "https://github.com/asha")
        self.assertEqual(pg.input_value("input[name=org]"), "")                          # untouched
        self.assertTrue(r["captcha"])
        self.assertIsNone(pg.evaluate("window.submitted"))

    def test_missing_pieces_are_reported_not_guessed(self):
        pg = self.page("<form><input name='email'></form>")
        r = fill_form(pg, "lever", {"full_name": "Asha", "email": "a@b.co"})
        self.assertEqual(r["filled"], ["email"])
        reasons = dict(r["skipped"])
        self.assertEqual(reasons["full_name"], "field not found on this page")
        self.assertEqual(reasons["phone"], "not in your profile")
        self.assertIn("no resume file", reasons["resume"])

    def test_run_end_to_end_with_banner(self):
        seen = []

        def route(page):
            def handler(rt):
                seen.append(rt.request.url)
                rt.fulfill(body=LEVER_HTML, content_type="text/html")
            page.route("https://jobs.lever.co/**", handler)

        # run() starts its own Playwright session (it runs alone in its own process in real use), so call it
        # from a fresh thread: Playwright refuses a second sync session in the thread that already has one.
        out = {}

        def worker():
            try:
                out["r"] = prefill.run(dict(PROFILE, resume_file=self.resume), "https://jobs.lever.co/acme/123",
                                       headless=True, before_goto=route)
                prefill.run(PROFILE, "https://www.linkedin.com/jobs/view/1", headless=True)
            except ValueError as e:
                out["err"] = str(e)

        t = threading.Thread(target=worker); t.start(); t.join(60)
        self.assertEqual(seen[0], "https://jobs.lever.co/acme/123/apply")
        self.assertIn("email", out["r"]["filled"])
        self.assertIn("Greenhouse and Lever", out["err"])  # unsupported site refused before any browser work

    def test_banner_uses_text_not_html(self):
        pg = self.page("<body></body>")
        pg.evaluate(prefill.BANNER_JS, "<img src=x onerror=window.pwned=1>")
        self.assertIsNone(pg.evaluate("window.pwned"))
        self.assertIn("<img", pg.inner_text("#job-engine-banner"))


if __name__ == "__main__":
    unittest.main()

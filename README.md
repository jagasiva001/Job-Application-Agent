# Agentic Job Application Engine v4.2

Python FastAPI backend and native Android client for matching job listings to a candidate profile, organizing application
materials, and tracking application progress.

A local FastAPI app that scores jobs against your profile and resume, explains every score, prepares an
application packet (resume lines + cover-letter draft) and tracks the application. **You submit every
application yourself.** Nothing is auto-submitted, which keeps you inside job sites' terms.

## Run (Windows, macOS, Linux)
```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
uvicorn main:app --reload
```
Open http://127.0.0.1:8000. Flow: save profile (paste or upload a .txt/.pdf/.docx resume) > add jobs (paste JSON or
fetch a Greenhouse/Lever board) > approve matches > **Prepare approved** > open the job (or **Pre-fill form**), apply, mark it applied.

## Android app (new in 4.2)
Open the `android/` folder in Android Studio and build/run the `app` configuration. Start this Python backend first.
For a physical phone, run `uvicorn main:app --host 0.0.0.0 --port 8000` from the backend folder and allow it through
your computer's firewall. In the Android app, set the backend URL; Android Emulator uses `http://10.0.2.2:8000`,
while a physical phone needs the computer's LAN URL. The app can list and score added jobs, approve/reject, prepare packets, track application
statuses, and request AI reviews. Configure the profile in the web app before adding jobs. The Android app keeps the
server URL in app preferences; the Basic Auth password is held in memory only. Use HTTPS on shared networks.

## Push this project to GitHub
1. Extract this project folder and create an **empty** GitHub repository (do not initialize it with a README, license, or `.gitignore`).
2. From the project folder, run:
```bash
git init -b main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
```
Replace the remote URL with your repository's URL. The root `.gitignore` excludes `.env`, databases, uploaded resumes,
and generated files. Commit `.env.example`, but never commit `.env` or an API key. No license is included; choose one
before inviting others to use or modify the code.

## Optional AI review agent (new in 4.2)
The agent uses the OpenAI Responses API and a read-only function tool to inspect the app's existing match evidence,
then returns a fit summary, strengths, gaps, questions to verify, and a cover-letter draft. It cannot change job status,
prepare packets, open browser pages, or submit applications. It runs only when you click **AI review**.
```bash
pip install -r requirements-ai.txt
```
Set `OPENAI_API_KEY` and optionally `AGENT_MODEL` in `.env`, then restart the app. When you request a review, the job
description and selected non-identifying profile fields (target roles, locations, experience, skills, work modes, and
sponsorship preference) are sent to OpenAI. Name, email, phone, full resume text, and uploaded resume file are excluded.
Review all generated claims and drafts before use. The AI feature does not submit applications.

## VS Code
Open the folder in VS Code (File > Open Folder), accept the recommended Python extension, and pick the `.venv`
interpreter (Ctrl+Shift+P > Python: Select Interpreter). Tests appear in the Testing panel; press F5 and choose
"Job Engine (uvicorn)" to run the app with the debugger. `.github/workflows/ci.yml` runs the tests on every push to GitHub.

## Browser pre-fill (new in 4.1, optional)
Opens a visible Chromium window on **your computer**, fills your details, and stops. You review, answer the custom
questions, solve any CAPTCHA and press Submit yourself. Nothing is ever clicked, ticked or submitted by the tool.
```bash
pip install -r requirements-prefill.txt
python -m playwright install chromium
```
Then, on a prepared job whose link is a Greenhouse or Lever page, click **Pre-fill form** (other sites just get **Open job**).
- **Fills:** name, email, phone, LinkedIn, GitHub (set them in your profile) and your resume file (upload a .pdf/.docx
  in the profile once; the original is kept in `uploads/`). A banner on the page lists what was filled and what was not.
- **Does not fill:** cover letters, custom questions, work authorization, EEO/diversity questions, dropdowns, checkboxes.
- **Sites:** `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co` only (exact host match). LinkedIn,
  Naukri and similar sites are deliberately unsupported: they prohibit automation and can ban accounts.
- **Where it runs:** needs a display, so it is switched off in Docker (`PREFILL_ENABLED=0`). Your profile is read from the
  database by the browser process, never passed on a command line. Logs go to `prefill.log`.
- Employers can customise their forms. Fields the tool can't find are reported as "not filled", never guessed.

## What changed from v3
| v3 problem | v4 |
|---|---|
| Form showed `{{NAME}}`; saving blanked your profile | Page is rendered with escaped, pre-filled values |
| Work-mode checkboxes always on | Unchecked means off; defaults to all on only for a new profile |
| Stored XSS (job text in `innerHTML`, `javascript:` links) | All output escaped; only http(s) URLs accepted and linked |
| approve/reject always said success | 404 for missing job, 409 for wrong status |
| `.env` ignored, `AI_PROVIDER=openai` did nothing | `python-dotenv` loaded; the dead OpenAI setting is removed |
| DB connections leaked | Connections always closed |
| Cap counted jobs never applied to | Cap = packets prepared per day; "applied" tracked separately |
| No rescoring | Saving the profile or adding jobs rescores every undecided job; low matches can be approved manually |
| Substring matching ("ai" in "maintain") | Whole-word matching |
| Empty profile scored ~45 | No free points; empty profile scores under 25 |
| Resume, experience, sponsorship unused | Resume similarity (TF-IDF), seniority check ("5+ years" caps score), sponsorship check |
| Dead `SKILLS` list | Skill vocabulary used to extract skills from your resume and show **skills to learn** per job |
| Strict dedupe key | Dedupe on company+title+location; tracking params stripped from URLs |
| Manual JSON only | Greenhouse and Lever connectors |
| `.txt` resume only | `.pdf` and `.docx` too |
| No tracker | Statuses (applied, interview, offer...), follow-up dates, CSV export (formula-injection safe) |
| Single 300-line file | `jobengine/` package + `main.py` routes, startup via lifespan, UTC timestamps, indexes, logging |
| No auth | Optional `APP_PASSWORD` login and cross-site POST blocking |
| No tests | 48 tests (`python -m unittest discover -s tests -t .` or `pytest`) |
| Score never measured | `eval/evaluate.py` precision@k and threshold sweep on jobs you label |

Existing v3 databases migrate automatically on startup (jobs stuck in `REQUIRES_BROWSER` go back to the approved queue).

## Scoring (100 points, every part explained in the UI)
skills 30 + role 20 + resume similarity 20 + location/work mode 15 + experience 15.
Caps: asks for more than your level + 1 year of experience: max 40. Needs sponsorship and the job refuses: max 30.
`MIN_MATCH_SCORE` (default 50) decides AWAITING_APPROVAL vs LOW_MATCH. **Calibrate it:** label 50+ real jobs in
`eval/sample_labels.csv` format and run `python eval/evaluate.py your_labels.csv`.
Optional: `pip install sentence-transformers` and set `MATCH_BACKEND=embeddings` (falls back to TF-IDF if unavailable).

## Security
Fine on localhost. Before running anywhere reachable by others (Docker, AWS), set `APP_PASSWORD` and put it behind HTTPS.
The profile and resume are stored unencrypted in `job_engine.db`.

## Verification status
The v4.1 baseline was documented as having 44 passing unit tests, with API-stack, live employer pages, visible browser
prefill, embeddings, and Docker execution listed as unverified. The v4.2 Android and AI additions have had Python syntax
and Android manifest XML checks, but the full Python test suite, live OpenAI request, and Android Gradle/APK build have
not been run. Build the Android project in Android Studio and run `pip install -r requirements-dev.txt && pytest` to
verify it in your environment.

## Not built (yet)
Pre-fill of cover letters and custom questions, other application sites, salary matching against job salary text,
multi-user accounts, and AI-generated writing stored directly in application packets. The optional AI review is advisory
and returns a separate draft for you to review.

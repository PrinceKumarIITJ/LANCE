# LANCE

A local application workspace for a 2027 Computer Science graduate targeting full-time AI/software roles. Onsite preference: India. Remote preference: worldwide, subject to each employer's country and work-authorization restrictions.

## Run on Windows

From PowerShell:

```powershell
cd 'C:\Users\Prince Kumar\OneDrive\Documents\LARK\LISA\LANCE'
.\run.ps1
```

Open **http://127.0.0.1:8765**. The first run creates a virtual environment and installs Python dependencies; later runs reuse it. Requires Python 3.11+ and Google Chrome for the browser assistant. If your PowerShell execution policy prevents a script from running, run the equivalent commands manually (no policy change is required):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765
```

## The application loop

1. **Your profile:** upload your resume PDF, review extracted text, fill the actual IIT/institution, name, contact details, skills, exact project/experience facts, and earliest full-time joining date. Graduation defaults to 2027; no other personal facts are invented. Each fact should retain project title, dates, contribution and verified metrics.
2. **Career sources:** add Greenhouse, Lever or Ashby company board slugs. Click **Find new openings**. Listings are live API results, not demo data. Board import is a company watchlist, not an internet-wide search engine. Errors appear next to the source.
3. **LinkedIn / other pages:** choose **Import a job**, paste the URL and full description from a real posting. Search inside LinkedIn yourself; automated LinkedIn discovery/Easy Apply navigation is not implemented. This does not bypass login, CAPTCHA or platform restrictions.
4. **Job pipeline:** inspect the relevance score and eligibility reasons. Scoring uses deterministic keywords and conservative checks; it does not establish eligibility. Remote roles always require country-restriction review. Roles specifying other graduation years, seniority, experience, or internships are flagged. Year ranges are expanded. Minimum-experience parsing is conservative and cannot understand every wording.
5. **Prepare materials:** generates a real resume PDF and cover-letter text from the profile. Only the ordering of your verified facts changes. Drafts need review for layout, facts and relevance. Standard fonts may not render non-Latin text fully. User-uploaded original PDF is stored separately; the **generated, reviewed PDF** is attached to applications.
6. **Approve packet:** review the PDF, cover letter, batch eligibility, joining date, location and work authorization. Check the two explicit review boxes.
7. **Browser:** open the portal in the dedicated Chrome profile. Log in yourself. Navigate through the real application/Easy Apply screens yourself, then choose **Fill current form** to fill supported exact-label fields and the resume. Unknown questions, radio/checkbox choices, custom dropdowns and consent need your input. Exact question/answer pairs can be saved in your profile. Repeat fill on later steps. Choose **Submit reviewed form** only on the final screen after review. A unique recognized submit button and native required-field validity are checked. Custom portals may still need manual completion.
8. **Submission:** only explicit confirmation text records success; a private screenshot and text evidence are kept. Missing confirmation or interrupted submit marks `uncertain`, which is never retried automatically. Check the portal/email and record the result with confirmation notes.
9. **HR outreach:** import your own real contacts CSV; source is mandatory. Prepare a role's packet, then create an email draft for a matching-company contact. Review/edit the subject and body, save edits, then send. One recipient per email; resume attached. Contacts are never guessed or harvested.
10. **Replies / tracking:** mailbox sync reads the latest 100 messages and correlates replies using thread IDs from emails sent by this app. It displays possible interview/offer/rejection signals for review; ATS emails not in those threads need manual tracking. Record outcomes with notes and export CSV as needed.

## What runs automatically

Enable scheduled discovery in **Automation** (default off), optionally followed by draft preparation for potential matches. The local process must remain open and the laptop awake. Optional **Automatically submit approved applications** processes reviewed `ready` packets, one per 15-second worker cycle. It opens Chrome, fills supported exact-label fields and submits only if all encountered fields are supported and required-field checks pass. Login, navigation, consent, unknown questions and custom controls pause the job as `needs_input`; complete those yourself and use the manual browser controls. **Automatically send queued HR emails** delivers up to five reviewed, explicitly queued drafts per cycle within the daily limit. Queued/sent/uncertain email applications are excluded from automatic browser application to avoid using both channels automatically. Remove a queued email from its detail view to cancel it. Both submission switches default off. No email or application is sent merely by starting a fresh app. This release does not implement automatic LinkedIn searches, arbitrary-form reasoning, auto follow-ups, or an application-to-every-company sweep. Real portals may require manual completion; automatic submissions are limited to fully supported forms.

## Email connection

Stop an existing app instance before connecting. Use:

```powershell
.\connect-mail.ps1
```

The script asks locally for your Gmail address and app password using a hidden prompt and starts the app with credentials in its process environment, not in source files or command-line arguments. Do not send credentials in chat. It removes its temporary credential variables when the app exits. Your Google account must allow app passwords and have 2-Step Verification. Some college/managed accounts do not allow this. This version has **no Google OAuth integration**. If app passwords are unavailable, use browser/manual email or a supported SMTP account configured through environment variables; never enable insecure authentication.

For another provider, configure `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_HOST`, `SMTP_PORT` (implicit TLS only; default 465), and `IMAP_HOST` in the launching process. Sender must match the profile email. SMTP acceptance means the sending server accepted the message, not guaranteed delivery or a portal application. Email outreach is tracked separately from portal submission. The default maximum is 10 emails per UTC day, configurable up to 50. Ambiguous sends are marked uncertain and cannot be automatically resent. Thread sync is read-only and bounded to the latest 100 inbox messages.

## Optional local AI

The system works without any AI API key. Default tailoring uses keyword overlap to reorder your actual facts. If Ollama is already installed with a model available, set its exact model name before launch:

```powershell
$env:OLLAMA_MODEL = 'your-installed-model-name'
.\run.ps1
```

Ollama is called only at `127.0.0.1:11434`. It receives the posting and supplied facts; the accepted output is a list of valid fact IDs, never generated candidate claims. Invalid/unavailable output falls back to keyword ordering. An inference request can take up to 90 seconds. No model is downloaded automatically.

## Data and operation

- `data/pilot.db`: SQLite profile, sources, jobs, contacts, outbox, audit history and reply excerpts.
- `data/original-resume.pdf`: original upload.
- `data/packets/<job-id>/`: generated resume, cover letter and source-fact manifest.
- `data/browser-profile/`: separate Chrome login/session state. Your everyday Chrome profile is not used.
- `data/evidence/`: application confirmation screenshots.

The entire `data/` folder is gitignored; protect it like your resume and login sessions. This checkout is inside OneDrive, so local files may sync according to your existing OneDrive configuration. To keep runtime data elsewhere, set `JOB_PILOT_DATA` to a directory you control before starting the app. Do not put runtime data in a public repository. The service binds only to loopback, rejects other hostnames/cross-origin mutations, requires a per-process request token, and adds response security headers. It is a single-user local service, not a hosted multi-user deployment. Do not expose its port publicly.

Restart recovery marks in-flight submissions/sends uncertain. Saving profile changes invalidates unsubmitted packet approvals and deletes unsent/queued drafts. Material changes in a re-fetched posting also invalidate approval. Restarting pauses in-progress browser preparation as needs_input. Discovery does not detect all expired jobs; verify the actual page before submitting. Cross-provider reposts with different URLs may still duplicate; canonical URL tracking removes query tracking parameters, not different employer postings. No success or job offer is guaranteed.

## Verification

```powershell
python -m pytest -q
node --check static/app.js
```

Tests use a separate temporary data directory and mocked provider/mail responses. They do not send email or submit any real applications. Browser end-to-end checks, when Chrome is available, use local synthetic forms and a temporary browser context.

## Official integration references

- [Greenhouse public Job Board API](https://docs.greenhouse.io/job-board) — reading jobs is public; its application POST requires an employer key, so this app uses the candidate-facing browser form.
- [Lever Postings API](https://github.com/lever/postings-api) — public listing API and hosted application URLs.
- [Ashby public job postings](https://developers.ashbyhq.com/docs/public-job-posting-api) — job board listing schema.
- [Playwright persistent browser context](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).
- [Google app-password availability](https://support.google.com/accounts/answer/185833).
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

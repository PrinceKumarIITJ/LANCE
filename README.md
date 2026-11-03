# LANCE

A local job-application system for a 2027 Computer Science graduate targeting full-time AI Engineer and software roles. Onsite: India. Remote: worldwide, subject to employer country restrictions.

## Start

Install Python 3.11+ and Google Chrome, then run inside this checkout:

```powershell
.\run.ps1
```

Open **http://127.0.0.1:8765**. On macOS/Linux use `sh run.sh`. The app stays on your laptop; keep it open and the laptop awake for scheduled work.

## Workflow

1. **Profile:** upload your resume and add verified skills/projects, actual institution and earliest joining date. Supporting documents can suggest evidence for review.
2. **Discover:** watch company career boards (Greenhouse, Lever, Ashby), search LinkedIn in your own Chrome session, import structured career URLs or paste postings.
3. **Evaluate:** review five-dimension scores and explicit graduation, experience, full-time, location and joining-date unknowns.
4. **Prepare:** generate tailored resume and cover-letter PDFs, ATS/text/page-budget checks, source-fact manifest, optional custom LaTeX templates.
5. **Apply:** supported company forms and LinkedIn Easy Apply Next/Review navigation; optional automatic submission of reviewed packets. Unknown fields/login/consent pause for you. Confirmation evidence is required to record success.
6. **Email:** connect your Gmail account using OAuth, or a supported SMTP account. Add one HR email or upload CSV/XLSX; create personalized campaigns, preview, approve and automatically deliver separate messages with your resume attached.
7. **Track:** thread-correlated replies, outcomes, application archives, follow-up reminders and offline HTML/CSV exports.
8. **Prepare further:** interview packs, factual STAR scaffolds, application-field drafts, skill-gap plans, GitHub evidence and optional Notion sync.

## Documentation

- [Complete setup, Gmail connection, LinkedIn and privacy](docs/SETUP.md)
- [CLI / slash-command equivalents](docs/COMMANDS.md)
- [Coverage and differences from the supplied PDF](docs/PDF_PARITY.md)

## HR sheet to email

Use HR outreach to add one address or upload an 8 MB CSV/TSV/XLSX sheet (up to 2,000 unique contacts). Common email/name/company headers are recognized. Formulas are not executed; invalid rows are reported. Mail campaigns creates one personalized message per recipient. Review the attached resume and messages, approve the campaign, then enable automatic sending. Default: 10 per UTC day, 14-day recipient cooldown. Caps and duplicate protection are shared with role-specific outreach. Unknown names/companies use neutral text.

Gmail OAuth needs your own Google Cloud Desktop client with Gmail API enabled and your account allowed by its consent/test-user configuration. Windows protects token files with per-user DPAPI; Unix uses owner-only permissions. The profile email must match the sending account. No passwords or tokens belong in Git or chat.

## Automation and practical limits

Submission and sending switches default off. They act only on approved packets or explicitly queued campaigns/drafts. Discovery and draft preparation can run on a schedule. Login, CAPTCHA, legal/compensation questions, consent and unsupported controls require user input. LinkedIn page layouts can change; its connector needs validation in your authenticated session. External Apply jobs may need the company-site flow. An uncertain send/submit is never blindly retried. Email acceptance is not proof of delivery or a portal application.

No actual application or email is sent by a fresh installation. The app cannot guarantee universal portal coverage, eligibility, interviews or employment. It does not invent achievements, company facts or salary benchmarks. Optional Ollama/Anthropic inference only orders valid fact IDs; deterministic tools work without an AI account. Cloud inference uses your configured provider and its account charges.

## Data

Private profile, resume, contacts, Chrome session, credentials, generated documents and SQLite tracking stay in `data/`, which is excluded from Git. Set `LANCE_DATA` to a dedicated private directory if desired. This checkout may be under OneDrive; your existing sync policy applies. The service binds only to loopback and is single-user. Do not expose its port publicly.

The earlier `job-pilot` folder is separate. To reuse its tracker, stop both apps and point `LANCE_DATA` at its dedicated `data` directory; migration preserves records. Never copy that directory into tracked source.

## Tests

```powershell
python -m pytest -q
node --check static/app.js
node --check static/features.js
node --check static/toolkit.js
```

Tests use temporary storage, fake mail transports and synthetic browser forms. They do not send to real HR contacts or apply to real jobs. Browser tests need Google Chrome; other tests do not need login or API keys. CI runs on Windows and Linux. Authenticated Gmail/LinkedIn and optional external integrations require the user's setup before live validation.

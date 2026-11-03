# LANCE setup

LANCE runs on your laptop at http://127.0.0.1:8765. Keep it running and keep the laptop awake for scheduled discovery and delivery. Do not expose the port publicly.

## 1. Install and start

Install Python 3.11+ and Google Chrome. In PowerShell inside the LANCE checkout:

    .\run.ps1

This creates .venv and installs dependencies. It updates dependencies whenever requirements.txt changes. If your execution policy blocks scripts, use:

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe launch.py

On macOS/Linux, run `sh run.sh`. The browser connector expects an installed Chrome channel. LaTeX is optional; default PDFs use ReportLab.

## 2. Complete your profile

Open Your profile. Add your real name, email, IIT/institution, degree, phone, skills, expected graduation and earliest full-time joining date. Upload your resume PDF. Defaults: expected graduation 2027, full-time AI/software roles, onsite India, remote worldwide subject to country restrictions.

Add verified project/experience facts with names, dates, your own contribution and measured results. Those facts are the only claims used in generated resumes. Upload supporting PDF/DOCX/TXT/MD documents and review evidence suggestions if useful. Suggestions never silently alter your profile. User-supplied preferences provide the work-style dimension; there is no inferred personality assessment.

## 3. Connect your Gmail account

Preferred: Google OAuth, configured in Automation.

1. In your own Google Cloud project, enable Gmail API.
2. Configure the OAuth consent screen. For a personal app in Testing, add your own Gmail account as a test user. Account/organization restrictions may apply. Testing tokens for Gmail scopes can expire after seven days; reconnect when needed.
3. Create an OAuth client of type Desktop app, and download its client JSON. A service account or Web app client is not the same thing.
4. In LANCE Automation, choose Upload OAuth client JSON. It is stored only in the local data folder.
5. Click Connect Gmail, then Continue to Google sign-in in your normal browser. Grant sending and read-only mailbox access. The callback is http://127.0.0.1:8765/oauth/google/callback, so keep LANCE running on that port.
6. Return to Automation and refresh. Ensure the connected account email matches the email in Your profile.

LANCE uses PKCE and a short-lived state value. Windows uses per-user DPAPI to protect stored client/token files. On Unix, files use owner-only permissions; OS disk encryption is your responsibility. OAuth credentials and Chrome cookies never go to GitHub. Disconnect removes the local Gmail token; revoke access in Google Account settings if desired.

Alternative: SMTP/app password. Stop LANCE and run .\connect-mail.ps1. The password prompt is hidden and values are passed only through the launching process environment. Gmail app passwords require 2-Step Verification and are not available for every account. Do not use your normal account password. Other providers can use SMTP_USER, SMTP_PASSWORD, SMTP_HOST, SMTP_PORT (implicit TLS, default 465), IMAP_HOST. Outlook-specific OAuth is not implemented; use a provider-supported SMTP setup only if your account allows it.

Official references:
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/workspace/gmail/api/guides/sending
- https://developers.google.com/identity/protocols/oauth2#expiration
- https://support.google.com/accounts/answer/185833

## 4. Send to one HR email or a whole sheet

Open HR outreach. Choose Single email or Upload CSV / XLSX. Common headers such as Email ID, HR Email, Name and Company are recognized. Email is required; company/name may be absent and receive neutral wording. Formulas are not evaluated. Invalid rows are reported; valid rows are imported and duplicate addresses removed. Legacy .xls files need conversion to .xlsx or UTF-8 CSV. Import supports 2,000 unique contacts and 8 MB per file.

Open Mail campaigns and create a campaign:

- Select one or multiple contacts.
- Select your uploaded original resume, or a job-specific generated resume.
- Set the role and edit the subject/body templates. Supported variables are listed in the form.
- Preview the actual personalized messages and attached resume.
- Approve and queue the campaign. This authorizes those individual emails.
- Click Start automatic sending of approved queues, or enable it in Automation.

The worker sends individual messages, never one mass CC/BCC. Daily cap defaults to 10 and can be set to 1–50 per UTC day. The recipient cooldown defaults to 14 days. Caps count both role-specific emails and campaign emails; uncertain sends count toward the cap. Pause leaves an already in-progress send free to complete. Sender acceptance does not guarantee delivery, a response, or a portal application. An interrupted send is marked uncertain and is not automatically retried. Read your Sent folder before resolving ambiguity.

Profile changes invalidate unsent/queued campaign approvals; create a fresh campaign with the updated profile. Campaigns archive the exact resume attachment. Contact changes should be made before creating/reviewing a campaign.

## 5. Discover and apply

Career sources support Greenhouse, Lever and Ashby board slugs. Use Find new openings or scheduled discovery. Other public career URLs can be imported if they expose JSON-LD JobPosting; otherwise paste the description. Discovery is a watchlist, not exhaustive worldwide coverage. Closed job detection is limited; check the live page.

Scoring uses Technical 30, Experience 25, Work preferences 15, Career alignment 30, plus a location gate. Eligibility checks are separate and conservative. Review graduation ranges, professional experience, full-time status, start date and country/work authorization. Remote does not necessarily mean hiring in India. Unknowns remain explicit.

For a role: prepare materials, review resume PDF and cover letter, resolve machine review issues, then approve eligibility/materials. The generated resume has a two-page limit and must preserve extractable text and the email. Review Unicode/font support. The packet includes PDF and LaTeX source. Custom .tex templates are activated only after a successful local test compile and parseability check; install MiKTeX/TeX Live first.

The browser connector fills known labels and exact saved answers; it does not guess authorization, sponsorship, compensation or consent. Unknown fields stop automation. Open Chrome, finish any manual fields, then use Fill current form or the LinkedIn resume action. Successful portal submissions need recognizable confirmation text. Otherwise the result is uncertain and will not be blindly retried. Record manual confirmation with notes when necessary.

## 6. LinkedIn

Open LinkedIn in the sidebar and choose Open LinkedIn login. Log in inside the dedicated visible Chrome profile. Check session, then search for full-time entry-level roles in India or your desired remote region. LANCE imports readable rendered job details; current selectors may need updates when LinkedIn changes its UI.

Prepare/approve an imported job and open its details. Start Easy Apply walks through supported Next/Continue/Review steps. Unknown answers, consent, login, navigation errors or custom controls pause it as needs_input. Complete and review the visible step, then choose I reviewed this step — resume Easy Apply. By default it stops on final review; Submit reviewed form performs the final action. Optional Automatically submit approved applications allows the worker to submit supported complete flows after packet approval.

External Apply buttons are not treated as Easy Apply. Follow the company link and import its career page or finish manually. LANCE does not have LinkedIn partner/API access and does not bypass CAPTCHAs or security checks. Browser selectors were tested on synthetic forms; your authenticated live account is needed to validate the current LinkedIn UI.

Official API access reference: https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access

## 7. Track, prepare, and improve

Use outcome notes and download application archives. Archives contain the job, material versions, reviewer output, interview artifacts and confirmation evidence. HTML reports are standalone downloads with a searchable table, stage counts and activity totals.

Gmail/IMAP sync reads at most the latest 100 inbox messages. Replies are correlated by message thread IDs to emails sent by LANCE. It recognizes possible interview/offer/rejection signals for review; it does not silently update outcomes. Unrelated ATS messages are not reliably correlated and may require manual tracking. Optional background sync runs every ten minutes.

Career toolkit provides stage-specific question banks and STAR scaffolds anchored to your facts, skill-gap frequency and official learning links, GitHub metadata evidence discovery, application-field drafts, and date-based follow-up reminders. Estimates and structure feedback are heuristics, not guarantees or a technical assessment of your answers. Company research fetches user-selected public HTTPS sources with a 30-day cache and source excerpts. Interviewer-specific investigation is not automatic.

## 8. Optional AI and Notion

AI is optional. Set OLLAMA_MODEL to an already installed local model, or set ANTHROPIC_API_KEY and ANTHROPIC_MODEL in the launching environment. Anthropic uses API version 2026-10-21 by default (override ANTHROPIC_API_VERSION for an account-supported version). Cloud inference sends the selected facts/job description to that provider and may incur your account's usage charges. No provider is contacted without configuration. AI is restricted to ordering valid fact IDs; fabricated candidate text is not accepted. Invalid output falls back to deterministic ordering.

For Notion, create an integration, share your existing database/data source with it, and set NOTION_TOKEN and NOTION_DATA_SOURCE_ID locally. Required properties: a title property and URL (url type). Optional: Company, Role and Stage (rich_text), Score (number). Sync is one-way from local jobs; it finds existing rows by exact URL before updating/creating. Existing duplicate URLs are reported, not multiplied. It does not delete Notion pages or modify local outcomes from Notion. No credentials are entered into source files.

## Local data

Everything private is in data/ (or LANCE_DATA if explicitly configured). This checkout is under OneDrive, so runtime files may sync according to your existing OneDrive settings. To keep data elsewhere, set LANCE_DATA to a dedicated private folder before launch. Do not point it at a directory containing unrelated documents.

Update source with git pull, then run again; the launcher updates changed dependencies. Only one server may use a data folder. The earlier job-pilot app remains separate. If you want its existing tracker data, stop both apps and set LANCE_DATA to its dedicated data folder; the schema migration adds fields without clearing records. Do not copy runtime data into tracked source.

For commands and explicit reset behavior, read docs/COMMANDS.md. Reset requires the literal RESET confirmation and never recursively deletes arbitrary folders. Browser sessions, mailbox credentials and templates are retained and need separate disconnect/removal if desired.

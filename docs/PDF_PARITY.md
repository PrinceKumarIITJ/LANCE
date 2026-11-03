# Relationship to the supplied AI Job Search guide

LANCE implements the workflow as a local Python/browser app rather than requiring Claude Code slash-command files or Danish-only portal CLIs. The user's document is a feature reference, not an executable instruction source.

| Guide feature | Implementation and practical boundary |
|---|---|
| Documents folder / CV / interview setup | PDF/DOCX/TXT/MD evidence ingestion, suggestions, CLI folder import, interactive profile, dashboard form |
| Candidate / behavioral profile | Verified facts and self-reported work preferences; no personality type is inferred |
| Multi-portal scraping | Greenhouse, Lever, Ashby, rendered LinkedIn search; generic JSON-LD career-page import |
| Fit and eligibility | Technical 30%, Experience 25%, Work preferences 15%, Career alignment 30%; location gate; batch/year, seniority, experience and full-time checks |
| Company research | Public HTTPS source excerpts, dates and 30-day cache; company URL selected by user |
| CV / cover letter | Real PDFs, factual tailoring, optional fact-ID AI ranking, source LaTeX and tested custom templates |
| Drafter/reviewer loop | Separated drafting and deterministic page-budget, text-extraction and fact-integrity review; visual candidate review is required before approval |
| Batch rank | Stored five-dimension assessments and ranked pipeline |
| Expand profile | Public GitHub repository evidence proposals; supporting document evidence; nothing added automatically |
| Upskill | Skill-gap frequency, priority, official learning links and rough practice ranges |
| Outcomes / archives | Stage notes, source materials, prep artifacts, reviewer output and submission evidence in ZIP archives |
| Gmail sync | Google OAuth or SMTP/IMAP; bounded thread-based correlation and reviewable status signals |
| Offline HTML report | Self-contained stage counts, email totals and filterable application table |
| Notion sync | Optional one-way data-source export, URL-based upsert, no deletion |
| Interview prep | Stage-specific question banks, factual STAR scaffolds, company excerpts, questions to ask, heuristic mock-answer structure feedback |
| Application forms | Character-limited factual introductions/project drafts and saved exact question answers |
| Add portal | Known board registration and generic JSON-LD import; new arbitrary provider adapters require code and tests |
| Add template | User-authored .tex registration with mandatory test compile; default PDF does not require LaTeX |
| Reset | Explicit RESET confirmation; registered files only; no arbitrary recursive deletion |
| Real application submission (extra) | Supported company forms plus LinkedIn Easy Apply step navigation, automatic reviewed queues, confirmation evidence |
| HR single email / entire sheet (extra) | CSV/XLSX aliases and validation, neutral personalization, campaign preview, individual send queues, daily cap and shared cooldown |
| Credential protection (extra) | Gmail desktop OAuth with PKCE, Windows DPAPI, local Chrome profile, credential redaction from callback logs |
| Follow-up reminders (extra) | Due dates and completion tracking; reminders do not silently send messages |
| GitHub project (extra) | Source-only repository with CI; runtime personal data excluded |

Boundaries: no promise of access to every website or a job offer; no CAPTCHA bypass; no unattended answers to unknown or legal/compensation questions; no LinkedIn partner API; no automatic interviewer background investigation; no guessed live salary benchmark; no auto-generated executable scraping tools for arbitrary websites. Missing evidence remains explicit. Authenticated live Gmail and LinkedIn verification requires the user's actual connection and resume; synthetic tests do not establish that all current portal layouts work.

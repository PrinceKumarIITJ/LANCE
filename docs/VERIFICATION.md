# Verification record

Verified locally on Windows on 3 November 2026:

- 46 automated tests passed: provider normalization, eligibility persistence, PDF/text review, stale approval invalidation, contact-sheet parsing, campaign personalization, sender/duplicate/cooldown/daily-cap checks, uncertain-send handling, reply correlation, OAuth state/PKCE and DPAPI storage, reports and archives, browser form filling and synthetic multi-step LinkedIn flows.
- Complete dashboard check passed: profile -> job import -> generated PDFs -> packet approval -> resume upload -> single HR contact -> sheet import -> personalized campaign preview -> approved queue. Nine views and desktop/mobile layouts checked; no page JavaScript errors or mobile horizontal overflow.
- JavaScript syntax checks passed for all three application scripts.
- Earlier expanded-source GitHub Actions run passed on Windows and Linux. Check the repository Actions tab for the latest commit result.

All mail transports in automated sending tests were fake. Browser submission tests used synthetic local content. No real email or job application was sent during these checks.

Live setup still requires the user's resume, profile and account connections. Authenticated Gmail OAuth/send and the current logged-in LinkedIn UI must be validated after connection. Optional cloud AI, Notion and custom LaTeX compilation need their credentials/tools and were not exercised against live accounts. Google Chrome synthetic flows do not guarantee compatibility with every current career portal or LinkedIn layout.

Run `python -m pytest -q` and `python tests/dashboard_e2e.py` to repeat checks. The dashboard script creates its own temporary server/storage with sending disabled. Screenshots are ignored artifacts, not repository files.

# Command reference

Run from the LANCE checkout with the same Python environment used by the app. A leading slash on the command name is accepted (`python lance.py /rank`). The CLI uses the same SQLite data directory and services as the dashboard. Do not run destructive CLI operations while the app is processing work; reset refuses while the server holds its data-folder lock.

| Guide workflow | LANCE command |
|---|---|
| Start app | `python lance.py serve` |
| Check setup | `python lance.py doctor` |
| Setup from CV | `python lance.py setup --resume path/to/cv.pdf` |
| Documents folder | `python lance.py setup --documents path/to/folder` |
| Interactive profile | `python lance.py setup --interactive` |
| Scrape watchlist | `python lance.py scrape` |
| Five-dimension rank | `python lance.py rank` |
| Prepare job packet | `python lance.py apply JOB_ID` |
| Import public career URL + prepare | `python lance.py apply https://company.example/careers/job` |
| Approve reviewed packet | `python lance.py apply JOB_ID --approve` |
| Submit reviewed supported form | `python lance.py apply JOB_ID --approve --submit` |
| GitHub evidence | `python lance.py expand` |
| Skill gaps | `python lance.py upskill --job-id JOB_ID` (omit ID for aggregate) |
| Stage-specific prep | `python lance.py interview JOB_ID --stage technical` |
| Record outcome | `python lance.py outcome JOB_ID interview --note "Screening confirmed"` |
| Mailbox replies | `python lance.py gmail-sync` |
| Offline dashboard | `python lance.py html-report --output report.html` |
| Notion export | `python lance.py notion-sync` |
| Add known career board | `python lance.py add-portal https://jobs.lever.co/company-slug --company Company` |
| Add/test LaTeX template | `python lance.py add-template path/to/resume.tex` |
| Import HR sheet | `python lance.py contacts path/to/hr.xlsx` |
| Create campaign drafts | `python lance.py campaign --name "AI outreach" --role "AI Engineer"` |
| Select one contact | Append `--contact-id 1` (repeat for more); omit to select all imported contacts |
| Reset profile | `python lance.py reset profile --confirm RESET` |
| Reset imported documents | `python lance.py reset documents --confirm RESET` |
| Reset tracker and registered artifacts | `python lance.py reset all --confirm RESET` |

`apply --approve` is an explicit assertion that you reviewed the generated PDF and job eligibility. `apply --submit` can perform an external action. Prefer the dashboard for interactive login, unknown answers, multi-step LinkedIn forms and visual review. CLI campaigns create drafts only; preview and approve them in the dashboard.

Reset clears the named app records and registered artifact files. It validates every file against the runtime data root and never recursively removes directories. It retains Chrome sessions, Google credentials and custom template files; use disconnect and remove their dedicated local files separately. Keep backups if you need historical application materials.

Custom `.tex` fields: `{{name}}`, `{{email}}`, `{{phone}}`, `{{location}}`, `{{college}}`, `{{degree}}`, `{{graduation_year}}`, `{{skills}}`, `{{facts}}`, `{{links}}`. Fields are LaTeX-escaped. Compile commands are fixed, shell escape is disabled and compilation is time-bounded. Use only templates you trust.

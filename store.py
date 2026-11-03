"""Private, local SQLite store. All writes use short, atomic transactions."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LANCE_DATA', os.environ.get('JOB_PILOT_DATA', str(ROOT / 'data')))).resolve()
DATA.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    con = sqlite3.connect(DATA / 'pilot.db', timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init(recover=True):
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(
          id INTEGER PRIMARY KEY, provider TEXT NOT NULL, board TEXT NOT NULL,
          company TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
          checked_at TEXT, error TEXT, UNIQUE(provider,board));
        CREATE TABLE IF NOT EXISTS jobs(
          id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
          company TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,
          url TEXT NOT NULL, description TEXT NOT NULL, provider TEXT NOT NULL,
          published TEXT, fetched_at TEXT NOT NULL, score INTEGER DEFAULT 0,
          eligibility TEXT NOT NULL DEFAULT 'review', reasons TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'new', packet TEXT, evidence TEXT,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contacts(
          id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          company TEXT NOT NULL, source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox(
          id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
          contact_id INTEGER NOT NULL REFERENCES contacts(id), subject TEXT NOT NULL,
          body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
          message_id TEXT, sent_at TEXT, error TEXT, UNIQUE(job_id,contact_id));
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL,
          job_id INTEGER, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inbox(
          message_id TEXT PRIMARY KEY, sender TEXT NOT NULL, subject TEXT NOT NULL,
          date TEXT, signal TEXT NOT NULL, job_id INTEGER, preview TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaigns(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
          subject_template TEXT NOT NULL, body_template TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft', attachment TEXT NOT NULL,
          profile_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaign_messages(
          id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
          contact_id INTEGER NOT NULL REFERENCES contacts(id), subject TEXT NOT NULL,
          body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
          message_id TEXT, sent_at TEXT, error TEXT, UNIQUE(campaign_id,contact_id));
        CREATE TABLE IF NOT EXISTS documents(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
          text TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assessments(job_id INTEGER PRIMARY KEY REFERENCES jobs(id),payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS research(company TEXT NOT NULL,url TEXT NOT NULL,
          payload TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(company,url));
        CREATE TABLE IF NOT EXISTS artifacts(id INTEGER PRIMARY KEY,job_id INTEGER,
          kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY,job_id INTEGER REFERENCES jobs(id),
          contact_id INTEGER REFERENCES contacts(id),due_date TEXT NOT NULL,note TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS notion_links(job_id INTEGER PRIMARY KEY,page_id TEXT NOT NULL);
        ''')
        if 'campaign_message_id' not in {row[1] for row in con.execute('PRAGMA table_info(inbox)')}:
            con.execute('ALTER TABLE inbox ADD COLUMN campaign_message_id INTEGER')
        if 'employment' not in {row[1] for row in con.execute('PRAGMA table_info(jobs)')}:
            con.execute("ALTER TABLE jobs ADD COLUMN employment TEXT NOT NULL DEFAULT ''")
        defaults = {
            'profile': {'name': '', 'email': '', 'phone': '', 'college': '',
                'degree': 'B.Tech Computer Science', 'graduation_year': 2027,
                'graduation_month': '', 'available_from': '', 'location': '',
                'locations': ['India', 'Remote'], 'roles': ['AI Engineer', 'Software Engineer'],
                'skills': [], 'facts': [], 'github': '', 'linkedin': '',
                'portfolio': '', 'answers': {}, 'resume': None,
                'experience_months': 0, 'work_preferences': []},
            'policy': {'discovery_enabled': False, 'interval_minutes': 360,
                'auto_prepare': False, 'auto_apply_ready': False, 'auto_send_queued': False,
                'min_score': 45, 'email_daily_limit': 10,
                'contact_cooldown_days': 14, 'auto_sync_inbox': False},
        }
        for key, value in defaults.items():
            con.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, json.dumps(value)))
            existing = json.loads(con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0])
            for field, default in value.items():
                existing.setdefault(field, default)
            con.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(existing), key))
        # Restarting must never retry a possibly completed external action.
        if recover:
            con.execute("UPDATE outbox SET status='uncertain',error='App restarted during send; check Sent before retrying' WHERE status='sending'")
            con.execute("UPDATE campaign_messages SET status='uncertain',error='Interrupted send; check Sent before retrying' WHERE status='sending'")
            con.execute("UPDATE jobs SET status='uncertain' WHERE status='submitting'")
            con.execute("UPDATE jobs SET status='needs_input' WHERE status='auto_running'")


def profile_hash(profile=None):
    import hashlib
    profile = dict(profile or get_setting('profile'))
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


def get_setting(key):
    with db() as con:
        row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else None


def set_setting(key, value):
    with db() as con:
        con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))


def rows(sql, args=()):
    with db() as con:
        return [dict(row) for row in con.execute(sql, args).fetchall()]


def job(job_id):
    result = rows('SELECT * FROM jobs WHERE id=?', (job_id,))
    if not result:
        raise ValueError('Job not found')
    return result[0]


def event(kind, detail, job_id=None):
    with db() as con:
        con.execute('INSERT INTO events(time,kind,job_id,detail) VALUES (?,?,?,?)',
                    (now(), kind, job_id, detail[:4000]))

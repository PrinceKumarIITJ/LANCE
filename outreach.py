"""Explicit outbox delivery with duplicate suppression and ambiguous-send handling."""
import csv
import hashlib
import imaplib
import io
import os
import re
import smtplib
import ssl
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from store import db, rows, job, get_setting, now, event
from packets import packet_path


def valid_email(value):
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', value) or len(value) > 254:
        raise ValueError('Invalid email address')
    return value.lower()


def import_contacts(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not {'email', 'company', 'source'}.issubset(reader.fieldnames or []):
        raise ValueError('CSV needs email,company,source columns; name is optional')
    records = list(reader)
    if len(records) > 1000:
        raise ValueError('Import at most 1000 contacts at a time')
    cleaned = []
    for row in records:
        email = valid_email(row['email'].strip())
        company, source = row['company'].strip(), row['source'].strip()
        if not company or not source:
            raise ValueError('Every contact needs a company and the source where you found the address')
        cleaned.append((email, row.get('name', '').strip(), company, source))
    with db() as con:
        for record in cleaned:
            con.execute('INSERT INTO contacts(email,name,company,source) VALUES (?,?,?,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name,company=excluded.company,source=excluded.source', record)
    return len(cleaned)


def draft(job_id, contact_id):
    item = job(job_id)
    contacts = rows('SELECT * FROM contacts WHERE id=?', (contact_id,))
    if not contacts:
        raise ValueError('Contact not found')
    contact = contacts[0]
    if item['company'].strip().casefold() != contact['company'].strip().casefold():
        raise ValueError('Contact company must match the job company')
    body = packet_path(job_id, 'cover-letter.txt').read_text(encoding='utf-8')
    body = body.replace(f"Dear {item['company']} hiring team,", f"Hi {contact['name'] or (item['company'] + ' hiring team')},", 1)
    subject = f"Application: {item['title']} — {get_setting('profile')['name']}"
    with db() as con:
        con.execute('INSERT OR IGNORE INTO outbox(job_id,contact_id,subject,body) VALUES (?,?,?,?)',
                    (job_id, contact_id, subject, body))
    return rows('SELECT * FROM outbox WHERE job_id=? AND contact_id=?', (job_id, contact_id))[0]


def send(outbox_id):
    import mail_account
    from campaigns import daily_count
    username, password = os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASSWORD')
    account = mail_account.status()
    oauth = account.get('connected', False)
    if oauth:
        username = account['email']
    if not username or (not oauth and not password):
        raise ValueError('Email is not connected. Configure SMTP_USER and SMTP_PASSWORD locally; never paste passwords in chat.')
    profile = get_setting('profile')
    if username.lower() != profile['email'].lower():
        raise ValueError('SMTP account must match the verified profile email')
    limit = get_setting('policy')['email_daily_limit']
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('''SELECT o.*,c.email FROM outbox o JOIN contacts c ON c.id=o.contact_id WHERE o.id=?''', (outbox_id,)).fetchone()
        if not row:
            raise ValueError('Draft not found')
        if row['status'] not in ('draft', 'queued'):
            raise ValueError('This email is already sent, in progress, or uncertain; it will not be resent')
        item = con.execute('SELECT * FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
        if item['status'] != 'ready':
            raise ValueError('Review the packet and verify eligibility before sending')
        import json
        from store import profile_hash
        manifest=json.loads(packet_path(row['job_id'],'manifest.json').read_text(encoding='utf-8'))
        if profile_hash(manifest['profile_snapshot'])!=profile_hash(profile):
            raise ValueError('Profile changed; regenerate and review the packet before sending')
        count = daily_count(con)
        if count >= limit:
            raise ValueError('Daily email limit reached')
        from datetime import datetime,timedelta,timezone
        cooldown=get_setting('policy').get('contact_cooldown_days',14)
        cutoff=(datetime.now(timezone.utc)-timedelta(days=cooldown)).isoformat()
        recent=sum(con.execute(f"SELECT count(*) FROM {table} WHERE contact_id=? AND status IN ('sending','sent','uncertain') AND sent_at>=?",(row['contact_id'],cutoff)).fetchone()[0]
                   for table in ('outbox','campaign_messages'))
        if recent:
            raise ValueError('Recipient was already contacted within the configured cooldown; review existing conversation first')
        message_id = make_msgid(domain=username.split('@')[-1])
        attachment = packet_path(row['job_id']).read_bytes()
        message = EmailMessage()
        message['From'] = formataddr((profile['name'], valid_email(username)))
        message['To'] = valid_email(row['email'])
        message['Subject'] = row['subject']
        message['Message-ID'] = message_id
        message.set_content(row['body'])
        message.add_attachment(attachment, maintype='application', subtype='pdf', filename='Resume.pdf')
        con.execute("UPDATE outbox SET status='sending',message_id=?,sent_at=? WHERE id=?", (message_id, now(), outbox_id))
    data_started = False
    try:
        if oauth:
            mail_account.access_token()
            data_started = True
            mail_account.send_mime(message)
        else:
            with smtplib.SMTP_SSL(os.environ.get('SMTP_HOST', 'smtp.gmail.com'), int(os.environ.get('SMTP_PORT', '465')), context=ssl.create_default_context(), timeout=35) as smtp:
                smtp.login(username, password)
                data_started = True
                refused = smtp.send_message(message)
                if refused:
                    raise smtplib.SMTPRecipientsRefused(refused)
        status, error = 'sent', None
    except Exception as exc:
        status = 'uncertain' if data_started else 'draft'
        # Never persist credentials or server text potentially containing credentials.
        error = type(exc).__name__ + (': check Sent before any retry' if data_started else ': connection/authentication failed')
    with db() as con:
        con.execute('UPDATE outbox SET status=?,error=? WHERE id=?', (status, error, outbox_id))
    event('email_' + status, f'Outbox #{outbox_id}; {error or message_id}', row['job_id'])
    return {'status': status, 'error': error, 'message_id': message_id}


def _imap_messages(username, password):
    with imaplib.IMAP4_SSL(os.environ.get('IMAP_HOST', 'imap.gmail.com'), timeout=30) as inbox:
        inbox.login(username, password)
        inbox.select('INBOX', readonly=True)
        status, data = inbox.search(None, 'ALL')
        if status != 'OK':
            raise ValueError('Mailbox search failed')
        for uid in data[0].split()[-100:]:
            status, parts = inbox.fetch(uid, '(BODY.PEEK[])')
            if status == 'OK':
                raw = next((part[1] for part in parts if isinstance(part, tuple)), b'')
                if raw:
                    yield raw


def record_replies(raw_messages):
    tracked = rows("SELECT message_id,job_id FROM outbox WHERE status IN ('sent','uncertain')")
    campaign_threads = rows("SELECT message_id,id FROM campaign_messages WHERE status IN ('sent','uncertain')")
    count = 0
    for raw in raw_messages:
        msg = message_from_bytes(raw, policy=policy.default)
        sender = parseaddr(str(msg.get('From', '')))[1].lower()
        refs = str(msg.get('In-Reply-To', '')) + ' ' + str(msg.get('References', ''))
        candidates = [entry for entry in tracked if entry['message_id'] and entry['message_id'] in refs]
        campaign_matches = [entry for entry in campaign_threads if entry['message_id'] and entry['message_id'] in refs]
        if not candidates and not campaign_matches:
            continue
        message_id = str(msg.get('Message-ID') or hashlib.sha256(raw).hexdigest())
        subject = str(msg.get('Subject', ''))
        part = msg.get_body(preferencelist=('plain',)) if msg.is_multipart() else msg
        try:
            text = part.get_content() if part else ''
        except Exception:
            text = ''
        if not isinstance(text, str):
            text = ''
        fresh = text.split('\nOn ')[0].split('\n>')[0][:6000]
        combined = (subject + '\n' + fresh).lower()
        signal = 'reply'
        if re.search(r'unfortunately|not moving forward|not selected|regret to inform', combined):
            signal = 'possible rejection'
        elif re.search(r'interview|schedule a call|assessment|coding test', combined):
            signal = 'possible interview'
        elif re.search(r'offer letter|pleased to offer', combined):
            signal = 'possible offer'
        with db() as con:
            cur = con.execute('INSERT OR IGNORE INTO inbox(message_id,sender,subject,date,signal,job_id,preview,campaign_message_id) VALUES (?,?,?,?,?,?,?,?)',
                (message_id, sender, subject, str(msg.get('Date', '')), signal,
                 candidates[0]['job_id'] if candidates else None, fresh[:1500],
                 campaign_matches[0]['id'] if campaign_matches else None))
            count += cur.rowcount
    return count


def sync_inbox():
    import mail_account
    if mail_account.status().get('connected'):
        raw_messages = mail_account.inbox_messages()
    else:
        username, password = os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASSWORD')
        if not username or not password:
            raise ValueError('Connect your mailbox locally first')
        raw_messages = _imap_messages(username, password)
    count = record_replies(raw_messages)
    event('inbox_sync', f'{count} new correlated replies; signals require review')
    return {'new_replies': count}

"""One reviewed campaign -> personalized, individually delivered HR emails."""
import hashlib
import json
import os
import re
import shutil
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from store import DATA, db, rows, get_setting, profile_hash, now, event
from outreach import valid_email
import mail_account

DEFAULT_SUBJECT = '{{role}} opportunities | {{candidate_name}} | {{graduation_year}} graduate'
DEFAULT_BODY = '''Hi {{name}},

I am {{candidate_name}}, pursuing {{degree}} at {{college}}, with expected graduation in {{graduation_year}}. I am exploring full-time {{role}} opportunities with {{company}} and can join from {{available_from}}.

My skills include {{skills}}. Relevant work from my profile:
{{highlights}}

I have attached my resume. If there is a suitable opening, I would appreciate the opportunity to discuss my fit or be directed to the relevant hiring team.

Regards,
{{candidate_name}}
{{email}}
{{github}}
{{linkedin}}'''


def render(template, profile, contact, role):
    values = {key: str(profile.get(key, '')) for key in ('degree','college','graduation_year','available_from','email','github','linkedin')}
    values.update(candidate_name=profile['name'], name=contact.get('name') or 'Hiring Team',
        company=contact.get('company') or 'your team', role=role,
        skills=', '.join(profile.get('skills', [])), highlights='\n'.join('- ' + f for f in profile.get('facts', [])[:3]))
    unknown = set(re.findall(r'{{\s*([a-zA-Z_]+)\s*}}', template)) - set(values)
    if unknown:
        raise ValueError('Unknown template variables: ' + ', '.join(sorted(unknown)))
    return re.sub(r'{{\s*([a-zA-Z_]+)\s*}}', lambda m: values[m[1]], template)


def create(name, role, contact_ids, subject=DEFAULT_SUBJECT, body=DEFAULT_BODY, resume_job_id=None):
    from packets import packet_path, validate_profile
    profile = get_setting('profile')
    validate_profile(profile)
    ids = list(dict.fromkeys(contact_ids))
    if not ids or len(ids) > 2000:
        raise ValueError('Choose between 1 and 2000 imported contacts')
    placeholders = ','.join('?' for _ in ids)
    contacts = rows(f'SELECT * FROM contacts WHERE id IN ({placeholders}) ORDER BY id', ids)
    if len(contacts) != len(ids):
        raise ValueError('Some selected contacts no longer exist')
    attachment = packet_path(resume_job_id) if resume_job_id else DATA / 'original-resume.pdf'
    if not attachment.is_file():
        raise ValueError('Upload your actual resume PDF in Your Profile, or select a prepared job resume')
    material = []
    for contact in contacts:
        rendered_subject = render(subject, profile, contact, role)
        if '\n' in rendered_subject or '\r' in rendered_subject:
            raise ValueError('Subject and personalization fields must not contain newlines')
        material.append((contact['id'], rendered_subject[:300], render(body, profile, contact, role)))
    with db() as con:
        cursor = con.execute('INSERT INTO campaigns(name,role,subject_template,body_template,attachment,profile_hash,created_at) VALUES (?,?,?,?,?,?,?)',
            (name,role,subject,body,str(attachment),profile_hash(profile),now()))
        campaign_id = cursor.lastrowid
        folder = DATA / 'campaigns' / str(campaign_id)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(attachment, folder / 'resume.pdf')
        (folder / 'profile.json').write_text(json.dumps(profile,indent=2),encoding='utf-8')
        con.execute('UPDATE campaigns SET attachment=? WHERE id=?',(str(folder/'resume.pdf'),campaign_id))
        for contact_id, rendered_subject, rendered_body in material:
            con.execute('INSERT INTO campaign_messages(campaign_id,contact_id,subject,body) VALUES (?,?,?,?)',
                (campaign_id,contact_id,rendered_subject,rendered_body))
    event('campaign_created', f'Campaign #{campaign_id}: {len(material)} individual draft emails')
    return campaign_id


def approve(campaign_id):
    with db() as con:
        campaign = con.execute('SELECT * FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
        if not campaign or campaign['profile_hash'] != profile_hash():
            raise ValueError('Profile changed or campaign not found; create a fresh campaign')
        con.execute("UPDATE campaign_messages SET status='queued',error=NULL WHERE campaign_id=? AND status='draft'",(campaign_id,))
        con.execute("UPDATE campaigns SET status='queued' WHERE id=?",(campaign_id,))
    event('campaign_approved',f'Campaign #{campaign_id} reviewed and queued for sending')


def pause(campaign_id):
    with db() as con:
        con.execute("UPDATE campaign_messages SET status='draft' WHERE campaign_id=? AND status='queued'",(campaign_id,))
        con.execute("UPDATE campaigns SET status='paused' WHERE id=?",(campaign_id,))


def daily_count(con):
    return sum(con.execute(f"SELECT count(*) FROM {table} WHERE status IN ('sending','sent','uncertain') AND substr(sent_at,1,10)=?",(now()[:10],)).fetchone()[0]
               for table in ('outbox','campaign_messages'))


def send(message_id):
    profile = get_setting('profile')
    account = mail_account.status()
    oauth = account.get('connected',False)
    sender = account.get('email') if oauth else os.environ.get('SMTP_USER')
    if not sender or (not oauth and not os.environ.get('SMTP_PASSWORD')):
        raise ValueError('Connect Gmail in Settings, or launch with SMTP credentials')
    if sender.lower() != profile['email'].lower():
        raise ValueError('Connected mailbox must match your profile email')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        message = con.execute('''SELECT m.*,c.email,c.name AS recipient_name,p.attachment,p.profile_hash,p.status AS campaign_status
            FROM campaign_messages m JOIN contacts c ON c.id=m.contact_id JOIN campaigns p ON p.id=m.campaign_id WHERE m.id=?''',(message_id,)).fetchone()
        if not message or message['status'] != 'queued' or message['campaign_status'] != 'queued':
            raise ValueError('Only reviewed, queued campaign messages can be sent')
        if message['profile_hash'] != profile_hash(profile):
            raise ValueError('Profile changed; create and review a new campaign')
        config=get_setting('policy')
        if daily_count(con) >= config['email_daily_limit']:
            return {'status':'deferred','reason':'Daily mail limit reached'}
        cutoff=(datetime.now(timezone.utc)-timedelta(days=config.get('contact_cooldown_days',14))).isoformat()
        recent = sum(con.execute(f"SELECT count(*) FROM {table} WHERE contact_id=? AND status IN ('sending','sent','uncertain') AND sent_at>=?",(message['contact_id'],cutoff)).fetchone()[0]
                     for table in ('outbox','campaign_messages'))
        if recent:
            con.execute("UPDATE campaign_messages SET status='skipped',error='Recipient already contacted within cooldown' WHERE id=?",(message_id,))
            return {'status':'skipped','reason':'Recent contact suppressed'}
        target=Path(message['attachment']).resolve()
        if not target.is_relative_to(DATA.resolve()) or not target.is_file():
            raise ValueError('Campaign attachment missing')
        mime=EmailMessage()
        mime['From']=formataddr((profile['name'],valid_email(sender)))
        mime['To']=valid_email(message['email'])
        mime['Subject']=message['subject']
        mid=make_msgid(domain=sender.split('@')[-1])
        mime['Message-ID']=mid
        mime.set_content(message['body'])
        mime.add_attachment(target.read_bytes(),maintype='application',subtype='pdf',filename='Resume.pdf')
        con.execute("UPDATE campaign_messages SET status='sending',message_id=?,sent_at=? WHERE id=?",(mid,now(),message_id))
    started=False
    try:
        if oauth:
            # Refresh before the send boundary; if refresh fails, no send was attempted.
            mail_account.access_token()
            started=True
            mail_account.send_mime(mime)
        else:
            with smtplib.SMTP_SSL(os.environ.get('SMTP_HOST','smtp.gmail.com'),int(os.environ.get('SMTP_PORT','465')),context=ssl.create_default_context(),timeout=35) as smtp:
                smtp.login(sender,os.environ['SMTP_PASSWORD'])
                started=True
                if smtp.send_message(mime):
                    raise smtplib.SMTPRecipientsRefused({})
        status,error='sent',None
    except Exception as exc:
        status='uncertain' if started else 'draft'
        error=type(exc).__name__ + (': check Sent before retrying' if started else ': reconnect mailbox, then review and requeue')
    with db() as con:
        con.execute('UPDATE campaign_messages SET status=?,error=? WHERE id=?',(status,error,message_id))
        left=con.execute("SELECT count(*) FROM campaign_messages WHERE campaign_id=? AND status IN ('draft','queued','sending')",(message['campaign_id'],)).fetchone()[0]
        if not left:
            con.execute("UPDATE campaigns SET status='complete' WHERE id=?",(message['campaign_id'],))
    event('campaign_'+status,f'Message #{message_id}; {error or mid}')
    return {'status':status,'error':error}

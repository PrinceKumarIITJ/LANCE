import asyncio
import csv
import io
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from pypdf import PdfReader

from store import ROOT, DATA, init, db, rows, job, get_setting, set_setting, now, event
from discovery import ingest, score_job, sync_sources, public_url
from packets import prepare, packet_path
from browser_agent import agent
import outreach
import campaigns
import mail_account
import linkedin_flow
from features_api import router as features_router
from runtime_lock import InstanceLock

TOKEN = secrets.token_urlsafe(32)
sync_lock = asyncio.Lock()
last_cycle = 0.0
last_mail_sync=0.0
worker_status = {'running': False, 'last_run': None, 'last_result': None, 'error': None}


async def cycle():
    global last_cycle
    if sync_lock.locked():
        raise ValueError('Discovery is already running')
    async with sync_lock:
        worker_status.update(running=True, error=None)
        try:
            result = await sync_sources()
            policy = get_setting('policy')
            if policy['auto_prepare']:
                for item in rows("SELECT id FROM jobs WHERE status='new' AND eligibility='potential' AND score>=? LIMIT 20", (policy['min_score'],)):
                    try:
                        await prepare(item['id'])
                    except ValueError as exc:
                        event('prepare_skipped', str(exc), item['id'])
            worker_status.update(last_result=result, last_run=now())
            return result
        finally:
            worker_status['running'] = False
            last_cycle = time.monotonic()


async def scheduler():
    global last_mail_sync
    while True:
        await asyncio.sleep(15)
        config = get_setting('policy')
        if config['discovery_enabled'] and time.monotonic() - last_cycle >= config['interval_minutes'] * 60:
            try:
                await cycle()
            except Exception as exc:
                worker_status['error'] = type(exc).__name__ + ': ' + str(exc)[:250]
                event('scheduler_error', worker_status['error'])
        try:
            await process_approved_queue(config,cancel_if_disabled=True)
        except Exception as exc:
            worker_status['error']=type(exc).__name__+': queue paused for this cycle; review activity'
            event('queue_cycle_error',worker_status['error'])
        if config.get('auto_sync_inbox') and time.monotonic()-last_mail_sync>=600:
            last_mail_sync=time.monotonic()
            try:
                await asyncio.to_thread(outreach.sync_inbox)
            except Exception as exc:
                event('mail_sync_stopped',type(exc).__name__+': reconnect mailbox or run manual sync')


async def process_approved_queue(config,cancel_if_disabled=False):
    """Only previously reviewed packets/drafts are eligible for unattended delivery."""
    if config.get('auto_send_queued'):
        for message in rows("SELECT id FROM campaign_messages WHERE status='queued' ORDER BY id LIMIT 5"):
            if cancel_if_disabled and not get_setting('policy').get('auto_send_queued'):
                break
            try:
                result=await asyncio.to_thread(campaigns.send,message['id'])
                if result['status']=='deferred':
                    break
            except Exception as exc:
                with db() as con:
                    con.execute("UPDATE campaign_messages SET status='draft',error=? WHERE id=? AND status='queued'",
                        (type(exc).__name__+': reconnect/review and requeue',message['id']))
        for draft in rows("SELECT id FROM outbox WHERE status='queued' ORDER BY id LIMIT 5"):
            if cancel_if_disabled and not get_setting('policy').get('auto_send_queued'):
                break
            try:
                await asyncio.to_thread(outreach.send, draft['id'])
            except Exception as exc:
                with db() as con:
                    con.execute("UPDATE outbox SET status='draft',error=? WHERE id=? AND status='queued'",
                                (type(exc).__name__ + ': automatic send stopped; review configuration and packet', draft['id']))
                event('auto_email_stopped', f'Outbox #{draft["id"]}: {type(exc).__name__}')
    if config.get('auto_apply_ready') and not agent.lock.locked():
        if cancel_if_disabled and not get_setting('policy').get('auto_apply_ready'):
            return
        if agent.job_id and job(agent.job_id)['status'] in ('needs_input','assisted','uncertain','submitting'):
            return  # Preserve the pending Chrome form until the candidate resolves it.
        # Email and browser are alternative channels for a job, never both automatically.
        candidates = rows("""SELECT j.id FROM jobs j WHERE j.status='ready' AND NOT EXISTS
            (SELECT 1 FROM outbox o WHERE o.job_id=j.id AND o.status IN ('queued','sending','sent','uncertain'))
            ORDER BY j.score DESC LIMIT 1""")
        for item in candidates:
            jid = item['id']
            with db() as con:
                changed = con.execute("UPDATE jobs SET status='auto_running' WHERE id=? AND status='ready'", (jid,)).rowcount
            if not changed:
                continue
            try:
                if linkedin_flow.is_linkedin(job(jid)['url']):
                    await linkedin_flow.apply(jid,submit=True,automatic=cancel_if_disabled)
                    continue
                await agent.open(jid)
                result = await agent.fill(jid)
                if result['needs_you'] or not result['filled']:
                    raise ValueError('Unknown questions, consent, login or navigation requires your review')
                if cancel_if_disabled and not get_setting('policy').get('auto_apply_ready'):
                    raise ValueError('Automatic submission was disabled; review the current form before continuing')
                await agent.submit(jid)
            except Exception as exc:
                with db() as con:
                    con.execute("UPDATE jobs SET status='needs_input',updated_at=? WHERE id=? AND status IN ('auto_running','assisted')", (now(), jid))
                event('auto_apply_stopped', f'{type(exc).__name__}: {str(exc)[:300]}', jid)


@asynccontextmanager
async def lifespan(app):
    with InstanceLock(DATA/'app.lock'):
        init()
        task = asyncio.create_task(scheduler())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await agent.close()


app = FastAPI(title='LANCE', lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(features_router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


@app.middleware('http')
async def local_security(request: Request, call_next):
    # Loopback app, no CORS, per-process CSRF token on all mutations.
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        return Response('Cross-origin access blocked', status_code=403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        supplied = request.headers.get('x-pilot-token', '')
        if not secrets.compare_digest(supplied, TOKEN):
            return Response('Reload LANCE and try again', status_code=403)
    response = await call_next(request)
    if request.url.path=='/oauth/google/callback':
        request.scope['query_string']=b''  # OAuth authorization codes must not appear in access logs.
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail': str(exc)}, status_code=400)


@app.get('/', response_class=HTMLResponse)
async def home():
    return (ROOT / 'static' / 'index.html').read_text(encoding='utf-8').replace('__PILOT_TOKEN__', TOKEN)


@app.get('/static/{filename}')
async def asset(filename: str):
    if filename not in ('app.js', 'features.js', 'toolkit.js', 'style.css'):
        raise HTTPException(404)
    return FileResponse(ROOT / 'static' / filename)


@app.get('/api/state')
def state():
    profile = get_setting('profile')
    return {'profile': profile, 'policy': get_setting('policy'),
            'jobs': rows("SELECT * FROM jobs ORDER BY (eligibility='blocked') ASC,score DESC,fetched_at DESC"),
            'sources': rows('SELECT * FROM sources ORDER BY company'),
            'contacts': rows('SELECT * FROM contacts ORDER BY company,name'),
            'outbox': rows('SELECT o.*,c.email,c.company FROM outbox o JOIN contacts c ON c.id=o.contact_id ORDER BY o.id DESC'),
            'inbox': rows('SELECT * FROM inbox ORDER BY date DESC LIMIT 100'),
            'events': rows('SELECT * FROM events ORDER BY id DESC LIMIT 80'),
            'worker': worker_status,
            'connections': {'email': mail_account.status().get('connected',False) or bool(os.environ.get('SMTP_USER') and os.environ.get('SMTP_PASSWORD')),
                            'local_ai': os.environ.get('OLLAMA_MODEL') or None,
                            'browser': agent.context is not None}}


class Profile(BaseModel):
    name: str = Field(default='', max_length=150)
    email: str = Field(default='', max_length=254)
    phone: str = Field(default='', max_length=50)
    college: str = Field(default='', max_length=200)
    degree: str = Field(default='B.Tech Computer Science', max_length=200)
    graduation_year: int = Field(default=2027, ge=2020, le=2045)
    graduation_month: str = ''
    available_from: str = ''
    location: str = Field(default='', max_length=200)
    locations: list[str] = Field(default_factory=list, max_length=30)
    roles: list[str] = Field(default_factory=lambda: ['AI Engineer', 'Software Engineer'], max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=100)
    facts: list[str] = Field(default_factory=list, max_length=50)
    github: str = ''
    linkedin: str = ''
    portfolio: str = ''
    answers: dict[str, str] = Field(default_factory=dict, max_length=100)
    experience_months:int=Field(default=0,ge=0,le=600)
    work_preferences:list[str]=Field(default_factory=list,max_length=30)


@app.put('/api/profile')
def save_profile(profile: Profile):
    data = profile.model_dump()
    if data['email']:
        outreach.valid_email(data['email'])
    if data['available_from']:
        from datetime import date
        date.fromisoformat(data['available_from'])
    for key in ('github', 'linkedin', 'portfolio'):
        if data[key]:
            public_url(data[key])
    for key in ('skills', 'roles', 'locations', 'facts'):
        data[key] = list(dict.fromkeys(s.strip() for s in data[key] if s.strip()))
        if any(len(s) > 4000 for s in data[key]):
            raise ValueError('Each profile entry must be under 4000 characters')
    data['resume'] = get_setting('profile').get('resume')
    set_setting('profile', data)
    # Any candidate change invalidates unsubmitted approvals/materials.
    with db() as con:
        con.execute("UPDATE jobs SET status='new',packet=NULL WHERE status IN ('prepared','ready','assisted','needs_input','auto_running')")
        con.execute("DELETE FROM outbox WHERE status IN ('draft','queued')")
        con.execute("UPDATE campaign_messages SET status='draft',error='Profile changed; create a fresh campaign' WHERE status='queued'")
        con.execute("UPDATE campaigns SET status='stale' WHERE status IN ('draft','queued','paused')")
    for item in rows('SELECT * FROM jobs'):
        score, eligibility, reasons = score_job(item, data)
        with db() as con:
            con.execute('UPDATE jobs SET score=?,eligibility=?,reasons=? WHERE id=?',
                        (score, eligibility, json.dumps(reasons), item['id']))
    from evaluation import rank_all
    rank_all()
    event('profile_updated', 'Profile saved; unsubmitted packets require regeneration')
    return {'saved': True}


@app.post('/api/resume')
async def resume(request: Request):
    length = int(request.headers.get('content-length', '0'))
    if length > 8 * 1024 * 1024:
        raise ValueError('PDF must be under 8 MB')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('PDF must be under 8 MB')
    if not data.startswith(b'%PDF-'):
        raise ValueError('Upload a PDF resume')
    try:
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > 15:
            raise ValueError('Resume PDF must be 15 pages or fewer')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception:
        raise ValueError('Could not read this PDF. Export an unencrypted, text-based PDF.')
    (DATA / 'original-resume.pdf').write_bytes(data)
    profile = get_setting('profile')
    profile['resume'] = {'uploaded_at': now(), 'text': text[:40000]}
    set_setting('profile', profile)
    with db() as con:
        con.execute("UPDATE jobs SET status='new',packet=NULL WHERE status IN ('prepared','ready','assisted','needs_input','auto_running')")
        con.execute("DELETE FROM outbox WHERE status IN ('draft','queued')")
        con.execute("UPDATE campaign_messages SET status='draft',error='Resume changed; create a fresh campaign' WHERE status='queued'")
        con.execute("UPDATE campaigns SET status='stale' WHERE status IN ('draft','queued','paused')")
    return {'text': text[:40000], 'message': 'Review extracted text and add accurate facts to your profile; nothing inferred automatically.'}


class Source(BaseModel):
    provider: str
    board: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=200)


@app.post('/api/sources')
def add_source(source: Source):
    if source.provider not in ('greenhouse', 'lever', 'ashby') or not re.fullmatch(r'[a-zA-Z0-9_-]+', source.board):
        raise ValueError('Choose a supported provider and enter the board slug')
    with db() as con:
        con.execute('INSERT INTO sources(provider,board,company) VALUES (?,?,?) ON CONFLICT(provider,board) DO UPDATE SET company=excluded.company,enabled=1',
                    (source.provider, source.board, source.company.strip()))
    return {'saved': True}


@app.delete('/api/sources/{source_id}')
def delete_source(source_id: int):
    with db() as con:
        con.execute('DELETE FROM sources WHERE id=?', (source_id,))
    return {'deleted': True}


@app.post('/api/discover')
async def discover():
    return {'results': await cycle()}


class Posting(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    location: str = Field(default='', max_length=300)
    url: str = Field(max_length=3000)
    description: str = Field(min_length=20, max_length=100000)
    provider: str = 'manual'


@app.post('/api/jobs')
def import_posting(posting: Posting):
    return {'id': ingest(posting.model_dump())}


@app.post('/api/jobs/{job_id}/prepare')
async def prepare_job(job_id: int):
    return await prepare(job_id)


@app.get('/api/jobs/{job_id}/packet')
def packet(job_id: int):
    return json.loads(packet_path(job_id, 'manifest.json').read_text(encoding='utf-8'))


@app.get('/api/jobs/{job_id}/resume.pdf')
def pdf(job_id: int):
    return FileResponse(packet_path(job_id), media_type='application/pdf', filename='Resume.pdf')


class Approval(BaseModel):
    eligibility_checked: bool
    materials_checked: bool


@app.post('/api/jobs/{job_id}/approve')
def approve(job_id: int, approval: Approval):
    item = job(job_id)
    if item['status'] != 'prepared' or not approval.eligibility_checked or not approval.materials_checked:
        raise ValueError('Prepare and review the PDF, facts, batch eligibility, location, and joining date first')
    packet_path(job_id)
    from store import profile_hash
    manifest=json.loads(packet_path(job_id,'manifest.json').read_text(encoding='utf-8'))
    if profile_hash(manifest['profile_snapshot'])!=profile_hash():
        raise ValueError('Profile changed; regenerate this packet before approving')
    review=packet_path(job_id,'review.json')
    result=json.loads(review.read_text(encoding='utf-8'))
    if not result['passed']:
        raise ValueError('Resolve resume review issues first: '+'; '.join(result['issues']))
    with db() as con:
        con.execute("UPDATE jobs SET status='ready',updated_at=? WHERE id=?", (now(), job_id))
    event('approved', 'Candidate confirmed materials and job eligibility', job_id)
    return {'status': 'ready'}


class Outcome(BaseModel):
    status: str
    note: str = Field(min_length=5, max_length=3000)


@app.post('/api/jobs/{job_id}/outcome')
def outcome(job_id: int, value: Outcome):
    job(job_id)
    if value.status not in ('submitted', 'interview', 'offer', 'rejected', 'archived'):
        raise ValueError('Choose a supported outcome')
    with db() as con:
        con.execute('UPDATE jobs SET status=?,evidence=?,updated_at=? WHERE id=?',
                    (value.status, json.dumps({'manual': True, 'note': value.note, 'time': now()}), now(), job_id))
    event('manual_outcome', value.status + ': ' + value.note, job_id)
    return {'saved': True}


@app.post('/api/browser/{job_id}/{action}')
async def browser(job_id: int, action: str):
    if action == 'open':
        return await agent.open(job_id)
    if action == 'fill':
        return await agent.fill(job_id,trust_existing=True)
    if action == 'submit':
        return await agent.submit(job_id)
    raise HTTPException(404)


class TextPayload(BaseModel):
    text: str = Field(max_length=1000000)


@app.post('/api/contacts/import')
def contacts(payload: TextPayload):
    return {'imported': outreach.import_contacts(payload.text)}


class Draft(BaseModel):
    job_id: int
    contact_id: int


@app.post('/api/outbox')
def draft(value: Draft):
    return outreach.draft(value.job_id, value.contact_id)


class EditDraft(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=20, max_length=15000)


@app.put('/api/outbox/{outbox_id}')
def edit_draft(outbox_id: int, value: EditDraft):
    if '\n' in value.subject or '\r' in value.subject:
        raise ValueError('Subject must be one line')
    with db() as con:
        cur = con.execute("UPDATE outbox SET subject=?,body=? WHERE id=? AND status='draft'", (value.subject, value.body, outbox_id))
        if cur.rowcount != 1:
            raise ValueError('Only unsent drafts can be edited')
    return {'saved': True}


@app.post('/api/outbox/{outbox_id}/send')
def send_email(outbox_id: int):
    return outreach.send(outbox_id)


@app.post('/api/outbox/{outbox_id}/queue')
def queue_email(outbox_id: int):
    with db() as con:
        row = con.execute('SELECT o.status,j.status AS job_status FROM outbox o JOIN jobs j ON j.id=o.job_id WHERE o.id=?', (outbox_id,)).fetchone()
        if not row or row['status'] != 'draft' or row['job_status'] != 'ready':
            raise ValueError('Only a reviewed draft with an approved job packet can be queued')
        con.execute("UPDATE outbox SET status='queued' WHERE id=?", (outbox_id,))
    return {'status': 'queued'}


@app.post('/api/outbox/{outbox_id}/unqueue')
def unqueue_email(outbox_id: int):
    with db() as con:
        cur = con.execute("UPDATE outbox SET status='draft' WHERE id=? AND status='queued'", (outbox_id,))
        if cur.rowcount != 1:
            raise ValueError('Only queued messages can be removed from the queue')
    return {'status': 'draft'}


@app.post('/api/inbox/sync')
def inbox():
    return outreach.sync_inbox()


class Policy(BaseModel):
    discovery_enabled: bool = False
    interval_minutes: int = Field(default=360, ge=15, le=10080)
    auto_prepare: bool = False
    auto_apply_ready: bool = False
    auto_send_queued: bool = False
    min_score: int = Field(default=45, ge=0, le=100)
    email_daily_limit: int = Field(default=10, ge=1, le=50)
    contact_cooldown_days:int=Field(default=14,ge=1,le=90)
    auto_sync_inbox:bool=False


@app.put('/api/policy')
def update_policy(value: Policy):
    set_setting('policy', value.model_dump())
    return {'saved': True}


@app.get('/api/export.csv')
def export_csv():
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    fields = ['company', 'title', 'location', 'url', 'score', 'eligibility', 'status', 'updated_at']
    writer.writerow(fields)
    for item in rows('SELECT * FROM jobs ORDER BY id'):
        # Neutralize spreadsheet formula injection in externally supplied job text.
        writer.writerow([("'" + str(item[k])) if str(item[k]).lstrip().startswith(('=', '+', '-', '@')) else item[k] for k in fields])
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename=applications.csv'})

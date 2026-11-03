import asyncio
import json
from email.message import EmailMessage
import httpx
import pytest
from fastapi.testclient import TestClient

import store
import packets
import browser_agent
import app as web
import discovery
import outreach
import campaigns
import vault
import documents
import features_api
import resume_templates
import reports


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in (store, packets, browser_agent, web, campaigns, vault, documents, features_api, resume_templates, reports):
        monkeypatch.setattr(module, 'DATA', tmp_path)
    for key in ('ANTHROPIC_API_KEY','ANTHROPIC_MODEL','OLLAMA_MODEL'):
        monkeypatch.delenv(key,raising=False)
    with TestClient(web.app) as client:
        client.headers['x-pilot-token'] = web.TOKEN
        yield client


def profile():
    return {'name': 'Test Candidate', 'email': 'candidate@example.com', 'phone': '+919999999999',
        'college': 'Test Institute', 'degree': 'B.Tech Computer Science', 'graduation_year': 2027,
        'available_from': '2027-06-01', 'locations': ['India', 'Remote'],
        'skills': ['Python', 'PyTorch', 'SQL'], 'roles': ['AI Engineer', 'Software Engineer'],
        'facts': ['Search project: built a Python document retriever using SQL.', 'Classifier project: trained and evaluated a PyTorch classifier.'], 'answers': {}}


def posting(**kwargs):
    return dict(company='TestCo', title='Graduate AI Engineer', location='Bengaluru, India',
        url='https://careers.example.com/jobs/123',
        description='Full-time graduate hiring for class of 2027. Use Python and PyTorch to build software.', **kwargs)


def setup_job(client):
    assert client.put('/api/profile', json=profile()).status_code == 200
    result = client.post('/api/jobs', json=posting())
    assert result.status_code == 200
    return result.json()['id']


def approved_job(client):
    jid = setup_job(client)
    assert client.post(f'/api/jobs/{jid}/prepare').status_code == 200
    assert client.post(f'/api/jobs/{jid}/approve', json={'eligibility_checked': True, 'materials_checked': True}).status_code == 200
    return jid


def test_empty_state_security_and_preferences(client):
    state = client.get('/api/state').json()
    assert state['jobs'] == []
    assert state['profile']['locations'] == ['India', 'Remote']
    assert not state['policy']['discovery_enabled']
    assert client.post('/api/discover', headers={'x-pilot-token': ''}).status_code == 403
    assert client.get('/api/state', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/', headers={'Host': 'evil.example'}).status_code == 400
    assert 'Content-Security-Policy' in client.get('/').headers


def test_packet_workflow_and_profile_invalidation(client):
    jid = setup_job(client)
    response = client.post(f'/api/jobs/{jid}/prepare')
    assert response.status_code == 200
    manifest = response.json()
    assert set(manifest['facts']) == set(profile()['facts'])
    assert '2027-06-01' in manifest['cover_letter']
    pdf = client.get(f'/api/jobs/{jid}/resume.pdf')
    assert pdf.content.startswith(b'%PDF-')
    from pypdf import PdfReader
    import io
    text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert 'Test Candidate' in text and 'PyTorch classifier' in text
    assert client.post(f'/api/jobs/{jid}/approve', json={'eligibility_checked': False, 'materials_checked': True}).status_code == 400
    assert client.post(f'/api/jobs/{jid}/approve', json={'eligibility_checked': True, 'materials_checked': True}).status_code == 200
    assert store.job(jid)['status'] == 'ready'
    p = profile(); p['phone'] = '+911111111111'
    client.put('/api/profile', json=p)
    assert store.job(jid)['status'] == 'new'
    assert store.job(jid)['packet'] is None


def test_resume_import_and_duplicate_urls(client):
    jid = setup_job(client)
    client.post(f'/api/jobs/{jid}/prepare')
    pdf = client.get(f'/api/jobs/{jid}/resume.pdf').content
    result = client.post('/api/resume', content=pdf, headers={'Content-Type':'application/pdf'})
    assert result.status_code == 200 and 'Test Candidate' in result.json()['text']
    assert client.post('/api/resume', content=b'not a PDF').status_code == 400
    p = posting(); p['url'] += '?utm_source=linkedin&ref=outreach'
    assert client.post('/api/jobs', json=p).json()['id'] == jid
    assert len(client.get('/api/state').json()['jobs']) == 1


@pytest.mark.parametrize('url', ['http://careers.example.com/jobs', 'https://127.0.0.1/jobs', 'https://localhost/jobs', 'https://user:pass@example.com/jobs', 'https://10.0.0.1/jobs', 'https://example.com:8443/jobs'])
def test_bad_destinations_rejected(url):
    with pytest.raises(ValueError):
        discovery.public_url(url)


@pytest.mark.parametrize('title,description,eligibility', [
    ('Senior AI Engineer','Python, minimum 5 years professional experience.','blocked'),
    ('AI Engineer Intern','Graduating in 2027. Python internship.','blocked'),
    ('Graduate Software Engineer','Only class of 2026 is eligible. Python.','blocked'),
    ('Graduate Software Engineer','Classes graduating 2026-2028. Python.','potential'),
    ('AI Engineer','Python required, experience building models.','review'),
    ('Backend Engineer','Requires 3 years of professional experience.','blocked'),
])
def test_eligibility_rules(title, description, eligibility):
    item = posting(); item.update(title=title, description=description)
    _, actual, reasons = discovery.score_job(item, profile())
    assert actual == eligibility, reasons


def test_remote_always_needs_country_review():
    item = posting(); item['location'] = 'Remote (US only)'
    assert discovery.score_job(item, profile())[1] == 'review'


@pytest.mark.parametrize('provider,payload', [
    ('greenhouse', {'jobs':[{'title':'AI Engineer','absolute_url':'https://careers.example.com/1','location':{'name':'India'},'content':'<p>Python</p>'}]}),
    ('lever', [{'text':'AI Engineer','applyUrl':'https://careers.example.com/1','categories':{'location':'India'},'descriptionPlain':'Python','lists':[{'text':'Requirements','content':'<li>SQL</li>'}]}]),
    ('ashby', {'jobs':[{'title':'AI Engineer','applyUrl':'https://careers.example.com/1','location':'India','descriptionPlain':'Python','isListed':True}]}),
])
def test_provider_contracts(provider, payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    source = {'provider':provider,'board':'testco','company':'TestCo'}
    items = asyncio.run(discovery.fetch_board(source, transport=transport))
    assert len(items) == 1 and items[0]['company'] == 'TestCo'
    assert items[0]['title'] == 'AI Engineer'


def test_provider_error_is_recorded(client, monkeypatch):
    client.post('/api/sources', json={'provider':'greenhouse','board':'testco','company':'TestCo'})
    async def failed(source):
        raise ValueError('Board not found')
    monkeypatch.setattr(discovery, 'fetch_board', failed)
    result = client.post('/api/discover').json()
    assert result['results'][0]['count'] == 0
    assert 'Board not found' in result['results'][0]['error']
    assert client.get('/api/state').json()['jobs'] == []


def seed_email(client, monkeypatch):
    jid = approved_job(client)
    result = client.post('/api/contacts/import', json={'text':'email,company,source,name\nhr@example.com,TestCo,Company careers page,Hiring Team'})
    assert result.status_code == 200
    contact = client.get('/api/state').json()['contacts'][0]
    draft = client.post('/api/outbox', json={'job_id':jid,'contact_id':contact['id']})
    assert draft.status_code == 200
    monkeypatch.setenv('SMTP_USER','candidate@example.com')
    monkeypatch.setenv('SMTP_PASSWORD','test-secret-never-real')
    return jid, draft.json()['id']


def test_email_send_dedup_and_attachment(client, monkeypatch):
    jid, oid = seed_email(client, monkeypatch)
    sent = []
    class SMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def login(self,*args): pass
        def send_message(self, message): sent.append(message); return {}
    monkeypatch.setattr(outreach.smtplib,'SMTP_SSL',SMTP)
    assert client.post(f'/api/outbox/{oid}/send').json()['status'] == 'sent'
    assert len(sent) == 1
    assert list(sent[0].iter_attachments())[0].get_content_type() == 'application/pdf'
    assert client.post(f'/api/outbox/{oid}/send').status_code == 400
    assert store.job(jid)['status'] == 'ready'  # An email isn't a portal submission.


def test_ambiguous_send_not_retried(client, monkeypatch):
    _, oid = seed_email(client, monkeypatch)
    class SMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def login(self,*args): pass
        def send_message(self, message): raise ConnectionResetError()
    monkeypatch.setattr(outreach.smtplib,'SMTP_SSL',SMTP)
    result = client.post(f'/api/outbox/{oid}/send').json()
    assert result['status'] == 'uncertain'
    assert client.post(f'/api/outbox/{oid}/send').status_code == 400


def test_contact_import_atomic_validation(client):
    bad = 'email,company,source\ngood@example.com,TestCo,Website\nbad-address,TestCo,Website'
    assert client.post('/api/contacts/import',json={'text':bad}).status_code == 400
    assert client.get('/api/state').json()['contacts'] == []


def test_export_and_manual_evidence(client):
    jid = setup_job(client)
    assert client.post(f'/api/jobs/{jid}/outcome',json={'status':'submitted','note':'Portal confirmation ref TEST-123'}).status_code == 200
    assert json.loads(store.job(jid)['evidence'])['manual'] is True
    assert 'submitted' in client.get('/api/export.csv').text
    assert client.post(f'/api/jobs/{jid}/prepare').status_code == 400


def test_updated_job_invalidates_prior_approval(client):
    jid = approved_job(client)
    updated = posting()
    updated['description'] += ' New requirement: minimum 5 years professional experience.'
    assert client.post('/api/jobs',json=updated).json()['id'] == jid
    item = store.job(jid)
    assert item['status'] == 'new' and item['packet'] is None
    assert item['eligibility'] == 'blocked'


def test_auto_application_pauses_on_unknown_questions(client, monkeypatch):
    jid = approved_job(client)
    calls = []
    async def fake_open(job_id): calls.append(('open',job_id))
    async def fake_fill(job_id):
        with store.db() as con:
            con.execute("UPDATE jobs SET status='assisted' WHERE id=?", (job_id,))
        return {'filled':['Full name'], 'needs_you':['Work authorization']}
    async def fake_submit(job_id): raise AssertionError('Unknown questions must never be submitted')
    monkeypatch.setattr(web.agent,'open',fake_open)
    monkeypatch.setattr(web.agent,'fill',fake_fill)
    monkeypatch.setattr(web.agent,'submit',fake_submit)
    asyncio.run(web.process_approved_queue({'auto_apply_ready':True}))
    assert calls == [('open',jid)]
    assert store.job(jid)['status'] == 'needs_input'
    asyncio.run(web.process_approved_queue({'auto_apply_ready':True}))
    assert calls == [('open',jid)]  # No blind retry.


def test_auto_application_supported_form_and_disabled_default(client, monkeypatch):
    jid = approved_job(client)
    calls = []
    async def fake_open(job_id): calls.append('open')
    async def fake_fill(job_id): return {'filled':['Full name','Email'], 'needs_you':[]}
    async def fake_submit(job_id):
        calls.append('submit')
        with store.db() as con:
            con.execute("UPDATE jobs SET status='submitted' WHERE id=?", (job_id,))
    monkeypatch.setattr(web.agent,'open',fake_open)
    monkeypatch.setattr(web.agent,'fill',fake_fill)
    monkeypatch.setattr(web.agent,'submit',fake_submit)
    asyncio.run(web.process_approved_queue({}))
    assert calls == []
    asyncio.run(web.process_approved_queue({'auto_apply_ready':True}))
    assert calls == ['open','submit']
    assert store.job(jid)['status'] == 'submitted'


def test_auto_email_requires_explicit_queue_and_avoids_second_channel(client, monkeypatch):
    jid, oid = seed_email(client, monkeypatch)
    sent = []
    class SMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def login(self,*args): pass
        def send_message(self,message): sent.append(message); return {}
    monkeypatch.setattr(outreach.smtplib,'SMTP_SSL',SMTP)
    asyncio.run(web.process_approved_queue({'auto_send_queued':True}))
    assert sent == []
    assert client.post(f'/api/outbox/{oid}/queue').status_code == 200
    assert client.post(f'/api/outbox/{oid}/unqueue').status_code == 200
    assert client.post(f'/api/outbox/{oid}/queue').status_code == 200
    async def forbidden_browser(_): raise AssertionError('Do not apply through both channels automatically')
    monkeypatch.setattr(web.agent,'open',forbidden_browser)
    asyncio.run(web.process_approved_queue({'auto_send_queued':True,'auto_apply_ready':True}))
    assert len(sent) == 1
    assert store.rows('SELECT status FROM outbox WHERE id=?',(oid,))[0]['status'] == 'sent'

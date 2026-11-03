import asyncio
import io
import json
import socket
from email.message import EmailMessage
from urllib.parse import urlsplit,parse_qs
from openpyxl import Workbook
import pytest

from tests.test_workflow import client,profile,setup_job,approved_job
import store
import campaigns
import contact_sheets
import mail_account
import outreach
import safe_web
import career_tools
import vault


def campaign_setup(client,monkeypatch):
    jid=approved_job(client)
    pdf=client.get(f'/api/jobs/{jid}/resume.pdf').content
    assert client.post('/api/resume',content=pdf).status_code==200
    for item in [{'email':'one@example.com','name':'Recruiter One','company':'Company One'}, {'email':'two@example.com','company':''}]:
        assert client.post('/api/contacts/add',json=item).status_code==200
    ids=[c['id'] for c in client.get('/api/state').json()['contacts']]
    response=client.post('/api/campaigns',json={'name':'Test campaign','role':'AI Engineer','contact_ids':ids})
    assert response.status_code==200,response.text
    monkeypatch.setenv('SMTP_USER','candidate@example.com')
    monkeypatch.setenv('SMTP_PASSWORD','synthetic-not-a-real-password')
    return response.json()['id']


class FakeSMTP:
    sent=[]
    def __init__(self,*args,**kwargs):pass
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def login(self,*args):pass
    def send_message(self,message):self.sent.append(message);return {}


def test_xlsx_header_aliases_duplicates_and_formula_rejection(client):
    book=Workbook();sheet=book.active
    for row in [('Email ID','HR Name','Company Name'),('A@example.com','Person A','Employer'),('a@example.com','Duplicate','Employer'),('not-an-email','Bad','Employer'),('=HYPERLINK("https://evil.example")','Formula','Employer')]:sheet.append(row)
    output=io.BytesIO();book.save(output)
    preview=client.post('/api/contacts/upload?preview=true',content=output.getvalue(),headers={'x-filename':'HR.xlsx'})
    assert preview.status_code==200,preview.text
    assert len(preview.json()['contacts'])==1 and preview.json()['duplicates']==1
    assert len(preview.json()['errors'])==2
    assert client.get('/api/state').json()['contacts']==[]
    imported=client.post('/api/contacts/upload',content=output.getvalue(),headers={'x-filename':'HR.xlsx'})
    assert imported.json()['imported']==1


def test_single_hr_and_personalized_campaign_send(client,monkeypatch):
    cid=campaign_setup(client,monkeypatch)
    messages=client.get('/api/campaigns').json()['messages']
    assert 'Recruiter One' in messages[0]['body'] and 'Company One' in messages[0]['body']
    assert 'your team' in messages[1]['body']
    assert client.post(f'/api/campaign-messages/{messages[0]["id"]}/send').status_code==400
    assert client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':False}).status_code==400
    assert client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':True}).status_code==200
    FakeSMTP.sent=[]
    monkeypatch.setattr(campaigns.smtplib,'SMTP_SSL',FakeSMTP)
    for item in messages:
        assert client.post(f'/api/campaign-messages/{item["id"]}/send').json()['status']=='sent'
    assert len(FakeSMTP.sent)==2
    assert all(len(message.get_all('To'))==1 for message in FakeSMTP.sent)
    assert all(list(message.iter_attachments())[0].get_content_type()=='application/pdf' for message in FakeSMTP.sent)
    assert client.post(f'/api/campaign-messages/{messages[0]["id"]}/send').status_code==400


def test_campaign_profile_staleness_pause_and_cooldown(client,monkeypatch):
    cid=campaign_setup(client,monkeypatch)
    client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':True})
    client.post(f'/api/campaigns/{cid}/pause')
    assert all(m['status']=='draft' for m in client.get('/api/campaigns').json()['messages'])
    client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':True})
    FakeSMTP.sent=[];monkeypatch.setattr(campaigns.smtplib,'SMTP_SSL',FakeSMTP)
    first=client.get('/api/campaigns').json()['messages'][0]
    client.post(f'/api/campaign-messages/{first["id"]}/send')
    second=campaigns.create('Another outreach','AI Engineer',[first['contact_id']])
    campaigns.approve(second)
    duplicate=store.rows('SELECT id FROM campaign_messages WHERE campaign_id=?',(second,))[0]['id']
    assert campaigns.send(duplicate)['status']=='skipped'
    assert len(FakeSMTP.sent)==1
    p=profile();p['name']='Changed Candidate'
    client.put('/api/profile',json=p)
    assert client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':True}).status_code==400


def test_campaign_daily_limit_shared_and_ambiguous_send(client,monkeypatch):
    cid=campaign_setup(client,monkeypatch)
    client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':True})
    policy=store.get_setting('policy');policy['email_daily_limit']=1;store.set_setting('policy',policy)
    class Uncertain(FakeSMTP):
        def send_message(self,message):raise ConnectionResetError()
    monkeypatch.setattr(campaigns.smtplib,'SMTP_SSL',Uncertain)
    items=client.get('/api/campaigns').json()['messages']
    assert campaigns.send(items[0]['id'])['status']=='uncertain'
    assert campaigns.send(items[1]['id'])['status']=='deferred'
    with pytest.raises(ValueError):campaigns.send(items[0]['id'])


def test_google_pkce_state_and_protected_storage(client):
    result=client.post('/api/mail/google/client',content=json.dumps({'installed':{'client_id':'fake.apps.googleusercontent.com','client_secret':'fake-secret'}}))
    assert result.status_code==200
    url=client.post('/api/mail/google/connect').json()['url']
    params=parse_qs(urlsplit(url).query)
    assert params['code_challenge_method']==['S256']
    assert params['redirect_uri']==[mail_account.REDIRECT]
    assert params['state'][0] in mail_account.pending
    assert 'fake-secret' not in url
    assert b'fake-secret' not in vault.path('google-client').read_bytes() if __import__('os').name=='nt' else True
    with pytest.raises(ValueError,match='Invalid/expired'):mail_account.complete('fake-code','invalid-state')
    assert client.post('/api/mail/google/client',content=json.dumps({'web':{'client_id':'fake'}})).status_code==400
    assert 'client_secret' not in client.get('/api/mail/status').text


def test_campaign_reply_thread_correlation(client,monkeypatch):
    cid=campaign_setup(client,monkeypatch)
    client.post(f'/api/campaigns/{cid}/approve',json={'reviewed':True})
    FakeSMTP.sent=[];monkeypatch.setattr(campaigns.smtplib,'SMTP_SSL',FakeSMTP)
    item=client.get('/api/campaigns').json()['messages'][0]
    campaigns.send(item['id'])
    sent=store.rows('SELECT * FROM campaign_messages WHERE id=?',(item['id'],))[0]
    reply=EmailMessage();reply['From']='one@example.com';reply['To']='candidate@example.com';reply['Subject']='Interview invitation';reply['Message-ID']='<synthetic-reply@example.com>';reply['In-Reply-To']=sent['message_id'];reply.set_content('Please schedule a call for an interview.')
    assert outreach.record_replies([reply.as_bytes()])==1
    assert outreach.record_replies([reply.as_bytes()])==0
    record=store.rows('SELECT * FROM inbox')[0]
    assert record['campaign_message_id']==item['id'] and record['signal']=='possible interview'


def test_five_dimension_plan_interview_archive_and_report(client):
    jid=approved_job(client)
    assessment=client.get(f'/api/jobs/{jid}/assessment').json()
    assert set(assessment['dimensions'])=={'technical','experience','work_preferences','career_alignment','location'}
    pack=client.post(f'/api/jobs/{jid}/interview',json={'stage':'technical'}).json()
    assert 'TestCo'==pack['company'] and pack['project_stories'][0]['fact'] in profile()['facts']
    assert client.post(f'/api/jobs/{jid}/answers',json={'character_limit':100}).status_code==200
    report=client.get('/api/report.html');assert 'self-contained' in report.text
    assert client.get(f'/api/jobs/{jid}/archive.zip').content.startswith(b'PK')
    assert client.post('/api/followups',json={'job_id':jid,'due_date':'2027-05-10','note':'Review status'}).status_code==200
    assert len(client.get('/api/followups').json()['followups'])==1


def test_document_suggestions_remain_evidence_only(client):
    text=b'Contact: learner@example.com\nBuilt a Python retrieval project with evaluated test queries.'
    assert client.post('/api/documents',content=text,headers={'x-filename':'notes.txt'}).status_code==200
    suggestions=client.get('/api/setup/suggestions').json()['suggestions']
    assert any(s['field']=='email' and s['value']=='learner@example.com' for s in suggestions)
    assert store.get_setting('profile')['email']==''
    assert all(s['value'] in text.decode() for s in suggestions)


def test_safe_web_rejects_private_dns_and_mixed_answers(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='non-public'):safe_web.public_addresses('example.com')


def test_generic_job_jsonld_import(client,monkeypatch):
    payload={'@type':'JobPosting','title':'Graduate Software Engineer','hiringOrganization':{'name':'StructuredCo'},'description':'Graduating class of 2027. Python software engineering.','jobLocation':{'address':{'addressLocality':'Bengaluru','addressCountry':'India'}}}
    monkeypatch.setattr(career_tools,'fetch',lambda url:{'url':url,'content':'<script type="application/ld+json">'+json.dumps(payload)+'</script>'})
    response=client.post('/api/jobs/import-url',json={'url':'https://careers.example.com/jobs/1'})
    assert response.status_code==200,response.text
    assert response.json()['imported']
    assert store.job(response.json()['id'])['company']=='StructuredCo'

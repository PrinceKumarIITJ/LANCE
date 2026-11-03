import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.responses import Response
from pydantic import BaseModel, Field
from store import DATA, db, rows, get_setting
import contact_sheets
import campaigns
import mail_account
import linkedin_flow
import documents
import career_tools
import evaluation
import reports
import resume_templates

router = APIRouter()


async def read_upload(request, limit=8*1024*1024):
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>limit:
            raise ValueError('File exceeds the upload limit')
    return bytes(data)


class Contact(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(default='',max_length=150)
    company: str = Field(default='',max_length=200)
    source: str = Field(default='user-provided',max_length=1000)


@router.post('/api/contacts/add')
def add_contact(contact:Contact):
    contact_sheets.save([contact.model_dump()])
    return {'saved':True}


@router.post('/api/contacts/upload')
async def contact_upload(request:Request,preview:bool=False):
    filename=request.headers.get('x-filename','contacts.csv')
    if not filename.lower().endswith(('.csv','.xlsx','.tsv')):
        raise ValueError('Upload CSV, TSV or XLSX; convert legacy .xls files first')
    result=contact_sheets.parse(await read_upload(request),filename)
    if not preview:
        result['imported']=contact_sheets.save(result['contacts'])
    return result


class Campaign(BaseModel):
    name:str=Field(min_length=1,max_length=150)
    role:str=Field(min_length=2,max_length=200)
    contact_ids:list[int]=Field(min_length=1,max_length=2000)
    subject:str=Field(default=campaigns.DEFAULT_SUBJECT,min_length=3,max_length=1000)
    body:str=Field(default=campaigns.DEFAULT_BODY,min_length=30,max_length=20000)
    resume_job_id:int|None=None


@router.get('/api/campaigns')
def campaign_list():
    return {'campaigns':rows('SELECT * FROM campaigns ORDER BY id DESC'),
        'messages':rows('''SELECT m.*,c.email,c.company,c.name FROM campaign_messages m JOIN contacts c ON c.id=m.contact_id ORDER BY m.id'''),
        'templates':{'subject':campaigns.DEFAULT_SUBJECT,'body':campaigns.DEFAULT_BODY}}


@router.post('/api/campaigns')
def create_campaign(value:Campaign):
    return {'id':campaigns.create(value.name,value.role,value.contact_ids,value.subject,value.body,value.resume_job_id)}


class Review(BaseModel):
    reviewed:bool


@router.post('/api/campaigns/{campaign_id}/approve')
def approve_campaign(campaign_id:int,value:Review):
    if not value.reviewed:
        raise ValueError('Review recipients, personalized messages and the attached resume first')
    campaigns.approve(campaign_id)
    return {'queued':True}


@router.post('/api/campaigns/{campaign_id}/pause')
def pause_campaign(campaign_id:int):
    campaigns.pause(campaign_id)
    return {'paused':True}


@router.get('/api/campaigns/{campaign_id}/resume.pdf')
def campaign_resume(campaign_id:int):
    items=rows('SELECT attachment FROM campaigns WHERE id=?',(campaign_id,))
    if not items:
        raise ValueError('Campaign not found')
    path=Path(items[0]['attachment']).resolve()
    if not path.is_relative_to(DATA.resolve()) or not path.is_file():
        raise ValueError('Attachment not found')
    return FileResponse(path,media_type='application/pdf',filename='Resume.pdf')


@router.post('/api/campaign-messages/{message_id}/send')
def send_campaign_message(message_id:int):
    return campaigns.send(message_id)


@router.get('/api/mail/status')
def mailbox_status():
    return mail_account.status()


@router.post('/api/mail/google/client')
async def upload_google_client(request:Request):
    try:
        data=json.loads(await read_upload(request,20000))
    except (ValueError,UnicodeDecodeError):
        raise ValueError('Upload a valid Google OAuth Desktop client JSON')
    return mail_account.configure(data)


@router.post('/api/mail/google/connect')
def connect_google():
    return mail_account.begin()


@router.get('/oauth/google/callback',response_class=HTMLResponse)
def google_callback(code:str='',state:str='',error:str=''):
    if error:
        raise ValueError('Google authorization was declined. Start Connect Gmail again if needed.')
    mail_account.complete(code,state)
    return '<!doctype html><title>LANCE Gmail connected</title><h1>Gmail connected.</h1><p>Return to LANCE. Your profile email must match this account before any message can be sent.</p><a href="/">Open LANCE</a>'


@router.post('/api/mail/disconnect')
def disconnect_google():
    import vault
    vault.remove('google-token')
    return {'disconnected':True}


@router.get('/api/linkedin/status')
async def linkedin_status():
    return await linkedin_flow.status()


@router.post('/api/linkedin/login')
async def linkedin_login():
    return await linkedin_flow.login()


class Search(BaseModel):
    keywords:str=Field(min_length=2,max_length=200)
    location:str=Field(default='India',max_length=150)
    limit:int=Field(default=5,ge=1,le=20)


@router.post('/api/linkedin/search')
async def linkedin_search(value:Search):
    return await linkedin_flow.search(value.keywords,value.location,value.limit)


class LinkedInApply(BaseModel):
    submit:bool=False
    resume:bool=False


@router.post('/api/linkedin/{job_id}/apply')
async def linkedin_apply(job_id:int,value:LinkedInApply):
    return await linkedin_flow.apply(job_id,value.submit,value.resume)


@router.get('/api/setup-guide',response_class=HTMLResponse)
def setup_guide():
    import html
    guide=(Path(__file__).parent/'docs'/'SETUP.md').read_text(encoding='utf-8')
    return '<!doctype html><title>LANCE setup</title><link rel="stylesheet" href="/static/style.css"><article class="card"><pre>'+html.escape(guide)+'</pre></article>'


@router.post('/api/documents')
async def upload_document(request:Request):
    return await asyncio.to_thread(documents.add,await read_upload(request),request.headers.get('x-filename','document.txt'))


@router.get('/api/setup/suggestions')
def setup_suggestions():
    return documents.suggestions()


@router.post('/api/rank')
def rank_jobs():
    return {'ranked':evaluation.rank_all()}


@router.get('/api/jobs/{job_id}/assessment')
def assessment(job_id:int):
    return evaluation.save_assessment(job_id)


@router.post('/api/upskill')
def upskill_all():
    return evaluation.skill_plan()


@router.post('/api/jobs/{job_id}/upskill')
def upskill_job(job_id:int):
    return career_tools.save_artifact(job_id,'upskill',evaluation.skill_plan(job_id))


class Interview(BaseModel):
    stage:str=Field(default='technical',pattern='^(technical|coding|system-design|hr|behavioral|manager)$')


@router.post('/api/jobs/{job_id}/interview')
def interview(job_id:int,value:Interview):
    return career_tools.interview(job_id,value.stage)


class MockAnswer(BaseModel):
    answer:str=Field(min_length=10,max_length=20000)


@router.post('/api/interview/feedback')
def mock_feedback(value:MockAnswer):
    return career_tools.mock_feedback(value.answer)


class AnswerLimit(BaseModel):
    character_limit:int=Field(default=1000,ge=100,le=5000)


@router.post('/api/jobs/{job_id}/answers')
def application_answers(job_id:int,value:AnswerLimit):
    return career_tools.application_answers(job_id,value.character_limit)


class URL(BaseModel):
    url:str=Field(min_length=10,max_length=3000)


@router.post('/api/jobs/{job_id}/research')
def research_company(job_id:int,value:URL):
    return career_tools.research(job_id,value.url)


@router.post('/api/jobs/import-url')
def import_url(value:URL):
    return career_tools.import_url(value.url)


@router.post('/api/profile/expand')
def expand_profile():
    return career_tools.expand_github()


@router.get('/api/report.html')
def offline_report():
    # Download because app pages deliberately disallow inline script/style.
    return Response(reports.html_report(),media_type='text/html',headers={'Content-Disposition':'attachment; filename=LANCE-report.html'})


@router.get('/api/jobs/{job_id}/archive.zip')
def archive_job(job_id:int):
    return Response(reports.archive(job_id),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename=application-{job_id}.zip'})


class Followup(BaseModel):
    job_id:int
    due_date:str
    note:str=Field(min_length=3,max_length=1000)


@router.get('/api/followups')
def followups():
    return {'followups':rows('SELECT f.*,j.company,j.title FROM followups f JOIN jobs j ON j.id=f.job_id ORDER BY due_date')}


@router.post('/api/followups')
def add_followup(value:Followup):
    from datetime import date
    from store import job
    job(value.job_id)
    date.fromisoformat(value.due_date)
    with db() as con:
        con.execute('INSERT INTO followups(job_id,due_date,note) VALUES (?,?,?)',(value.job_id,value.due_date,value.note))
    return {'saved':True}


@router.post('/api/followups/{followup_id}/done')
def complete_followup(followup_id:int):
    with db() as con:
        con.execute("UPDATE followups SET status='done' WHERE id=?",(followup_id,))
    return {'saved':True}


@router.post('/api/templates')
async def add_template(request:Request):
    return await asyncio.to_thread(resume_templates.register,await read_upload(request,100000),request.headers.get('x-filename','resume.tex'))


@router.get('/api/templates/preview.pdf')
def template_preview():
    template=get_setting('resume_template')
    if not template:raise ValueError('No custom template activated')
    path=Path(template['preview']).resolve()
    if not path.is_relative_to(DATA.resolve()):raise ValueError('Invalid template location')
    return FileResponse(path,media_type='application/pdf')


@router.delete('/api/templates/active')
def default_template():
    from store import set_setting
    set_setting('resume_template',None)
    return {'default_restored':True}


@router.post('/api/notion/sync')
def notion_sync():
    from notion_export import sync
    return {'results':sync()}

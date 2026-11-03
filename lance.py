"""Command equivalents of the setup guide. Prefix command names with / if desired."""
import argparse
import asyncio
import json
import sys
from pathlib import Path


def output(value):print(json.dumps(value,indent=2,ensure_ascii=True,default=str))


def portal(url):
    from urllib.parse import urlsplit
    from discovery import public_url
    parts=urlsplit(public_url(url));host=parts.hostname
    providers={'boards.greenhouse.io':'greenhouse','job-boards.greenhouse.io':'greenhouse',
        'jobs.lever.co':'lever','jobs.ashbyhq.com':'ashby'}
    if host not in providers:raise ValueError('Board sync supports Greenhouse, Lever and Ashby. Use apply URL for other JSON-LD career pages.')
    slug=parts.path.strip('/').split('/')[0]
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+',slug):raise ValueError('Could not identify company board slug')
    return providers[host],slug


def main(argv=None):
    parser=argparse.ArgumentParser(description='LANCE local AI/software job application workspace')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('serve');commands.add_parser('doctor')
    p=commands.add_parser('setup');p.add_argument('--resume',type=Path);p.add_argument('--documents',type=Path);p.add_argument('--interactive',action='store_true')
    commands.add_parser('scrape');commands.add_parser('rank');commands.add_parser('expand');commands.add_parser('notion-sync');commands.add_parser('gmail-sync')
    p=commands.add_parser('apply');p.add_argument('target');p.add_argument('--approve',action='store_true');p.add_argument('--submit',action='store_true')
    p=commands.add_parser('interview');p.add_argument('job_id',type=int);p.add_argument('--stage',default='technical')
    p=commands.add_parser('upskill');p.add_argument('--job-id',type=int)
    p=commands.add_parser('outcome');p.add_argument('job_id',type=int);p.add_argument('status',choices=['submitted','interview','offer','rejected','archived']);p.add_argument('--note',required=True)
    p=commands.add_parser('html-report');p.add_argument('--output',type=Path,default=None)
    p=commands.add_parser('add-portal');p.add_argument('url');p.add_argument('--company',required=True)
    p=commands.add_parser('add-template');p.add_argument('file',type=Path)
    p=commands.add_parser('contacts');p.add_argument('file',type=Path)
    p=commands.add_parser('campaign');p.add_argument('--name',required=True);p.add_argument('--role',required=True);p.add_argument('--contact-id',type=int,action='append',default=[])
    p=commands.add_parser('reset');p.add_argument('scope',choices=['profile','documents','all']);p.add_argument('--confirm',required=True)
    args=list(argv if argv is not None else sys.argv[1:])
    if args:args[0]=args[0].lstrip('/')
    options=parser.parse_args(args)
    if options.command=='serve':
        import runpy
        runpy.run_path(str(Path(__file__).parent/'launch.py'),run_name='__main__');return
    from store import init,DATA,db,rows,get_setting,set_setting
    init(recover=False)
    if options.command=='doctor':
        import shutil,mail_account,intelligence
        output({'data_folder':str(DATA),'mail':mail_account.status(),'ai':intelligence.status(),
            'latex_compiler':next((p for name in ('lualatex','xelatex','pdflatex') if (p:=shutil.which(name))),None),
            'profile_ready':all(get_setting('profile').get(k) for k in ('name','email','college','available_from','facts'))});return
    if options.command=='scrape':
        from discovery import sync_sources
        output(asyncio.run(sync_sources()))
    elif options.command=='rank':
        from evaluation import rank_all
        output(rank_all())
    elif options.command=='setup':
        import documents
        if options.documents:
            folder=options.documents.resolve()
            if not folder.is_dir():raise ValueError('Documents folder not found')
            files=[p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.pdf','.docx','.txt','.md')]
            if len(files)>50:raise ValueError('Import at most 50 documents in one command')
            for path in files:documents.add(path.read_bytes(),path.name)
        if options.resume:
            import io
            from pypdf import PdfReader
            from store import now
            data=options.resume.read_bytes()
            if len(data)>8*1024*1024 or not data.startswith(b'%PDF-'):raise ValueError('Resume must be a PDF under 8 MB')
            documents.add(data,options.resume.name)
            text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages)
            (DATA/'original-resume.pdf').write_bytes(data)
            profile=get_setting('profile');profile['resume']={'text':text[:40000],'uploaded_at':now()};set_setting('profile',profile)
        if options.interactive:
            import app
            profile=get_setting('profile')
            for key,label in [('name','Full name'),('email','Email'),('phone','Phone'),('college','Institution'),('available_from','Earliest full-time joining date (YYYY-MM-DD)')]:
                profile[key]=input(label+': ').strip()
            profile['skills']=[v.strip() for v in input('Skills, comma separated: ').split(',') if v.strip()]
            print('Enter verified project/experience facts, one per line. Blank line finishes.')
            profile['facts']=[]
            while (fact:=input('Fact: ').strip()):profile['facts'].append(fact)
            app.save_profile(app.Profile(**profile))
        output(documents.suggestions())
    elif options.command=='apply':
        from packets import prepare
        from career_tools import import_url
        if options.target.isdigit():jid=int(options.target)
        else:
            result=import_url(options.target)
            if not result.get('imported'):output(result);return
            jid=result['id']
        output(asyncio.run(prepare(jid)))
        if options.approve:
            from app import approve,Approval
            approve(jid,Approval(eligibility_checked=True,materials_checked=True))
        if options.submit:
            if not options.approve:raise ValueError('Submission requires --approve after you have reviewed the generated materials and eligibility')
            from browser_agent import agent
            from store import job
            import linkedin_flow
            async def run():
                try:
                    if linkedin_flow.is_linkedin(job(jid)['url']):return await linkedin_flow.apply(jid,submit=True)
                    await agent.open(jid);filled=await agent.fill(jid)
                    if filled['needs_you']:return filled
                    return await agent.submit(jid)
                finally:await agent.close()
            output(asyncio.run(run()))
    elif options.command=='interview':
        from career_tools import interview
        output(interview(options.job_id,options.stage))
    elif options.command=='upskill':
        from evaluation import skill_plan
        output(skill_plan(options.job_id))
    elif options.command=='expand':
        from career_tools import expand_github
        output(expand_github())
    elif options.command=='outcome':
        from app import outcome,Outcome
        output(outcome(options.job_id,Outcome(status=options.status,note=options.note)))
    elif options.command=='gmail-sync':
        from outreach import sync_inbox
        output(sync_inbox())
    elif options.command=='html-report':
        from reports import html_report
        path=options.output or DATA/'LANCE-report.html';path.write_text(html_report(),encoding='utf-8');print(str(path))
    elif options.command=='notion-sync':
        from notion_export import sync
        output(sync())
    elif options.command=='add-portal':
        provider,board=portal(options.url)
        from app import add_source,Source
        output(add_source(Source(provider=provider,board=board,company=options.company)))
    elif options.command=='add-template':
        from resume_templates import register
        output(register(options.file.read_bytes(),options.file.name))
    elif options.command=='contacts':
        import contact_sheets
        result=contact_sheets.parse(options.file.read_bytes(),options.file.name);contact_sheets.save(result['contacts']);output(result)
    elif options.command=='campaign':
        import campaigns
        ids=options.contact_id or [r['id'] for r in rows('SELECT id FROM contacts')]
        output({'campaign_id':campaigns.create(options.name,options.role,ids),'next':'Review and queue in the dashboard; this command only creates drafts'})
    elif options.command=='reset':
        from reset_data import reset
        from runtime_lock import InstanceLock
        with InstanceLock(DATA/'app.lock'):
            output(reset(options.scope,options.confirm))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:
        print('LANCE: '+str(exc),file=sys.stderr);sys.exit(1)

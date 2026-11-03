"""Explicit reset of registered application artifacts; never recursively delete a directory."""
from pathlib import Path
from store import DATA,db,rows,get_setting,set_setting


def reset(scope,confirmation):
    if confirmation!='RESET' or scope not in ('profile','documents','all'):
        raise ValueError('Reset requires --confirm RESET and scope profile, documents, or all')
    files=[]
    if scope in ('documents','all'):
        files.extend(Path(item['path']) for item in rows('SELECT path FROM documents'))
        files.append(DATA/'original-resume.pdf')
    if scope=='all':
        for item in rows('SELECT packet FROM jobs WHERE packet IS NOT NULL'):
            files.extend(Path(item['packet'])/name for name in ('resume.pdf','resume.tex','resume.log','resume.aux','resume.out','cover-letter.pdf','cover-letter.txt','manifest.json','review.json'))
        for item in rows('SELECT attachment FROM campaigns'):
            files.extend([Path(item['attachment']),Path(item['attachment']).parent/'profile.json'])
        files.extend(DATA/'evidence'/f"{item['id']}.png" for item in rows('SELECT id FROM jobs'))
    for path in files:
        resolved=path.resolve()
        if not resolved.is_relative_to(DATA.resolve()) or resolved==DATA.resolve():
            raise ValueError('Artifact location is outside the LANCE data folder; reset stopped')
    for path in files:path.unlink(missing_ok=True)
    if scope in ('profile','all'):
        p=get_setting('profile')
        for key in ('name','email','phone','college','location','github','linkedin','portfolio','available_from'):p[key]=''
        p.update(skills=[],facts=[],answers={},resume=None,work_preferences=[],experience_months=0)
        set_setting('profile',p)
    elif scope=='documents':
        p=get_setting('profile');p['resume']=None;set_setting('profile',p)
    with db() as con:
        if scope in ('documents','all'):con.execute('DELETE FROM documents')
        if scope=='all':
            for table in ('campaign_messages','campaigns','outbox','contacts','followups','inbox','assessments','artifacts','research','notion_links','events','jobs','sources'):
                con.execute('DELETE FROM '+table)
        else:
            con.execute("UPDATE jobs SET status='new',packet=NULL WHERE status IN ('prepared','ready','assisted','needs_input')")
            con.execute("DELETE FROM outbox WHERE status IN ('draft','queued')")
            con.execute("UPDATE campaigns SET status='stale' WHERE status IN ('draft','queued','paused')")
            con.execute("UPDATE campaign_messages SET status='draft',error='Reset invalidated approval' WHERE status='queued'")
    return {'reset':scope,'note':'Registered records/artifacts reset. Browser session, OAuth credentials and custom templates are deliberately retained; disconnect accounts separately and remove their dedicated local folders if needed.'}

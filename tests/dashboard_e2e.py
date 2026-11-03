"""Full dashboard QA in isolated storage. Never connects a real mailbox or submits jobs."""
import asyncio
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]


async def browser_flow(base):
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(channel='chrome',headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1080})
        errors=[]
        page.on('pageerror',lambda err:errors.append(str(err)))
        await page.goto(base,wait_until='networkidle')
        await page.get_by_role('heading',name='Your next opportunities').wait_for()
        await page.locator('nav [data-view="profile"]').click()
        for key,value in {'name':'UI Candidate','email':'candidate@example.com','phone':'+919999999999',
            'college':'Synthetic Test Institute','available_from':'2027-06-01','skills':'Python, SQL',
            'facts':'Search project: built and evaluated a Python retrieval API using SQL.'}.items():
            await page.locator(f'#profile-form [name="{key}"]').fill(value)
        await page.get_by_role('button',name='Save profile',exact=True).click()
        await page.get_by_text('Profile saved. Pending packets need regeneration.',exact=True).wait_for()
        await page.locator('nav [data-view="jobs"]').click()
        await page.get_by_role('button',name='+ Import a job',exact=True).click()
        for key,value in {'company':'UI TestCo','title':'Graduate AI Engineer','location':'Bengaluru, India',
            'url':'https://careers.example.com/ui-test','description':'Full-time graduate hiring for class of 2027. Build Python software with SQL.'}.items():
            await page.locator(f'#import-job-form [name="{key}"]').fill(value)
        await page.get_by_role('button',name='Add to pipeline',exact=True).click()
        await page.locator('#modal-content').get_by_role('heading',name='Graduate AI Engineer',exact=True).wait_for()
        await page.get_by_role('button',name='1. Prepare materials',exact=True).click()
        await page.locator('#approval-form').wait_for()
        await page.locator('#approval-form [name="eligibility"]').check()
        await page.locator('#approval-form [name="materials"]').check()
        await page.get_by_role('button',name='2. Approve application packet',exact=True).click()
        await page.get_by_text('Packet approved. Ready for browser application or HR email.',exact=True).wait_for()
        state=await (await page.request.get(base+'/api/state')).json()
        jid=state['jobs'][0]['id']
        assert state['jobs'][0]['status']=='ready'
        await page.get_by_role('button',name='Close dialog').click()
        await page.locator('nav [data-view="profile"]').click()
        pdf=await (await page.request.get(base+f'/api/jobs/{jid}/resume.pdf')).body()
        await page.locator('#resume-file').set_input_files({'name':'synthetic-resume.pdf','mimeType':'application/pdf','buffer':pdf})
        await page.get_by_text('Review extracted text and add accurate facts to your profile; nothing inferred automatically.',exact=True).wait_for()
        await page.locator('nav [data-view="outreach"]').click()
        await page.get_by_role('button',name='+ Single email',exact=True).click()
        await page.locator('#feature-contact-add [name="email"]').fill('hr-one@example.com')
        await page.locator('#feature-contact-add [name="name"]').fill('Synthetic HR One')
        await page.locator('#feature-contact-add [name="company"]').fill('UI TestCo')
        await page.get_by_role('button',name='Save contact',exact=True).click()
        await page.get_by_text('HR email saved. Create a campaign to send from your account.',exact=True).wait_for()
        async with page.expect_file_chooser() as chooser:
            await page.get_by_role('button',name='Upload CSV / XLSX',exact=True).click()
        await (await chooser.value).set_files({'name':'hr-sheet.csv','mimeType':'text/csv','buffer':b'Email ID,Name,Company\nhr-two@example.com,Synthetic HR Two,UI TestCo\nhr-two@example.com,Duplicate,UI TestCo\ninvalid,Invalid,UI TestCo'})
        await page.get_by_role('heading',name='Sheet imported',exact=True).wait_for()
        await page.get_by_role('button',name='Create campaign with these contacts',exact=True).click()
        await page.locator('#feature-campaign-create [name="name"]').fill('Synthetic UI outreach')
        await page.get_by_role('button',name='Create drafts and preview',exact=True).click()
        await page.get_by_role('heading',name='Synthetic UI outreach',exact=True).wait_for()
        await page.locator('#feature-campaign-approve input[name="reviewed"]').check()
        await page.get_by_role('button',name='Approve and queue campaign',exact=True).click()
        await page.get_by_text('Campaign approved and queued. Start automatic sending when your mailbox is connected.',exact=True).wait_for()
        # Deliberately never enable sending or connect an account in this test.
        campaigns=await (await page.request.get(base+'/api/campaigns')).json()
        assert len(campaigns['messages'])==2
        assert all(m['status']=='queued' for m in campaigns['messages'])
        await page.get_by_role('button',name='Close dialog').click()
        for view,title in [('linkedin','Your LinkedIn application desk.'),('toolkit','Prepare for what comes next.'),('settings','Keep things moving.'),('campaigns','One campaign. Individual conversations.')]:
            await page.locator(f'nav [data-view="{view}"]').click()
            await page.get_by_role('heading',name=title,exact=True).wait_for()
            await page.wait_for_timeout(200)
        folder=ROOT/'artifacts'/'screenshots';folder.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(folder/'campaign-desktop.png'),full_page=True)
        await page.set_viewport_size({'width':390,'height':844})
        await page.locator('nav [data-view="overview"]').click()
        await page.screenshot(path=str(folder/'overview-mobile.png'),full_page=True)
        assert not await page.evaluate('document.documentElement.scrollWidth>window.innerWidth'),'Mobile horizontal overflow'
        assert not errors,errors
        state=await (await page.request.get(base+'/api/state')).json()
        assert not state['policy']['auto_send_queued'] and not state['policy']['auto_apply_ready']
        print('PASS: profile -> job import -> PDFs -> approval -> resume upload -> single HR -> sheet -> campaign preview -> approved queue; nine screens; desktop/mobile; zero external sends')
        await browser.close()


def main():
    with tempfile.TemporaryDirectory(prefix='lance-ui-') as temp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env=os.environ.copy();env['LANCE_DATA']=temp
        for name in ('SMTP_USER','SMTP_PASSWORD','ANTHROPIC_API_KEY','ANTHROPIC_MODEL','OLLAMA_MODEL','NOTION_TOKEN'):
            env.pop(name,None)
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port)],
            cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
        base=f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                try:
                    if httpx.get(base,timeout=1).status_code==200:break
                except httpx.HTTPError:pass
                if process.poll() is not None:raise RuntimeError('QA server exited before becoming ready')
                time.sleep(.1)
            else:raise RuntimeError('QA server did not become ready')
            asyncio.run(browser_flow(base))
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':main()

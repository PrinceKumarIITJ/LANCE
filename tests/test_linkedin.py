import asyncio
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
from tests.test_workflow import client,approved_job
from browser_agent import BrowserAgent
import linkedin_flow
import store

CHROME=Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')


@pytest.mark.skipif(not CHROME.exists(),reason='Google Chrome not installed')
@pytest.mark.parametrize('submit',[False,True])
def test_multistep_easy_apply_known_answers_and_final_submit(client,monkeypatch,submit):
    jid=approved_job(client)
    with store.db() as con:con.execute('UPDATE jobs SET url=? WHERE id=?',('https://www.linkedin.com/jobs/view/123456789/',jid))
    p=store.get_setting('profile');p['answers']={'authorized to work in india?':'Yes'};store.set_setting('profile',p)
    async def check():
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(channel='chrome',headless=True)
            context=await browser.new_context()
            agent=BrowserAgent();agent.context=context;agent.page=await context.new_page();agent.job_id=jid
            monkeypatch.setattr(linkedin_flow,'agent',agent)
            await agent.page.set_content('''<div role="dialog"><form>
                <label>First name<input name="first" required></label><label>Email<input type="email" required></label>
                <label>Resume<input type="file" required></label>
                <button type="button" aria-label="Continue to next step" onclick="nextStep()">Next</button></form></div>
                <script>
                function nextStep(){document.querySelector('[role=dialog]').innerHTML=`<form>
                  <fieldset><legend>Authorized to work in India?</legend><label><input type="radio" name="auth" required>Yes</label><label><input type="radio" name="auth" required>No</label></fieldset>
                  <button type="button" aria-label="Review your application" onclick="reviewStep()">Review</button></form>`;}
                function reviewStep(){document.querySelector('[role=dialog]').innerHTML=`<p>Review application</p><button type="button" onclick="finish()">Submit application</button>`;}
                function finish(){document.querySelector('[role=dialog]').innerHTML='<h2>Your application was sent</h2>';}
                </script>''')
            result=await linkedin_flow.apply(jid,submit=submit,resume=True)
            assert result['status']==('submitted' if submit else 'assisted'),result
            assert store.job(jid)['status']==('submitted' if submit else 'assisted')
            await browser.close()
    asyncio.run(check())


@pytest.mark.skipif(not CHROME.exists(),reason='Google Chrome not installed')
def test_easy_apply_stops_on_unknown_question(client,monkeypatch):
    jid=approved_job(client)
    with store.db() as con:con.execute('UPDATE jobs SET url=? WHERE id=?',('https://www.linkedin.com/jobs/view/987654321/',jid))
    async def check():
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(channel='chrome',headless=True)
            agent=BrowserAgent();agent.context=await browser.new_context();agent.page=await agent.context.new_page();agent.job_id=jid
            monkeypatch.setattr(linkedin_flow,'agent',agent)
            await agent.page.set_content('<div role="dialog"><form><label>Expected salary<input name="salary" required></label><button>Submit application</button></form></div>')
            result=await linkedin_flow.apply(jid,submit=True,resume=True)
            assert result['status']=='needs_input'
            assert 'Expected salary' in result['message']
            assert store.job(jid)['status']=='needs_input'
            await browser.close()
    asyncio.run(check())

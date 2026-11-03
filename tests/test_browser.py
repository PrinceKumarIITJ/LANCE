"""Real Chrome tests against synthetic content only; no external application is sent."""
import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright
from browser_agent import BrowserAgent
import store
import packets
import browser_agent


CHROME = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')


@pytest.mark.skipif(not CHROME.exists(), reason='Google Chrome not installed')
def test_real_browser_fill_required_fields_and_confirmation(tmp_path, monkeypatch):
    for module in (store, packets, browser_agent):
        monkeypatch.setattr(module, 'DATA', tmp_path)
    store.init()
    profile = store.get_setting('profile')
    profile.update(name='Browser Test', email='browser@example.com', phone='+919999999999',
                   college='Test Institute', available_from='2027-06-01', skills=['Python'],
                   facts=['Test project: built a Python API.'])
    store.set_setting('profile', profile)
    from discovery import ingest
    jid = ingest(dict(company='Synthetic Test', title='Graduate Software Engineer', location='India',
        url='https://example.com/synthetic-test', provider='manual', description='Graduates in 2027. Python.'))

    async def check():
        await packets.prepare(jid)
        with store.db() as con:
            con.execute("UPDATE jobs SET status='ready' WHERE id=?", (jid,))
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel='chrome', headless=True)
            context = await browser.new_context()
            agent = BrowserAgent()
            agent.context = context
            agent.page = await context.new_page()
            agent.job_id = jid
            await agent.page.set_content('''<form id="application">
              <label>Full name<input name="full" required></label>
              <label>Email<input type="email" name="email" required></label>
              <label>Resume<input type="file" name="resume" required></label>
              <label>Why this company?<textarea name="why" required></textarea></label>
              <label><input type="checkbox" name="consent" required>I consent</label>
              <button type="submit">Submit application</button></form>
              <script>document.querySelector('form').addEventListener('submit', ev => {
                ev.preventDefault(); document.body.innerHTML='<h1>Your application has been submitted</h1><p>Synthetic test only</p>';
              });</script>''')
            result = await agent.fill(jid)
            assert 'Full name' in result['filled']
            assert 'Resume PDF' in result['filled']
            assert 'Why this company?' in result['needs_you']
            assert await agent.page.locator('input[name="full"]').input_value() == 'Browser Test'
            assert not await agent.page.locator('input[name="consent"]').is_checked()
            with pytest.raises(ValueError, match='Complete required fields'):
                await agent.submit(jid)
            assert store.job(jid)['status'] == 'assisted'
            await agent.page.locator('textarea').fill('Synthetic test response')
            await agent.page.locator('[name="consent"]').check()
            result = await agent.submit(jid)
            assert result['status'] == 'submitted'
            assert Path(result['evidence']['screenshot']).is_file()
            assert 'submitted' in result['evidence']['confirmation']
            with pytest.raises(ValueError, match='Fill and review'):
                await agent.submit(jid)
            await browser.close()
    asyncio.run(check())

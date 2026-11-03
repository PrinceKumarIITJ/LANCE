"""LinkedIn browser connector. Uses the candidate's visible, logged-in session."""
import asyncio
import re
from urllib.parse import urlencode, urlsplit
from browser_agent import agent
from discovery import ingest
from store import DATA, db, job, now, event

flow_lock = asyncio.Lock()


def is_linkedin(url):
    host = (urlsplit(url).hostname or '').lower()
    return host == 'linkedin.com' or host.endswith('.linkedin.com')


async def status():
    signed_in = False
    if agent.context:
        try:
            signed_in = any(c['name'] == 'li_at' for c in await agent.context.cookies('https://www.linkedin.com'))
        except Exception:
            pass
    return {'browser_open': agent.context is not None, 'session_present': signed_in,
            'message': 'Session cookie present; security checkpoints can still require your input' if signed_in else 'Open LinkedIn and sign in locally'}


async def login():
    async with agent.lock:
        context = await agent.start()
        page = await context.new_page()
        await page.goto('https://www.linkedin.com/login', wait_until='domcontentloaded', timeout=45000)
    return {'message':'Sign in inside the Chrome window. LANCE never asks for your LinkedIn password.'}


async def first_text(page, selectors):
    for selector in selectors:
        loc = page.locator(selector).first
        if await loc.count():
            text = (await loc.inner_text()).strip()
            if text:
                return text
    return ''


async def read_posting(page, url=None):
    if not is_linkedin(page.url):
        raise ValueError('Open a LinkedIn job page first')
    title = await first_text(page, ['.job-details-jobs-unified-top-card__job-title h1','h1'])
    company = await first_text(page, ['.job-details-jobs-unified-top-card__company-name a','.jobs-unified-top-card__company-name a','.topcard__org-name-link'])
    description = await first_text(page, ['#job-details','.jobs-description-content__text','.jobs-description__content','.show-more-less-html__markup'])
    location = await first_text(page, ['.job-details-jobs-unified-top-card__tertiary-description-container','.jobs-unified-top-card__bullet','.topcard__flavor--bullet'])
    if not title or not company or len(description) < 40:
        raise ValueError('LinkedIn job details were not readable. Finish login/checkpoint or paste the job description manually.')
    return {'id':ingest(dict(company=company,title=title,description=description,location=location[:300],url=url or page.url,provider='linkedin'))}


async def search(keywords, location='India', limit=5):
    async with flow_lock:
        async with agent.lock:
            context = await agent.start()
            page = await context.new_page()
            await page.goto('https://www.linkedin.com/jobs/search/?'+urlencode({
                'keywords':keywords,'location':location,'f_JT':'F','f_E':'2','f_TPR':'r604800'}),
                wait_until='domcontentloaded',timeout=45000)
            if '/login' in page.url or '/checkpoint' in page.url or '/authwall' in page.url:
                raise ValueError('Complete LinkedIn login or its security checkpoint in Chrome, then search again')
            try:
                await page.locator('a[href*="/jobs/view/"]').first.wait_for(timeout=15000)
            except Exception:
                raise ValueError('No readable LinkedIn job cards found. Check the visible Chrome page; page layouts may require manual import.')
            hrefs = await page.locator('a[href*="/jobs/view/"]').evaluate_all('els => els.map(el=>el.href)')
            links = []
            for href in hrefs:
                match = re.search(r'/jobs/view/(?:[^/?]*-)?(\d+)',href)
                if match:
                    target = 'https://www.linkedin.com/jobs/view/'+match[1]+'/'
                    if target not in links:
                        links.append(target)
            results=[]
            for link in links[:limit]:
                detail = await context.new_page()
                try:
                    await detail.goto(link,wait_until='domcontentloaded',timeout=45000)
                    await detail.locator('#job-details,.jobs-description__content,.show-more-less-html__markup').first.wait_for(timeout=12000)
                    results.append(await read_posting(detail,link))
                except Exception as exc:
                    results.append({'url':link,'error':str(exc)[:250]})
                finally:
                    await detail.close()
            event('linkedin_search',f'{keywords}; {len(results)} job detail attempts')
            return {'results':results,'message':'Imported readable jobs; review eligibility before applying'}


async def pause(job_id, reason):
    with db() as con:
        con.execute("UPDATE jobs SET status='needs_input',updated_at=? WHERE id=? AND status NOT IN ('submitted','submitting','uncertain')",(now(),job_id))
    event('linkedin_needs_input',reason,job_id)
    return {'status':'needs_input','message':reason}


async def apply(job_id, submit=False, resume=False):
    async with flow_lock:
        item=job(job_id)
        if not is_linkedin(item['url']):
            raise ValueError('This is not a LinkedIn job URL')
        if item['status'] not in ('ready','auto_running','assisted','needs_input'):
            raise ValueError('Prepare and approve the application packet first')
        if not resume:
            await agent.open(job_id)
        else:
            agent._check(job_id)
        page=agent.page
        if '/login' in page.url or '/checkpoint' in page.url or '/authwall' in page.url:
            return await pause(job_id,'Complete LinkedIn login or security verification in Chrome, then Resume Easy Apply')
        dialog=page.locator('[role="dialog"]').filter(has=page.locator('form')).first
        if not await dialog.count():
            # Some LinkedIn variants place the form directly in the modal container.
            dialog=page.locator('.jobs-easy-apply-modal,[role="dialog"]').first
        if not await dialog.count():
            button=page.get_by_role('button',name=re.compile('Easy Apply',re.I)).first
            try:
                await button.wait_for(state='visible',timeout=10000)
                await button.click()
                await page.locator('[role="dialog"],.jobs-easy-apply-modal').first.wait_for(timeout=10000)
            except Exception:
                return await pause(job_id,'Easy Apply is unavailable or not readable. Use the external Apply link in Chrome or import the company career URL.')
        scope='[role="dialog"]:visible, .jobs-easy-apply-modal:visible'
        # Choose one root selector to avoid duplicate matching of the same modal.
        scope='[role="dialog"]:visible' if await page.locator('[role="dialog"]:visible').count() == 1 else '.jobs-easy-apply-modal:visible'
        for step in range(10):
            result=await agent.fill(job_id,scope_selector=scope,trust_existing=resume)
            if result['needs_you']:
                return await pause(job_id,'Complete these fields in Chrome or save exact answers in your profile: '+', '.join(dict.fromkeys(result['needs_you'])))
            root=page.locator(scope)
            final=root.get_by_role('button',name=re.compile(r'^Submit application$',re.I))
            if await final.count() and await final.first.is_visible():
                if submit:
                    return await agent.submit(job_id)
                return {'status':'assisted','message':'Reached the final review step. Check the form in Chrome, then click Submit reviewed form.'}
            missing=await root.locator('input,select,textarea').evaluate_all('els=>els.filter(e=>e.willValidate&&!e.validity.valid).length')
            if missing:
                return await pause(job_id,'Required fields remain; complete them in Chrome, then resume')
            next_buttons=root.get_by_role('button',name=re.compile(r'^(Next|Continue|Review|Continue to next step|Review your application)$',re.I))
            visible=[]
            for button in await next_buttons.all():
                if await button.is_visible() and await button.is_enabled():
                    visible.append(button)
            if len(visible)!=1:
                return await pause(job_id,'No unique next/review button found; continue the visible form manually, then resume')
            before=await root.inner_text()
            await visible[0].click()
            try:
                await page.wait_for_function('(data)=>{const root=document.querySelector(data.selector);return root&&root.innerText!==data.text}',
                    arg={'selector':'[role="dialog"]' if 'role=' in scope else '.jobs-easy-apply-modal','text':before},timeout=8000)
            except Exception:
                return await pause(job_id,'The portal did not advance; check inline validation messages in Chrome')
        return await pause(job_id,'Step limit reached. Review the remaining form in Chrome.')

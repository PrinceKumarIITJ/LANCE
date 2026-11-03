"""Visible, local browser assistant. Never guess questionnaire or legal answers."""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright
from store import DATA, db, get_setting, job, now, event, profile_hash
from packets import packet_path
from discovery import public_url


class BrowserAgent:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.playwright = None
        self.context = None
        self.page = None
        self.job_id = None
        self.scope_selector = None

    async def start(self):
        if self.context is None:
            self.playwright = await async_playwright().start()
            try:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    str(DATA / 'browser-profile'), channel='chrome', headless=False,
                    viewport={'width': 1280, 'height': 900})
            except Exception:
                await self.playwright.stop()
                self.playwright = None
                raise ValueError('Chrome could not start. Install Google Chrome and close any LANCE browser already using this profile.')
            self.context.on('close', self._closed)
        return self.context

    def _closed(self, *_):
        self.context, self.page, self.job_id = None, None, None

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()

    async def open(self, job_id):
        async with self.lock:
            item = job(job_id)
            if item['status'] in ('submitting', 'submitted', 'uncertain'):
                raise ValueError('Application already submitted or uncertain; verify the portal before continuing')
            context = await self.start()
            if self.page and not self.page.is_closed() and self.job_id:
                if job(self.job_id)['status']=='submitted':
                    await self.page.close()
            self.page = await context.new_page()
            self.job_id = job_id
            self.scope_selector = None
            await self.page.goto(public_url(item['url']), wait_until='domcontentloaded', timeout=45000)
            event('browser_opened', 'Application opened in dedicated Chrome profile', job_id)
            return {'status': 'opened', 'message': 'Log in if needed and navigate to the application form; then click Fill current form.'}

    async def fill(self, job_id, scope_selector=None, trust_existing=False):
        async with self.lock:
            self._check(job_id)
            profile = get_setting('profile')
            item = job(job_id)
            if item['status'] not in ('ready', 'assisted', 'auto_running', 'needs_input'):
                raise ValueError('Review and approve the application packet first')
            manifest=json.loads(packet_path(job_id,'manifest.json').read_text(encoding='utf-8'))
            expected_hash=profile_hash(manifest['profile_snapshot'])
            if expected_hash!=profile_hash(profile):
                raise ValueError('Profile changed after this packet was prepared; regenerate and approve the materials')
            names = profile['name'].split()
            self.scope_selector = scope_selector
            values = {'first name': names[0], 'last name': ' '.join(names[1:]), 'full name': profile['name'],
                'name': profile['name'], 'email': profile['email'], 'email address': profile['email'],
                'phone': profile['phone'], 'phone number': profile['phone'], 'mobile phone number': profile['phone'],
                'linkedin': profile.get('linkedin', ''), 'linkedin profile': profile.get('linkedin', ''),
                'github': profile.get('github', ''), 'portfolio': profile.get('portfolio', '')}
            values.update({str(k).strip().lower(): str(v) for k, v in profile.get('answers', {}).items()})
            filled, skipped = [], []
            for frame in self.page.frames:
                root = frame.locator(scope_selector) if scope_selector else frame.locator('body')
                if not await root.count():
                    continue
                for field in await root.locator('input,textarea,select').all():
                    kind = (await field.get_attribute('type') or 'text').lower()
                    if (not await field.is_visible() and kind != 'file') or not await field.is_enabled():
                        continue
                    if kind in ('hidden', 'submit', 'button'):
                        continue
                    info = await field.evaluate('''el => ({tag: el.tagName.toLowerCase(), label: ((el.labels && [...el.labels].map(x=>x.innerText).join(' ')) || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '').trim()})''')
                    label = re.sub(r'\s*\*\s*$', '', info['label']).strip().lower()
                    if kind in ('radio', 'checkbox'):
                        question = await field.evaluate('''el => {const g=el.closest('fieldset,[role="group"],.fb-dash-form-element'); return g ? (g.querySelector('legend,.fb-dash-form-element__label,[data-test-form-element-label]')?.innerText || '') : ''}''')
                        question = re.sub(r'\s*\*\s*$', '', question).strip().lower() or label
                        answer = values.get(question)
                        if trust_existing and not answer:
                            answered = await field.evaluate('''el => el.type === 'checkbox' ? (!el.required || el.checked) : [...(el.form?.elements || document.querySelectorAll('input'))].some(x=>x.type==='radio'&&x.name===el.name&&x.checked)''')
                            if answered:
                                filled.append('Existing choice (reviewed)')
                                continue
                        if kind == 'radio' and answer and answer.strip().casefold() == label.casefold():
                            await field.check()
                            filled.append(question)
                        elif kind == 'radio' and answer:
                            continue
                        elif kind == 'checkbox' and answer and answer.lower() in ('yes','true','checked','no','false','unchecked'):
                            await field.set_checked(answer.lower() in ('yes','true','checked'))
                            filled.append(question)
                        else:
                            skipped.append(info['label'] or 'Consent or selection needs your review')
                        continue
                    if kind == 'password':
                        skipped.append('Login required')
                        continue
                    if kind == 'file':
                        if re.search('resume|cv', label):
                            await field.set_input_files(str(packet_path(job_id)))
                            filled.append('Resume PDF')
                        else:
                            skipped.append(info['label'] or 'Unidentified attachment')
                        continue
                    value = values.get(label)
                    if not value:
                        if trust_existing and (await field.input_value()).strip():
                            filled.append('Existing answer (reviewed)')
                            continue
                        skipped.append(info['label'] or 'Unlabelled field')
                        continue
                    try:
                        if info['tag'] == 'select':
                            await field.select_option(label=value, timeout=2000)
                        else:
                            await field.fill(value, timeout=2000)
                        filled.append(info['label'])
                    except Exception:
                        skipped.append(info['label'])
            with db() as con:
                if profile_hash()!=expected_hash or job(job_id)['packet']!=item['packet']:
                    raise ValueError('Profile or packet changed while filling; review a fresh packet before submitting')
                con.execute("UPDATE jobs SET status='assisted',updated_at=? WHERE id=?", (now(), job_id))
            event('browser_filled', json.dumps({'filled': filled, 'needs_you': skipped}), job_id)
            return {'filled': filled, 'needs_you': skipped,
                    'message': 'Check every answer in Chrome. Complete unknown fields and consent choices yourself. Multi-step forms may need Fill again.'}

    def _check(self, job_id):
        if not self.page or self.page.is_closed() or self.job_id != job_id:
            raise ValueError('Open this job in the browser assistant first')

    async def submit(self, job_id):
        async with self.lock:
            self._check(job_id)
            item = job(job_id)
            if item['status'] != 'assisted':
                raise ValueError('Fill and review the form before submitting')
            manifest=json.loads(packet_path(job_id,'manifest.json').read_text(encoding='utf-8'))
            if profile_hash(manifest['profile_snapshot'])!=profile_hash():
                raise ValueError('Profile changed; regenerate and review materials before submitting')
            body = await self.page.locator('body').inner_text()
            confirmation_pattern = r'(?:your application (?:has been|was) (?:successfully )?(?:submitted|received|sent)|application (?:submitted successfully|sent)|thank you for applying|thanks for applying)'
            if re.search(confirmation_pattern, body, re.I):
                raise ValueError('This page already shows an application confirmation. Verify it and record the outcome instead of submitting again.')
            if re.search(r'verify you are human|complete the captcha|security verification', body, re.I):
                raise ValueError('Complete the portal security check in Chrome first')
            for frame in self.page.frames:
                root = frame.locator(self.scope_selector) if self.scope_selector else frame.locator('body')
                if not await root.count():
                    continue
                missing = await root.locator('input:visible,select:visible,textarea:visible').evaluate_all('''els => els.filter(e => e.willValidate && !e.validity.valid).map(e => (e.labels && [...e.labels].map(l=>l.innerText).join(' ')) || e.name || 'Unanswered field')''')
                if missing:
                    raise ValueError('Complete required fields: ' + ', '.join(missing[:10]))
            candidates = []
            for frame in self.page.frames:
                root = frame.locator(self.scope_selector) if self.scope_selector else frame.locator('body')
                if not await root.count():
                    continue
                loc = root.get_by_role('button', name=re.compile(r'^(submit application|send application|submit)$', re.I))
                for button in await loc.all():
                    if await button.is_visible() and await button.is_enabled():
                        candidates.append(button)
            if len(candidates) != 1:
                raise ValueError('A unique final submit button was not found. Complete the portal flow manually and record its confirmation.')
            with db() as con:
                cur = con.execute("UPDATE jobs SET status='submitting' WHERE id=? AND status='assisted'", (job_id,))
                if cur.rowcount != 1:
                    raise ValueError('Submission is already in progress')
            status = 'uncertain'
            evidence = {'url': self.page.url, 'time': now()}
            try:
                await candidates[0].click(timeout=15000)
                await self.page.wait_for_timeout(2500)
                text = await self.page.locator('body').inner_text()
                confirm = re.search(confirmation_pattern, text, re.I)
                if confirm:
                    status = 'submitted'
                    evidence['confirmation'] = text[max(0, confirm.start() - 80):confirm.end() + 250]
                evidence['url'] = self.page.url
                folder = DATA / 'evidence'
                folder.mkdir(exist_ok=True)
                screenshot = folder / f'{job_id}.png'
                await self.page.screenshot(path=str(screenshot), full_page=True)
                evidence['screenshot'] = str(screenshot)
            except Exception as exc:
                evidence['error'] = type(exc).__name__
            with db() as con:
                con.execute('UPDATE jobs SET status=?,evidence=?,updated_at=? WHERE id=?',
                            (status, json.dumps(evidence), now(), job_id))
            event('browser_' + status, json.dumps(evidence), job_id)
            return {'status': status, 'evidence': evidence,
                    'message': 'Submission confirmed' if status == 'submitted' else 'Confirmation not detected. Check portal/email; this application will not be retried automatically.'}


agent = BrowserAgent()

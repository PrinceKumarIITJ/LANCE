"""Read-only browser check of a running local dashboard; run from project root."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='chrome', headless=True)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1080})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        response = await page.goto('http://127.0.0.1:8765', wait_until='networkidle')
        assert response.status == 200
        await page.get_by_role('heading', name='Your next opportunities').wait_for()
        folder = Path('data/qa')
        folder.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(folder / 'dashboard-desktop.png'), full_page=True)
        for label, heading in [
            ('Job pipeline', 'Your application pipeline.'),
            ('Career sources', 'Find openings at the source.'),
            ('HR outreach', 'Start the right conversations.'),
            ('Your profile', 'The work that makes you, you.'),
            ('Automation', 'Keep things moving.'),
        ]:
            await page.get_by_role('button', name=label, exact=True).click()
            await page.get_by_role('heading', name=heading, exact=True).wait_for()
        await page.get_by_role('button', name='Job pipeline', exact=True).click()
        await page.get_by_role('button', name='+ Import a job', exact=True).click()
        await page.get_by_role('heading', name='Import a real opening').wait_for()
        await page.get_by_role('button', name='Close dialog').click()
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.get_by_role('button', name='Overview', exact=True).click()
        await page.screenshot(path=str(folder / 'dashboard-mobile.png'), full_page=True)
        assert not await page.evaluate('document.documentElement.scrollWidth > window.innerWidth'), 'Horizontal overflow on mobile'
        assert not errors, errors
        print('UI PASS: six screens, import dialog, desktop/mobile, no JS errors, no mobile overflow')
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())

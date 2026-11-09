"""Exercise panel controls and autosave with isolated browser API fixtures.

No backend records are written and no phone or voice sessions are started.
Run after building the frontend, against the local dashboard server.
"""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


async def run(base_url):
    zone = {"id": "ui-test-area", "label": "Test area", "area": "Mission Valley", "level": "warning",
            "instruction": "Exercise instruction", "version": 1,
            "polygon": [[32.76, -117.16], [32.78, -117.16], [32.78, -117.12]]}
    snapshot = {"calls": [], "zones": [zone], "fires": [], "facilities": [], "incidents": [], "routes": [], "updated_at": "2026-11-08T12:00:00Z"}
    requests, errors = [], []
    fail_next = False
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def api(route):
            nonlocal fail_next
            if route.request.url.endswith('/api/dashboard/snapshot'):
                await route.fulfill(json=snapshot)
            elif route.request.url.endswith('/api/dashboard/zones') and route.request.method == 'POST':
                body = route.request.post_data_json
                requests.append(body)
                await asyncio.sleep(.9)
                if fail_next:
                    fail_next = False
                    await route.fulfill(status=503, json={"detail": "Temporary test outage"})
                    return
                saved = {**body, 'version': snapshot['zones'][0]['version'] + 1}
                snapshot['zones'] = [saved]
                await route.fulfill(json=saved)
            else:
                await route.fulfill(status=404, json={"detail": "Unexpected test request"})
        await page.route('**/api/**', api)
        await page.goto(base_url.rstrip('/') + '/dashboard/')
        overview = page.get_by_role('region', name='Overview panel', exact=True)
        await expect(overview).to_be_visible()
        assert not await page.get_by_text('Publish area instruction', exact=True).count()
        assert not await page.get_by_text('Import crawler results', exact=True).count()
        before = await overview.bounding_box()
        handle = overview.locator('header')
        handle_box = await handle.bounding_box()
        await page.mouse.move(handle_box['x'] + 95, handle_box['y'] + 20)
        await page.mouse.down()
        await page.mouse.move(handle_box['x'] + 295, handle_box['y'] + 50, steps=12)
        await page.mouse.up()
        after = await overview.bounding_box()
        assert after['x'] > before['x'] + 150, (before, after)
        resize = overview.get_by_role('separator', name='Resize Overview')
        await resize.focus()
        await page.keyboard.press('ArrowRight')
        assert (await overview.bounding_box())['width'] > after['width']
        await overview.get_by_role('button', name='Close Overview', exact=True).click()
        await expect(overview).to_be_hidden()
        await page.get_by_role('button', name='Toggle navigation panel', exact=True).click()
        await expect(overview).to_be_visible()
        await page.get_by_role('button', name='Reset workspace layout').click()
        await page.wait_for_timeout(100)
        assert (await overview.bounding_box())['x'] == before['x']
        await page.get_by_role('navigation', name='Workspace').get_by_role('button', name='Areas').click()
        await overview.get_by_role('button', name='Test area').click()
        detail = page.get_by_role('region', name='Area instruction panel', exact=True)
        instruction = detail.get_by_role('textbox', name='Instruction', exact=True)
        await instruction.fill('First edit')
        await expect(detail.get_by_role('status')).to_have_text('Saving…')
        await instruction.fill('Newest edit')
        # Closing during a write must preserve and serialize the newer edit.
        await detail.get_by_role('button', name='Close Area instruction', exact=True).click()
        await expect(detail).to_be_hidden()
        await page.wait_for_timeout(2800)
        assert snapshot['zones'][0]['instruction'] == 'Newest edit', snapshot
        assert [body['instruction'] for body in requests] == ['First edit', 'Newest edit'], requests
        await page.get_by_role('button', name='Toggle details panel', exact=True).click()
        await expect(detail.get_by_role('status')).to_have_text('Saved · live')
        fail_next = True
        await instruction.fill('Retry this edit')
        await expect(detail.get_by_role('button', name='Retry save')).to_be_visible(timeout=5000)
        assert snapshot['zones'][0]['instruction'] == 'Newest edit'
        await detail.get_by_role('button', name='Retry save').click()
        await expect(detail.get_by_role('status')).to_have_text('Saved · live', timeout=5000)
        assert snapshot['zones'][0]['instruction'] == 'Retry this edit'
        count = len(requests)
        await instruction.fill('')
        await page.wait_for_timeout(800)
        assert len(requests) == count, 'An incomplete instruction was submitted'
        await instruction.fill('Final saved edit')
        await expect(detail.get_by_role('status')).to_have_text('Saved · live', timeout=5000)
        await page.get_by_role('button', name='Inbox', exact=True).click()
        inbox = page.get_by_role('region', name='Inbox panel', exact=True)
        await expect(inbox).to_be_visible()
        await inbox.get_by_role('button', name='Close Inbox', exact=True).click()
        out = ROOT / '.runtime' / 'ui-workspace'
        out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / 'panels-desktop.png'))
        for width, height in [(1024, 768), (768, 1024), (390, 844), (320, 640)]:
            await page.set_viewport_size({'width': width, 'height': height})
            await page.wait_for_timeout(100)
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Page overflows at {width}px'
            for control in await page.locator('header.dashboard-header button, header.dashboard-header a, nav[aria-label="Workspace"] button').all():
                if await control.is_visible():
                    box = await control.bounding_box()
                    assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1, ('clipped toolbar', width, box)
            await expect(detail).to_be_visible()
            bounds = await detail.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width + 1, (width, bounds)
            assert bounds['y'] + bounds['height'] <= height + 1, (height, bounds)
            if width <= 900:
                await expect(overview).to_be_hidden()
        await page.get_by_role('button', name='Toggle details panel').click()
        await expect(overview).to_be_visible()
        await expect(detail).to_be_hidden()
        await page.get_by_role('button', name='Toggle details panel').click()
        await expect(detail).to_be_visible()
        await page.screenshot(path=str(out / 'panels-mobile.png'))
        await detail.get_by_role('button', name='Close Area instruction', exact=True).click()
        await expect(overview).to_be_visible()
        await page.get_by_role('button', name='Show map only').click()
        await expect(overview).to_be_hidden()
        await expect(detail).to_be_hidden()
        assert not errors, errors
        await browser.close()
        return {'passed': True, 'checks': ['drag', 'resize', 'close/reopen', 'reset', 'serialized autosave', 'save after close', 'failure/retry', 'incomplete input', 'inbox', 'responsive 320–1440px', 'map only'], 'save_requests': len(requests)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.base_url)), indent=2))

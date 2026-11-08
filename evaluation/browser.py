"""Run the actual built React dashboard against the isolated ASGI backend.

Only transport is bridged: its normal fetch/polling, React rendering, and Leaflet
map run unmodified. External map tiles are blocked; no real maps/data are queried.
"""
from urllib.parse import urlsplit
import re


class Dashboard:
    def __init__(self, browser, sandbox):
        self.sandbox = sandbox
        self.context = browser.new_context(viewport={'width':1600,'height':1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)[:500]))
        self.page.route('**/*', self.route)
        self.page.goto('http://evaluation.test/dashboard/', wait_until='domcontentloaded')

    def route(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != 'evaluation.test':
            route.abort()
            return
        response = self.sandbox.client.request(request.method, url.path+('?' + url.query if url.query else ''),
                                               content=request.post_data, headers={'content-type':request.headers.get('content-type','application/json')})
        headers = {k:v for k,v in response.headers.items() if k.lower() not in {'content-length','content-encoding'}}
        route.fulfill(status=response.status_code, headers=headers, body=response.content)

    def inspect(self, snapshot, screenshot=None, reload=False):
        if reload:
            self.page.reload(wait_until='domcontentloaded')
        call = snapshot
        short = call['id'][:8]
        card = self.page.get_by_role('button').filter(has_text='Voice · '+short).first
        location = call['assessment'].get('location') or 'Location not confirmed'
        instruction = (call.get('instruction') or {}).get('text')
        render_error = None
        try:
            self.page.get_by_role('tab',name=re.compile(r'^Calls')).click(timeout=5000)
            card.wait_for(timeout=5000)
            card.click(timeout=5000)
            self.page.wait_for_function('([location, instruction]) => { const a=document.querySelectorAll("aside"); const t=a[a.length-1]?.innerText || ""; return t.includes(location) && (!instruction || t.includes(instruction)); }',
                                        arg=[location,instruction], timeout=5000)
        except Exception as exc:
            render_error = type(exc).__name__+': dashboard did not converge to current location/instruction'
        detail = self.page.locator('aside').last.inner_text(timeout=5000)
        # Leaflet renders CircleMarker geometry as SVG paths containing arc commands.
        expected_markers = sum(c['assessment'].get('location_resolution',{}).get('status')=='resolved' for c in self.sandbox.snapshot()['calls'])
        # The selected call may not change when another call is added. Wait for
        # polling to render its marker too, rather than score the previous frame.
        try:
            self.page.wait_for_function(r'n => [...document.querySelectorAll(".leaflet-overlay-pane path")].filter(e => /a\d+(?:\.\d+)?,\d/.test(e.getAttribute("d") || "")).length === n',arg=expected_markers,timeout=5000)
        except Exception:
            pass
        paths = self.page.locator('.leaflet-overlay-pane path').evaluate_all(r'(els) => els.map(e => e.getAttribute("d")).filter(d => /a\d+(?:\.\d+)?,\d/.test(d || ""))')
        result = {'detail':detail, 'circle_paths':paths, 'expected_marker_count':expected_markers,
                  'marker_count_matches':len(paths)==expected_markers, 'page_errors':list(self.errors), 'render_error':render_error,
                  'scope':'Rendered dashboard, matching current text and circle count; geometry screenshots retained for review. Not an independent geographic-accuracy proof.'}
        if screenshot:
            self.page.screenshot(path=str(screenshot), full_page=True)
        return result

    def close(self):
        self.context.close()

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
        location = 'Confirmation pending: '+call['pending_location'] if call.get('pending_location') else call['assessment'].get('location') or 'Location not confirmed'
        instruction = (call.get('instruction') or {}).get('text')
        render_error = None
        try:
            navigation = self.page.get_by_role('navigation',name='Workspace')
            if navigation.count():
                calls = navigation.get_by_role('button',name=re.compile(r'^Calls',re.I))
                if calls.get_attribute('aria-pressed') != 'true':
                    calls.click(timeout=5000)
            else:
                self.page.get_by_role('tab',name=re.compile(r'^Calls')).click(timeout=5000)
            card.wait_for(timeout=5000)
            card.click(timeout=5000)
            details = self.page.get_by_role('button',name='Details',exact=True)
            if details.count() and details.get_attribute('aria-expanded') == 'false':
                details.click(timeout=5000)
            self.page.wait_for_function('([location, instruction]) => { const a=document.querySelectorAll("aside"); const panel=document.querySelector(\'[aria-label="Call details panel"]\') || a[a.length-1]; const t=panel?.innerText || ""; return t.includes(location) && (!instruction || t.includes(instruction)); }',
                                        arg=[location,instruction], timeout=5000)
        except Exception as exc:
            render_error = type(exc).__name__+': dashboard did not converge to current location/instruction'
        panel = self.page.get_by_role('region',name='Call details panel')
        detail = (panel if panel.count() else self.page.locator('aside').last).inner_text(timeout=5000)
        expected_markers = sum(c['assessment'].get('location_resolution',{}).get('status')=='resolved' for c in self.sandbox.snapshot()['calls'])
        # The selected call may not change when another call is added. Wait for
        # polling to render its marker too, rather than score the previous frame.
        try:
            self.page.wait_for_function('n => document.querySelectorAll(".caller-marker").length === n',arg=expected_markers,timeout=5000)
        except Exception:
            pass
        # flyTo animates for 0.6s. Wait for stable rendered geometry, rather than
        # capturing a marker and polygons in different animation frames.
        settled = self.page.evaluate('''() => new Promise(resolve => {
          const start=performance.now(); let last='',changed=start;
          const tick=() => {
            const now=performance.now();
            const nodes=[...document.querySelectorAll('.leaflet-map-pane,.leaflet-overlay-pane path,.response-marker')];
            const current=JSON.stringify(nodes.map(e=>[e.getAttribute('d'),e.getAttribute('style'),e.getBoundingClientRect().x,e.getBoundingClientRect().y]));
            if(current!==last){last=current;changed=now;}
            if(now-start>650 && now-changed>250) return resolve(true);
            if(now-start>4000) return resolve(false);
            requestAnimationFrame(tick);
          }; requestAnimationFrame(tick);
        })''')
        markers = self.page.locator('.caller-marker').evaluate_all('(els) => els.map(e => e.title)')
        map_box = self.page.locator('.leaflet-container').bounding_box()
        map_visible = bool(map_box and map_box['width'] >= 200 and map_box['height'] >= 200 and self.page.locator('.leaflet-container').is_visible())
        # Compare the Leaflet anchors even if the caller icon sits beside the
        # place icon to keep both click targets visible.
        from evaluation.backend import LOCATIONS
        query = call['assessment'].get('location') or ''
        fixture = next((name for name in LOCATIONS if query==name or query.startswith(name+',') or query.startswith(name+' in ')),None)
        marker_geometry = self.page.evaluate('''name => {
          if(!name) return null;
          const place=[...document.querySelectorAll('.leaflet-marker-icon:not(.caller-marker)')].find(e=>e.title===name);
          const caller=document.querySelector('.caller-marker-selected');
          if(!place||!caller) return {matches:false,reason:'Expected place or selected caller marker missing'};
          const anchor=marker => {
            const bounds=marker.getBoundingClientRect();
            return [bounds.x-parseFloat(marker.style.marginLeft),bounds.y-parseFloat(marker.style.marginTop)];
          };
          const a=anchor(place),b=anchor(caller);
          const distance=Math.hypot(a[0]-b[0],a[1]-b[1]);
          return {matches:distance<=3,pixel_distance:distance};
        }''',fixture)
        result = {'detail':detail, 'caller_markers':markers, 'expected_marker_count':expected_markers,
                  'map_visible':map_visible, 'map_box':map_box,'map_settled':settled,'marker_geometry':marker_geometry,
                  'marker_count_matches':len(markers)==expected_markers, 'page_errors':list(self.errors), 'render_error':render_error,
                  'scope':'Rendered dashboard, current text, visible map, caller marker count and selected caller alignment with named synthetic place marker. Does not verify real-world geocoding.'}
        if screenshot:
            self.page.screenshot(path=str(screenshot), full_page=True)
        return result

    def close(self):
        self.context.close()

"""One fresh Edge context per task. Browser sandbox is not Host OS isolation."""
import uuid
import ctypes as C
from ctypes import wintypes as W
import os

from .protocol import ComputerError, fingerprint, origin


class DriverJob:
    """Kill the private Playwright process tree when the Host exits on Windows."""
    def __init__(self, playwright, *, name=None):
        if os.name != 'nt':
            raise ComputerError('platform_unverified','This backend is currently verified only on Windows')
        # Playwright has no public driver-PID API. This one version-pinned bridge
        # is isolated here and fail-closed; never attach to the user's browser.
        pid = playwright._impl_obj._connection._transport._proc.pid
        from jarvis_worker.windows import Windows, JobLimits
        self.api = Windows()
        self.job = self.api.check(self.api.create_job(None,name),'Create browser Job')
        try:
            limits=JobLimits();limits.basic.flags=0x2000
            self.api.check(self.api.set_job(self.job,9,C.byref(limits),C.sizeof(limits)),'Set browser lifecycle Job')
            kernel=C.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
            kernel.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];kernel.AssignProcessToJobObject.restype=W.BOOL
            process=self.api.check(kernel.OpenProcess(0x100|1,False,pid),'Open private browser driver')
            try:self.api.check(kernel.AssignProcessToJobObject(self.job,process),'Assign private browser driver')
            finally:self.api.close(process)
        except Exception:
            self.close();raise

    def close(self):
        if self.job:
            self.api.kill_job(self.job,1);self.api.close(self.job);self.job=None


class EdgeBrowser:
    def __init__(self, task, *, headed=False, demo_html=None, scratch_parent=None):
        self.task, self.headed, self.demo_html = task, headed, demo_html
        self.playwright = self.browser = self.context = self.page = None
        self.job = None
        self.lease = None
        self.scratch_parent = scratch_parent
        self.cleanup = None
        self.handles = {}
        self.blocked_requests = 0

    def allowed(self, url):
        try:
            return origin(url) in self.task['allowed_origins']
        except ComputerError:
            return False

    def start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ComputerError('computer_dependency_missing', 'Install the optional computer dependency group') from exc
        from jarvis_core.browser_recovery import BrowserLease
        self.lease = BrowserLease(self.scratch_parent)
        self.lease.launching()
        self.playwright = sync_playwright().start()
        self.lease.started(self.playwright._impl_obj._connection._transport._proc.pid)
        self.job = DriverJob(self.playwright, name=self.lease.job_name)
        environment={key:os.environ[key] for key in ('SystemRoot','WINDIR','LOCALAPPDATA','USERPROFILE','TEMP','TMP','PATH') if key in os.environ}
        self.context = self.playwright.chromium.launch_persistent_context(
            str(self.lease.profile), channel='msedge', headless=not self.headed,
            chromium_sandbox=True, env=environment, timeout=10000,
            downloads_path=str(self.lease.downloads),
            viewport={'width':1280,'height':800}, accept_downloads=False,
            service_workers='block', permissions=[])
        self.browser = self.context.browser
        self.context.set_default_timeout(2000)
        self.context.set_default_navigation_timeout(10000)
        def route(request_route):
            request = request_route.request
            if self.demo_html is not None:
                if request.url == self.task['url'] and request.method == 'GET':
                    request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=self.demo_html)
                else:
                    self.blocked_requests += 1
                    request_route.abort()
            elif self.allowed(request.url):
                # Playwright continue_ routes only the original request: a
                # server redirect can otherwise bypass our origin check.
                # This first backend rejects redirects rather than following
                # an unobserved chain under the initial permission.
                response = request_route.fetch(max_redirects=0,max_retries=0,timeout=10000)
                try:
                    if 300 <= response.status < 400:
                        self.blocked_requests += 1
                        request_route.abort()
                    else:
                        request_route.fulfill(response=response)
                finally:
                    response.dispose()
            else:
                self.blocked_requests += 1
                request_route.abort()
        self.context.route('**/*', route)
        self.context.route_web_socket('**/*', lambda socket: socket.close())
        self.context.on('page', lambda page: page.close() if self.page is not None and page != self.page else None)
        self.page = self.context.new_page()
        self.page.on('dialog', lambda dialog: dialog.dismiss())
        self.page.on('download', lambda download: download.cancel())
        self.page.goto(self.task['url'], wait_until='domcontentloaded')
        self._check_page()

    def _check_page(self):
        if self.page.is_closed() or not self.allowed(self.page.url):
            raise ComputerError('url_denied', 'Browser left the permitted task origin')

    def _snapshot(self, *, bind=False):
        self._check_page()
        targets = []
        new_handles = {}
        for target in self.task['targets']:
            locator = self.page.get_by_role(target['role'], name=target['name'], exact=True)
            state = {'id':target['id'],'role':target['role'],'name':target['name'],
                     'actions':target['actions'],'allowed_values':target['values'],'available':False}
            if locator.count() == 1 and locator.is_visible():
                handle = locator.element_handle()
                data = handle.evaluate("e => ({html:e.outerHTML,type:e.type||'',value:e.value??null,checked:e.checked??null})")
                if data['type'] not in ('password','file','hidden'):
                    state.update(available=locator.is_enabled(),value=data['value'],checked=data['checked'],signature=fingerprint(data))
                    new_handles[target['id']] = handle
                else:
                    handle.dispose()
            targets.append(state)
        snapshot = {'url':self.page.url,'text':self.page.locator('body').inner_text(timeout=2000)[:6000],'targets':targets}
        if bind:
            for handle in self.handles.values():
                handle.dispose()
            self.handles = new_handles
        else:
            for handle in new_handles.values():
                handle.dispose()
        return snapshot

    def observe(self):
        snapshot = self._snapshot(bind=True)
        return {'id':uuid.uuid4().hex,'digest':fingerprint(snapshot),**snapshot}

    def check_fresh(self, observation):
        if fingerprint(self._snapshot()) != observation['digest']:
            raise ComputerError('stale_observation', 'Page changed after observation; no action was dispatched')

    def act(self, action):
        self._check_page()
        handle = self.handles.get(action['target'])
        if handle is None or not handle.evaluate('e => e.isConnected'):
            raise ComputerError('stale_observation', 'Observed element no longer exists')
        if action['op'] == 'click':
            href = handle.evaluate("e => e.tagName === 'A' ? e.href : null")
            if href is not None and not self.allowed(href):
                raise ComputerError('url_denied', 'Link destination is outside the task origins')
            handle.click(timeout=2000)
        elif action['op'] == 'fill':
            handle.fill(action['value'],timeout=2000)
        elif action['op'] == 'select':
            handle.select_option(value=action['value'],timeout=2000)
        elif action['op'] == 'check':
            handle.set_checked(action['value'],timeout=2000)
        else:
            raise ComputerError('action_denied','Unknown browser action')
        self.page.wait_for_timeout(150)
        self._check_page()

    def succeeded(self):
        self._check_page()
        goal = self.task['success']
        nodes = self.page.get_by_role(goal['role'])
        return any(nodes.nth(i).is_visible() and nodes.nth(i).inner_text().strip() == goal['text'] for i in range(min(nodes.count(),30)))

    def screenshot(self):
        raw = self.page.screenshot(type='png',full_page=False,timeout=2000)
        if len(raw)>2*1024*1024:
            raise ComputerError('screenshot_limit','Screenshot exceeds limit')
        return raw

    def close(self):
        try:
            if self.browser:self.browser.close()
        finally:
            try:
                if self.playwright:self.playwright.stop()
            finally:
                try:
                    if self.job:self.job.close()
                finally:
                    if self.lease:self.cleanup=self.lease.close()

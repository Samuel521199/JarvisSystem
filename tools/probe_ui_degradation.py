"""Real Edge chat/refresh under optional-asset faults; isolated data, no cloud calls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'runtime/node-host'), str(ROOT/'tools')]
from tests.test_web import web
from jarvis_core import __version__
from jarvis_core.service import CoreService
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'status': 'running', 'cloud_calls': 0, 'cases': []}
    original = Path.read_bytes
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
            for label, faults in [('normal', set()), ('degraded', {'evolution.css', 'logo.js', 'preview.html'})]:
                with tempfile.TemporaryDirectory(prefix='jarvis-ui-fault-') as directory:
                    root = Path(directory); (root/'project').mkdir()
                    core = CoreService(root/'data'); core.initialize(root/'project')
                    def read(path):
                        if path.name in faults: raise FileNotFoundError('fault injection only')
                        return original(path)
                    with patch.object(Path, 'read_bytes', read):
                        server = web.create_server(core=core, chat=SyntheticChat(), port=0)
                    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
                    thread.start()
                    try:
                        for width in (1440, 390):
                            page = browser.new_page(viewport={'width': width, 'height': 1000})
                            errors=[]; page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto('http://127.0.0.1:' + str(server.server_address[1]))
                            expect(page.locator('#send')).to_be_enabled()
                            page.wait_for_load_state('networkidle')
                            expect(page.locator('html')).not_to_have_attribute('data-brand-cinema', '')
                            expect(page.locator('.asset-warning')).to_have_count(1 if faults else 0)
                            page.locator('#message').fill('基础降级回归测试')
                            page.locator('#send').click()
                            expect(page.locator('#send')).to_have_attribute('aria-label', '发送消息')
                            if page.locator('.message.assistant').count() != 1:
                                page.screenshot(path=str(args.output/'failure.png'), full_page=True)
                                report['failure_detail'] = {'page_errors': errors, 'messages': page.locator('#messages').inner_text(),
                                    'fixture_calls': server.chat.calls, 'state': page.evaluate('({busy,refreshing,coreReady,modelCatalog,note:document.getElementById("notice")?.textContent,input:document.getElementById("message").value})')}
                            expect(page.locator('.message.assistant')).to_have_count(1)
                            expect(page.locator('#conversation-status')).to_have_attribute('data-state', 'saved')
                            page.reload(); expect(page.locator('.message.assistant')).to_have_count(1)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                            assert page.locator('#send').bounding_box()['y'] < 1000
                            screenshot = args.output/f'{label}-{width}.png'
                            page.screenshot(path=str(screenshot), full_page=True)
                            assert not errors, errors
                            report['cases'].append({'label': label, 'width': width, 'status': 'passed',
                                'faults': sorted(faults), 'page_errors': errors, 'screenshot': str(screenshot)})
                            page.close()
                    finally:
                        server.shutdown(); server.server_close(); thread.join(2)
            browser.close()
        report['status'] = 'passed'
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__)
        raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__': main()

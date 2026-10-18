"""Real Edge/HTTP continuity flow with synthetic data and a fake model.

Explicit commands use actual stores. Ordinary replies capture the compiled
context. No user files, credentials or cloud requests are used by this probe.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('continuity_probe_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    checks, errors, calls = [], [], []
    def probe(config, provider, message, *args, **kwargs):
        calls.append({'provider': provider, 'message': message, 'history': kwargs['history'], 'instructions': kwargs['instructions']})
        return {'status': 'SUCCEEDED', 'text': '已读取本轮允许使用的资料。', 'provider': provider, 'model': config['providers'][provider]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-continuity-ui-') as directory:
        base = Path(directory); folder = base/'project'; folder.mkdir()
        core = CoreService(base/'data'); core.initialize(folder)
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex', automatic_fallback=False)
        path = base/'providers.json'; path.write_text(json.dumps(config), encoding='utf-8')
        chat = ChatService(core, path); server = web.create_server(core=core, chat=chat, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        try:
            with patch('jarvis_core.chat.gateway.probe', side_effect=probe), sync_playwright() as playwright:
                job = DriverJob(playwright)
                try:
                    browser = playwright.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port)); expect(page.locator('#send')).to_be_enabled()
                    def send(text, expected):
                        expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=10000)
                        before = page.locator('.message.assistant').count()
                        page.locator('#message').fill(text)
                        expect(page.locator('#message')).to_have_value(text)
                        expect(page.locator('#send')).to_be_enabled()
                        page.locator('#send').click()
                        expect(page.locator('.message.assistant')).to_have_count(before+1)
                        expect(page.locator('.message.assistant').last).to_contain_text(expected)
                        expect(page.locator('#send')).to_have_attribute('aria-label', '发送消息')
                        expect(page.locator('#conversation-status')).to_have_attribute('data-state', 'saved')
                    send('保存接续：旅行=已确定杭州_UI_PRIVATE｜比较住宿_UI_NEXT', '已保存接续')
                    assert not calls
                    original_url = page.url
                    record = chat.continuity.list()['records'][0]
                    assert record['document']['source']['conversation_id'] == original_url.split('#chat=')[1]
                    page.locator('#open-memory').click()
                    page.get_by_role('button', name='接续', exact=True).click()
                    expect(page.locator('.continuity-card')).to_have_count(1)
                    expect(page.locator('.continuity-card a')).to_have_attribute('href', '/#chat='+record['document']['source']['conversation_id'])
                    page.locator('.continuity-card input[value="vertex"]').check()
                    page.get_by_role('button', name='保存许可', exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('接续已更新')
                    page.locator('#memory-close').click(); page.locator('#clear').click()
                    send('继续话题：旅行', '已选择')
                    send('接着比较下一步', '已读取')
                    assert 'UI_PRIVATE' in calls[-1]['message'] and calls[-1]['history'] == []
                    assert 'owner_entered_note' in calls[-1]['message']
                    saved_url = page.url
                    page.reload(); expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=10000)
                    assert page.evaluate('Continuity.snapshot().length') == 1
                    send('请再接着说', '已读取')
                    assert calls[-1]['history'] and 'UI_PRIVATE' in calls[-1]['message']
                    checks.append('Source command archived before atomic checkpoint save; new chat resumes consented note; selection and dependency refs survive refresh')
                    send('更新接续：旅行=改为苏州_UI_CURRENT｜比较交通_UI_NEXT2', '已更新进展')
                    send('现在应该继续什么？', '已读取')
                    assert calls[-1]['history'] == [] and 'UI_CURRENT' in calls[-1]['message']
                    assert 'UI_PRIVATE' not in str(calls[-1])
                    page.locator('#open-memory').click(); page.get_by_role('button', name='接续', exact=True).click()
                    expect(page.locator('.continuity-card')).to_contain_text('苏州')
                    page.get_by_role('button', name='标记完成', exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('不代表后台执行')
                    expect(page.locator('.continuity-card')).to_contain_text('主人标记完成')
                    page.get_by_role('button', name='重新打开', exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('接续已更新')
                    page.screenshot(path=str(args.output/'continuity-desktop.png'), full_page=True)
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.output/'continuity-mobile.png'), full_page=True)
                    page.locator('.continuity-card input[value="vertex"]').uncheck()
                    page.get_by_role('button', name='保存许可', exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('接续已更新')
                    page.locator('#memory-close').click()
                    before=len(calls)
                    page.locator('#message').fill('继续');page.locator('#send').click()
                    expect(page.locator('.message.error').last).to_contain_text('所选接续')
                    assert len(calls)==before
                    # Keep old rows on screen while a fresh read is in flight:
                    # stale action buttons must be inert until that read settles.
                    held=[]
                    page.route('**/api/continuity',lambda route:held.append(route))
                    page.locator('#open-memory').click();page.get_by_role('button',name='接续',exact=True).click()
                    expect(page.get_by_role('button',name='忘记',exact=True)).to_be_disabled()
                    assert len(held)==1
                    held[0].continue_();page.unroute('**/api/continuity')
                    expect(page.get_by_role('button',name='忘记',exact=True)).to_be_enabled()
                    page.get_by_role('button',name='忘记',exact=True).click();page.get_by_role('button',name='确认忘记',exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('已忘记')
                    page.locator('#memory-close').click();page.reload();expect(page.locator('#send')).to_be_enabled()
                    send('聊点别的', '已读取')
                    assert 'UI_CURRENT' not in str(calls[-1]) and 'UI_PRIVATE' not in str(calls[-1])
                    assert calls[-1]['history']==[]
                    checks.append('Update/complete/reopen work; revoked provider stops before model; pending list read locks stale buttons; forget removes derived context after refresh')
                    page.locator('#conversation-status').click();page.locator('#conversation-temporary').click()
                    page.locator('#message').fill('保存接续：临时=不保存｜不执行');page.locator('#send').click()
                    expect(page.locator('.message.error')).to_contain_text('临时会话')
                    assert chat.continuity.list()['records']==[]
                    checks.append('Temporary writes refused; desktop and mobile panel fit; no background task or cloud calls used')
                    assert not errors, errors
                    browser.close()
                finally:
                    job.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)
    report = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'checks': checks, 'page_errors': errors, 'synthetic_model_calls': len(calls), 'real_model_calls': 0}
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()

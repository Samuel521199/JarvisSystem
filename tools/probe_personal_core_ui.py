"""Real Edge/HTTP personal-core flow with synthetic data and a fake model.

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
    spec = importlib.util.spec_from_file_location('personal_probe_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    checks, errors, calls = [], [], []
    def probe(config, provider, message, *args, **kwargs):
        calls.append({'provider': provider, 'message': message, 'history': kwargs['history'], 'instructions': kwargs['instructions']})
        return {'status': 'SUCCEEDED', 'text': '已读取本轮允许使用的资料。', 'provider': provider, 'model': config['providers'][provider]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-personal-ui-') as directory:
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
                    send('记住：测试饮品=无糖茶_UI_PRIVATE', '已记住')
                    send('设置交流风格：温暖', '已保存交流设置')
                    send('设置相处方式：伙伴', '已保存交流设置')
                    assert not calls
                    original_url = page.url
                    doc = server.conversations.get(original_url.split('#chat=')[1])['document']
                    assert all(row.get('personal_control') for row in doc['messages'])
                    page.reload(); expect(page.locator('#send')).to_be_enabled()
                    assert page.evaluate('history.length') == 0
                    checks.append('Explicit memory/persona commands commit without models; archived control turns stay out of prompts after reload')
                    send('你好，新的一天', '已读取')
                    assert 'UI_PRIVATE' not in calls[-1]['message'] and calls[-1]['history'] == []
                    assert 'warm, considerate' in calls[-1]['instructions'] and 'companion tone' in calls[-1]['instructions']
                    page.locator('#open-memory').click(); expect(page.locator('.memory-card')).to_have_count(1)
                    page.get_by_role('button', name='修改', exact=True).click()
                    page.locator('#memory-providers input[value="vertex"]').check()
                    page.locator('#memory-save').click(); expect(page.locator('#memory-status')).to_contain_text('已存入')
                    page.locator('#memory-close').click()
                    page.locator('#clear').click()
                    send('我喜欢什么饮品？', '已读取')
                    assert 'UI_PRIVATE' in calls[-1]['message'] and calls[-1]['history'] == []
                    assert 'companion tone' in calls[-1]['instructions']
                    checks.append('New chat receives the persistent profile and explicitly allowed facts; local-only facts were not sent before consent')
                    send('修改记忆：测试饮品=黑咖啡_UI_CURRENT', '已纠正')
                    send('请按现在的偏好回答', '已读取')
                    assert 'UI_CURRENT' in calls[-1]['message'] and 'UI_PRIVATE' not in str(calls[-1])
                    send('查看记忆', '黑咖啡_UI_CURRENT')
                    send('忘记：测试饮品', '已忘记')
                    page.reload(); expect(page.locator('#send')).to_be_enabled()
                    send('现在还有什么偏好？', '已读取')
                    assert 'UI_CURRENT' not in str(calls[-1]) and 'UI_PRIVATE' not in str(calls[-1])
                    checks.append('Correction/forget invalidate dependent turns; local memory query text never returns through archived history')
                    send('撤销交流设置', '温暖 · 助手')
                    page.screenshot(path=str(args.output/'personal-chat.png'), full_page=True)
                    page.locator('#open-memory').click()
                    page.locator('#memory-facts details summary').click()
                    page.screenshot(path=str(args.output/'personal-help-desktop.png'), full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.output/'personal-help-mobile.png'), full_page=True)
                    page.locator('#memory-close').click()
                    # A lost model catalog must not disable local personal commands.
                    page.evaluate('modelCatalog=[];setControls()')
                    send('查看交流设置', '温暖')
                    page.locator('#conversation-status').click(); page.locator('#conversation-temporary').click()
                    page.locator('#message').fill('记住：临时内容=不应保存'); page.locator('#send').click()
                    expect(page.locator('.message.error')).to_contain_text('临时会话')
                    assert chat.memory.list()['facts'] == []
                    expect(page.locator('#conversation-status')).to_have_attribute('data-state', 'temporary')
                    checks.append('Temporary chat refuses explicit memory writes without invoking a model')
                    checks.append('Commands remain usable without a model catalog; memory help fits desktop and 390px mobile')
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

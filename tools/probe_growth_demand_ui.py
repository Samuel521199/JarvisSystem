"""Demand-driven growth through real Edge, HTTP, ledger and LPAC; synthetic models."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'tools'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution import recipes
from test_evolution import Provider
from probe_conversation_tasks_ui import Chat
from probe_sample_tasks_ui import Planner
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('growth_ui_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    checks, errors = [], []
    provider, planner, chat = Provider(), Planner(), Chat()
    provider.release = threading.Event()
    with tempfile.TemporaryDirectory(prefix='jarvis-growth-ui-') as temporary:
        base = Path(temporary); source = base/'sample'; source.mkdir()
        (source/'a.txt').write_bytes(b'abc'); (source/'中文.md').write_bytes(b'x')
        core = CoreService(base/'data'); core.initialize(source)
        server = web.create_server(core=core, chat=chat, port=0)
        server.evolution.close()
        server.evolution = EvolutionManager(core, provider=provider, monitor=False)
        server.computer.sample.chat_factory = lambda *a, **kw: planner
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        try:
            with sync_playwright() as p:
                driver = DriverJob(p)
                try:
                    browser = p.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width':1440, 'height':1050})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    expect(page.locator('#send')).to_be_enabled()
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    cid = page.evaluate('Workspace.currentConversation().id')
                    def send(text):
                        page.locator('#message').fill(text)
                        expect(page.locator('#message')).to_have_value(text)
                        page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    send('/任务 列出样例目录文件并保存报告')
                    expect(page.locator('#conversation-task-list')).to_contain_text('已核验：2 个文件', timeout=15000)
                    send('/改进 把最近的目录报告导出为 TSV')
                    expect(page.locator('#growth-dialog')).to_be_visible()
                    expect(page.locator('.growth-card')).to_have_count(1)
                    expect(page.locator('.growth-card')).to_contain_text('待开始')
                    assert len(provider.calls) == chat.calls == 0
                    card = page.locator('.growth-card'); job_id = card.get_attribute('data-growth-id')
                    page.get_by_role('button', name='补齐能力并导出', exact=True).click()
                    assert provider.entered.wait(5)
                    page.locator('#growth-close').click()
                    send('请陪我聊聊今天的安排')
                    expect(page.locator('#messages')).to_contain_text('# 项目笔记')
                    assert chat.calls == 1 and chat.requests[-1]['history'] == []
                    assert server.evolution.busy
                    provider.release.set()
                    send('/成长进度')
                    expect(page.locator('#growth-dialog')).to_be_visible()
                    expect(page.locator('.growth-card')).to_contain_text('已完成', timeout=30000)
                    job = server.evolution.store.job(job_id)
                    assert job['result']['benefit']['verified_on_user_input']
                    assert job['attempts'][0]['validation']['isolation']['backend'] != 'test-double'
                    assert len(provider.calls) == 1
                    with page.expect_download() as download:
                        page.get_by_role('button', name='下载已核验结果', exact=True).click()
                    saved = args.output/'verified-output.tsv'; download.value.save_as(str(saved))
                    assert saved.read_text(encoding='utf-8') == recipes.expected(job['request']['input'])
                    checks.append('Chat demand -> model-free proposal -> real LPAC evaluation/activation -> exact export of two source files; chat continues while generator waits')
                    page.locator('.growth-card details summary').click()
                    page.screenshot(path=str(args.output/'desktop.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(args.output/'mobile.png'))
                    page.locator('#growth-close').click(); page.reload()
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    expect(page.locator('.growth-link')).to_have_count(1)
                    page.locator('.growth-link').click()
                    expect(page.locator('.growth-card')).to_contain_text('已完成')
                    page.locator('#growth-close').click()
                    send('/改进 导出 CSV')
                    expect(page.get_by_role('button', name='使用现有能力导出', exact=True)).to_be_visible()
                    page.get_by_role('button', name='使用现有能力导出', exact=True).click()
                    expect(page.locator('.growth-card').first).to_contain_text('已完成', timeout=20000)
                    assert len(provider.calls) == 1
                    page.locator('#growth-close').click()
                    checks.append('Reload restores source-bound receipt; CSV reuses v2 capability with no additional coding call; desktop/mobile no overflow')
                    # Lose one accepted preview response, recover via persisted request ID.
                    def lost(route):
                        if route.request.method == 'POST': route.fetch(); route.abort('failed')
                        else: route.continue_()
                    page.route('**/api/conversation-growth/'+cid, lost)
                    send('/改进 导出 Markdown')
                    expect(page.locator('#message')).to_have_value('/改进 导出 Markdown')
                    expect(page.locator('.growth-link')).to_have_count(3)
                    page.unroute('**/api/conversation-growth/'+cid, lost)
                    page.locator('.growth-link').last.click()
                    expect(page.locator('.growth-card')).to_have_count(3)
                    expect(page.locator('.growth-card').first).to_contain_text('待开始')
                    page.locator('.growth-card').first.get_by_role('button', name='取消本次').click()
                    expect(page.locator('.growth-card').first).to_contain_text('已取消')
                    assert len(provider.calls) == 1
                    page.locator('#growth-close').click(); page.locator('#message').fill('')
                    page.set_viewport_size({'width':1440,'height':1050})
                    page.locator('#clear').click(); send('/成长进度')
                    expect(page.locator('#growth-list')).to_contain_text('尚无改进单')
                    assert chat.calls == 1
                    page.locator('#growth-close').click()
                    page.locator('#conversation-status').click(); page.locator('#conversation-temporary').click()
                    send('/改进 导出 CSV')
                    expect(page.locator('#toast')).to_contain_text('临时会话不建立持久改进单')
                    assert not errors, errors
                    checks.append('Lost preview response recovered by original request ID without another job; proposal cancelled without model; new conversation isolated; temporary chat blocked')
                    browser.close()
                finally: driver.close()
        finally:
            provider.release.set(); server.shutdown(); server.server_close(); thread.join(3)
    report = {'version':__version__, 'captured_at':datetime.now(timezone.utc).isoformat(), 'status':'passed',
        'checks':checks, 'page_errors':errors, 'coding_calls':len(provider.calls), 'paid_calls':0,
        'screenshots':[str(args.output/name) for name in ('desktop.png','mobile.png')],
        'scope':'Real Edge/HTTP/archive/LPAC/ledger/download; source planner, chat and coding replies synthetic.'}
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()

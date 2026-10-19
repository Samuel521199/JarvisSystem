"""Synthetic model, real browser/HTTP/LPAC: saved improvement through delivery."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use'), str(ROOT/'apps/web')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect
import server as web


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependency', action='store_true', help='Verify the optional bundled JSON-query recipe')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    report = {'version': __version__, 'status': 'running', 'paid_model_calls': 0, 'checks': []}
    def save(): (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save(); errors = []; entered = threading.Event(); release = threading.Event(); calls = []
    candidate = ('import queries\nimport json\ndef transform(data):\n    return json.dumps(queries.total(data))\n'
                 if args.dependency else 'def transform(data):\n    return str(sum(data))\n')
    with tempfile.TemporaryDirectory(prefix='jarvis-demand-ui-') as tmp:
        root = Path(tmp); project = root/'project'; project.mkdir()
        original = b'\xef\xbb\xbfdef transform(data):\n    return "wrong"\n'
        source = project/'calc.py'; source.write_bytes(original)
        if args.dependency:
            (project/'queries.py').write_text('def total(data):\n    return 0\n', encoding='utf-8')
        originals = {p.name: p.read_bytes() for p in project.glob('*.py')}
        core = CoreService(root/'data'); core.initialize(project)
        chat = SyntheticChat(); server = web.create_server(core=core, chat=chat, port=0)
        def generate(prompt, instructions, guard):
            calls.append(prompt); entered.set()
            while not release.wait(.05): guard()
            content = {'files': {'calc.py': candidate, 'queries.py': 'import jmespath\ndef total(data):\n    return jmespath.search("sum(@)", data)\n'}} if args.dependency else {'code': candidate}
            return {'status': 'SUCCEEDED', 'text': json.dumps({**content, 'notes': 'synthetic UI fixture'})}
        server.computer.skills.coding_generate = generate
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        origin = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as pw:
                owner = DriverJob(pw)
                try:
                    browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width': 1480, 'height': 1040})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(origin); expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project').click(); page.locator('#folder-path').fill(str(project)); page.locator('#project-open').click()
                    expect(page.locator('#context-project')).to_contain_text(str(project))
                    def send(text):
                        page.locator('#message').fill(text); page.locator('#composer').evaluate('element=>element.requestSubmit()')
                    send('/改进 修复求和工具，空表返回字符串0')
                    expect(page.locator('#skill-coding-demand')).to_be_checked()
                    page.locator('#skill-paths').fill('calc.py\nqueries.py' if args.dependency else 'calc.py')
                    if args.dependency:
                        page.locator('#skill-coding-recipe').select_option('python-jmespath-v1')
                        expect(page.locator('#skill-controls')).to_contain_text('不安装到本机环境')
                    page.locator('#skill-coding-cases').fill(json.dumps([{'input':[2,4], 'expected':'6'}, {'input':[], 'expected':'0'}]))
                    page.locator('#skill-coding-heldout').fill(json.dumps([{'input':[9], 'expected':'9'}, {'input':[-2,1], 'expected':'-1'}]))
                    page.locator('#model-trigger').click(); page.locator('#model-search').fill('离线验证模型')
                    page.locator('#model-options button').filter(has_text='离线验证模型').first.click()
                    page.locator('#composer').evaluate('element=>element.requestSubmit()')
                    expect(page.locator('#growth-dialog')).to_be_visible(timeout=15000)
                    card = page.locator('.growth-card'); expect(card).to_contain_text('待开始')
                    assert not calls
                    job_id = card.get_attribute('data-growth-id'); cid = page.evaluate('Workspace.currentConversation().id')
                    report['checks'].append('natural improvement opens explicit coding draft; proposal makes zero model calls')
                    page.screenshot(path=str(args.output/'proposal.png'))
                    card.get_by_role('button', name='开始编码与独立验收', exact=True).click()
                    assert entered.wait(20)
                    page.locator('#growth-close').click(); page.locator('#composer-mode').select_option('chat')
                    send('你好，继续聊聊今天')
                    expect(page.locator('#messages')).to_contain_text('文件夹就是项目的根目录', timeout=15000)
                    report['checks'].append('chat responds while coding waits in background')
                    release.set()
                    send('/成长进度'); card = page.locator('[data-growth-id="'+job_id+'"]')
                    expect(card).to_contain_text('候选与产物已通过 4 条案例', timeout=90000)
                    assert source.read_bytes() == original
                    assert all((project/p).read_bytes() == raw for p, raw in originals.items())
                    page.screenshot(path=str(args.output/'verified.png'))
                    page.reload(); expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    send('/成长进度'); card = page.locator('[data-growth-id="'+job_id+'"]')
                    expect(card).to_contain_text('候选与产物已通过 4 条案例', timeout=15000)
                    card.get_by_role('button', name='查看差异、验收与应用', exact=True).click()
                    expect(page.locator('#coding-result .coding-diff')).to_contain_text('calc.py')
                    if args.dependency:
                        import zipfile
                        with page.expect_download() as downloaded:
                            page.get_by_role('button', name='下载可运行工具包', exact=True).click()
                        downloaded.value.save_as(str(args.output/'download.pyz'))
                        with zipfile.ZipFile(args.output/'download.pyz') as archive:
                            assert '_vendor/jmespath-1.1.0.dist-info/LICENSE' in archive.namelist()
                        report['checks'].append('browser download saved dependency PYZ with bundled license')
                        page.get_by_text('离线使用与重建', exact=True).click()
                        expect(page.locator('#coding-result')).to_contain_text('无需安装')
                    page.get_by_role('button', name='应用到原文件', exact=True).click()
                    expect(page.locator('#coding-result [role=status]')).to_contain_text('候选文件组已应用')
                    assert source.read_bytes() != original
                    page.get_by_role('button', name='恢复本次原文件', exact=True).click()
                    expect(page.locator('#coding-result [role=status]')).to_contain_text('原文件已恢复')
                    assert source.read_bytes() == original
                    assert all((project/p).read_bytes() == raw for p, raw in originals.items())
                    page.screenshot(path=str(args.output/'result-panel.png'))
                    report['checks'].append('page reload restores the same receipt; right panel apply/rollback restores exact BOM bytes')
                    page.get_by_role('button', name='关闭编程结果', exact=True).click()
                    send('/成长进度'); expect(page.locator('#growth-dialog')).to_be_visible(timeout=15000)
                    expect(page.locator('[data-growth-id="'+job_id+'"]')).to_contain_text('候选与产物已通过 4 条案例')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(args.output/'narrow.png'))
                    assert len(calls) == 1 and not errors
                    report.update(status='passed', model_calls=len(calls), conversation_id=cid, job_id=job_id, page_errors=errors)
                    save(); browser.close()
                finally: owner.close()
        except Exception as exc:
            report.update(status='failed', error=str(exc), page_errors=errors); save(); raise
        finally:
            release.set(); server.shutdown(); server.server_close(); thread.join(5)
    print(json.dumps({'status':report['status'], 'report':str(args.output/'report.json')}))


if __name__ == '__main__': main()

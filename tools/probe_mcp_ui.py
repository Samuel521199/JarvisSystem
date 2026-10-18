"""Real Edge management UI; isolated data, no MCP or model calls."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_core.mcp_catalog import McpManager
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect


def main():
    spec = importlib.util.spec_from_file_location('mcp_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    output = ROOT/'artifacts/mcp'; output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='jarvis-mcp-ui-') as tmp:
        root = Path(tmp); project = root/'project'; project.mkdir()
        core = CoreService(root/'data'); core.initialize(project)
        chat = SyntheticChat(); server = web.create_server(core=core, chat=chat, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_address[1])
        try:
            with sync_playwright() as p:
                job = DriverJob(p)
                try:
                    browser = p.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1050}); page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(origin + '/settings#mcp')
                    expect(page.locator('.mcp-card')).to_have_count(10)
                    expect(page.locator('#mcp-status')).to_contain_text('0 项可调用')
                    page.screenshot(path=str(output/'mcp-desktop.png'), full_page=True)
                    page.locator('#mcp-search').fill('文档'); expect(page.locator('.mcp-card')).to_have_count(1)
                    page.locator('#mcp-search').fill(''); page.get_by_role('button', name='三维与创作', exact=True).click()
                    expect(page.locator('.mcp-card')).to_have_count(1)
                    page.get_by_role('button', name='管理Blender 三维创作', exact=True).focus(); page.keyboard.press('Enter')
                    expect(page.locator('#mcp-detail')).to_be_visible(); expect(page.locator('#mcp-detail')).to_contain_text('社区维护')
                    expect(page.locator('#mcp-detail')).to_contain_text('专业 CAD')
                    page.screenshot(path=str(output/'mcp-detail.png')); page.keyboard.press('Escape')
                    checks.append('10 curated cards, search/categories, keyboard details, source and CAD boundaries')
                    page.get_by_role('button', name='全部工具', exact=True).click()
                    page.get_by_role('button', name='管理Context7 文档助手', exact=True).click()
                    page.locator('#mcp-policy-mode').select_option('manual'); page.get_by_role('button', name='保存规则', exact=True).click()
                    expect(page.locator('#mcp-detail')).not_to_be_visible()
                    page.reload(); expect(page.locator('.mcp-card')).to_have_count(10)
                    page.get_by_role('button', name='管理Context7 文档助手', exact=True).click()
                    expect(page.locator('#mcp-policy-mode')).to_have_value('manual')
                    page.get_by_role('button', name='填写连接配置', exact=True).click()
                    expect(page.locator('#mcp-url')).to_have_value('https://mcp.context7.com/mcp')
                    page.get_by_role('button', name='添加配置', exact=True).click()
                    expect(page.locator('#mcp-editor')).not_to_be_visible()
                    expect(page.locator('[data-mcp-id="context7"]')).to_contain_text('已配置 · 待接入')
                    page.locator('#mcp-filter').select_option('registered'); expect(page.locator('.mcp-card')).to_have_count(1)
                    page.get_by_role('button', name='管理Context7 文档助手', exact=True).click()
                    page.get_by_role('button', name='检查格式', exact=True).click()
                    expect(page.locator('#mcp-detail')).to_contain_text('尚未连接服务器')
                    page.keyboard.press('Escape')
                    checks.append('policy survives reload; template -> persisted registration -> grouped card -> explicit format-only check')
                    page.locator('#mcp-filter').select_option(''); page.locator('#mcp-add').click()
                    page.locator('#mcp-extension-name').fill('<img src=x onerror=alert(1)>')
                    page.locator('#mcp-transport').select_option('streamable-http'); page.locator('#mcp-url').fill('https://example.com/mcp')
                    page.get_by_role('button', name='添加配置', exact=True).click(); expect(page.locator('#mcp-editor')).not_to_be_visible()
                    expect(page.locator('.mcp-card')).to_have_count(11)
                    assert page.locator('.mcp-card img').count() == 0
                    page.get_by_role('button', name='自定义连接', exact=True).click(); expect(page.locator('.mcp-card')).to_have_count(1)
                    page.locator('.mcp-card .skill-card-open').click(); page.get_by_role('button', name='移除配置', exact=True).click()
                    expect(page.locator('.mcp-card')).to_have_count(0); page.keyboard.press('Escape')
                    page.get_by_role('button', name='全部工具', exact=True).click()
                    page.set_viewport_size({'width': 390, 'height': 844}); expect(page.locator('.mcp-card')).to_have_count(10)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/'mcp-mobile.png'), full_page=True)
                    checks.append('custom entry rendered as text, removal affects registration only, mobile has no overflow')
                    page.goto(origin + '/settings#skill'); expect(page.locator('.skill-card')).to_have_count(10)
                    page.goto(origin + '/settings#mcp'); expect(page.locator('.mcp-card')).to_have_count(10)
                    assert not errors, errors
                    assert chat.calls == 0
                    assert not any(x['callable'] for x in McpManager(core).snapshot()['entries'])
                    checks.append('existing skill menu preserved; no JavaScript errors, model calls or ready-state inflation')
                    browser.close()
                finally: job.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(3)
    report = {'status': 'passed', 'checks': checks, 'page_errors': errors, 'paid_model_calls': 0, 'mcp_calls': 0, 'scope': 'isolated real Edge management UI, not MCP protocol or tool usability'}
    (ROOT/'evals/reports/mcp-ui.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()

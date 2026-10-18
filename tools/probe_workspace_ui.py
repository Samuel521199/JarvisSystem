"""Real Edge and filesystem integration; synthetic model and picker, no cloud calls."""
import importlib.util
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


class SyntheticChat:
    calls = 0
    failure = False
    incomplete = False
    hook = None
    text = '# 项目笔记\n\n文件夹就是项目的根目录。\n'

    def models(self):
        return {'default_provider': 'local', 'providers': [{'provider': 'local'}],
                'models': [{'provider': 'local', 'model': 'offline-fixture', 'label': '离线验证模型',
                            'reasoning_levels': [], 'last_probe_status': 'NOT_TESTED'}]}

    def reply(self, message, **kwargs):
        self.calls += 1
        if self.hook:
            self.hook()
        if self.failure:
            return {'status': 'FAILED', 'user_message': '离线测试的模型失败', 'provider': 'local'}
        return {'status': 'SUCCEEDED', 'text': self.text,
                'provider': 'local', 'model': 'offline-fixture', 'usage': {}, 'notice': [],
                'output_incomplete': self.incomplete}


def main():
    spec = importlib.util.spec_from_file_location('workspace_ui_probe', ROOT/'apps/web/server.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    output = Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/project-workspace'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-workspace-ui-') as directory:
        base = Path(directory)
        first, second = base/'项目一', base/'项目二'
        first.mkdir();second.mkdir()
        core = CoreService(base/'data');core.initialize(first)
        chat = SyntheticChat()
        server = module.create_server(core=core, chat=chat, port=0)
        server.workspace.picker = lambda: str(second)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True);thread.start()
        errors, checks = [], []
        try:
            with sync_playwright() as playwright:
                job = DriverJob(playwright)
                try:
                    browser = playwright.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1050})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    # Expected HTTP 400 path validation is checked below, not a JS error.
                    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
                    page.goto('http://127.0.0.1:'+str(server.server_address[1]))
                    expect(page.locator('#send')).to_be_enabled()
                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(first));page.locator('#project-open').click()
                    expect(page.locator('#context-project')).to_contain_text(str(first))
                    assert not (first/'.git').exists()
                    checks.append('open non-Git folder through real HTTP; no repository initialization')

                    def open_file_options():
                        if not page.locator("#file-options").evaluate("el=>el.open"):page.locator("#file-options-label").click()

                    def send(text):
                        if page.locator("#file-options").evaluate("el=>el.open"):page.locator("#file-options-label").click()
                        page.locator('#message').fill(text);page.locator('#send').click()
                        expect(page.locator('#send')).to_have_attribute('aria-label', '发送消息')

                    open_file_options();page.locator('#file-mode').check();send('生成一份项目笔记')
                    expect(page.locator('.file-receipt').last).to_contain_text('已保存')
                    defaults = list(first.glob('回答-*.md'));assert len(defaults) == 1
                    assert defaults[0].read_text(encoding='utf-8') == '# 项目笔记\n\n文件夹就是项目的根目录。\n'
                    assert chat.calls == 1
                    checks.append('generated text defaults to project root and bytes match receipt')

                    page.locator('#clear').click();expect(page.locator('#context-project')).to_contain_text(str(first))
                    open_file_options();page.locator('#file-mode').check();open_file_options();page.locator('#output-path').fill('notes/嵌套.md');send('写嵌套文件')
                    expect(page.locator('.file-receipt').last).to_contain_text('已保存')
                    assert (first/'notes/嵌套.md').is_file()
                    open_file_options();page.locator('#output-path').fill(str(second/'explicit.md'));send('写明确的其他位置')
                    expect(page.locator('.file-receipt').last).to_contain_text(str(second/'explicit.md'))
                    assert (second/'explicit.md').is_file()
                    checks.append('new chat inherits project; nested relative and explicit absolute destinations')

                    before = chat.calls;open_file_options();page.locator('#output-path').fill('notes/嵌套.md');send('不能覆盖原文件')
                    expect(page.locator('#toast')).to_contain_text('目标已存在')
                    assert page.locator('#message').input_value() == '不能覆盖原文件' and chat.calls == before
                    checks.append('existing file blocked before model request; draft and original file preserved')

                    open_file_options();page.locator('#file-mode').uncheck();send('普通回答稍后保存')
                    page.locator('#message').fill('待办草稿')
                    page.locator('#open-project').click();page.locator('#project-pick').click()
                    expect(page.locator('#context-project')).to_contain_text(str(second))
                    page.locator('.session-row:not(#current-chat)').first.click()
                    expect(page.locator('#context-project')).to_contain_text(str(first))
                    assert page.locator('#message').input_value() == '待办草稿'
                    page.locator('.answer-menu summary').last.click();page.get_by_role('button', name='导出为文件…', exact=True).last.click()
                    page.locator('#save-path').fill('manual.md');page.locator('#save-confirm').click()
                    expect(page.locator('#save-dialog')).not_to_be_visible()
                    assert (first/'manual.md').is_file() and not (second/'manual.md').exists()
                    checks.append('picker API selection, switch and restore chat/draft, manual save stays with original project')

                    chat.failure = True
                    open_file_options();page.locator('#file-mode').check();open_file_options();page.locator('#output-path').fill('failed-model.md');send('测试失败保留')
                    expect(page.locator('.message.error').last).to_contain_text('离线测试的模型失败')
                    assert not (first/'failed-model.md').exists() and page.locator('#message').input_value() == '测试失败保留'
                    chat.failure = False
                    checks.append('model failure keeps draft and creates no output file')

                    chat.incomplete = True
                    open_file_options();page.locator('#output-path').fill('incomplete.md');send('测试截断回答')
                    expect(page.locator('.message.incomplete').last).to_contain_text('回答未完整结束')
                    assert not (first/'incomplete.md').exists()
                    chat.incomplete = False
                    checks.append('truncated response remains visible with persistent warning and is never auto-saved')

                    chat.hook = lambda: (first/'raced.md').write_text('keep original', encoding='utf-8')
                    open_file_options();page.locator('#output-path').fill('raced.md');send('测试保存失败后另存')
                    expect(page.locator('.file-receipt').last).to_contain_text('文件未保存')
                    chat.hook = None
                    assert (first/'raced.md').read_text() == 'keep original'
                    page.locator('.answer-menu summary').last.click();page.get_by_role('button', name='检查并重试保存…').click()
                    expect(page.locator('#save-path')).to_be_disabled()
                    page.locator('#save-new').click();page.locator('#save-path').fill('另存.md');page.locator('#save-confirm').click()
                    expect(page.locator('#save-dialog')).not_to_be_visible()
                    assert (first/'另存.md').is_file() and (first/'raced.md').read_text() == 'keep original'
                    checks.append('competing file created during generation is not overwritten; response preserved for explicit Save As')

                    chat.text = '```python\nprint("text only")\n```'
                    open_file_options();page.locator('#output-path').fill('sample.py');send('生成代码文件')
                    expect(page.locator('.file-receipt').last).to_contain_text('已保存')
                    assert (first/'sample.py').read_text() == 'print("text only")\n'
                    chat.text = '```python\nfirst()\n```\n说明文字\n```python\nsecond()\n```'
                    open_file_options();page.locator('#output-path').fill('examples.md');send('保存包含多段代码的文档')
                    expect(page.locator('.file-receipt').last).to_contain_text('已保存')
                    assert (first/'examples.md').read_text(encoding='utf-8') == chat.text
                    checks.append('single enclosing code fence removed; multi-block document preserved; saved code never executed')

                    page.locator('#clear').click();page.locator('#message').fill('为这个项目写一份说明文档')
                    open_file_options();page.locator('#file-mode').check();open_file_options();page.locator('#output-path').fill('项目说明.md')
                    page.screenshot(path=str(output/'desktop.png'), full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output/'mobile.png'), full_page=True)
                    page.keyboard.press('Escape');page.locator('#context-project').click()
                    assert page.locator('#project-dialog').is_visible()
                    page.screenshot(path=str(output/'folder-dialog-mobile.png'), full_page=True)
                    page.locator('[data-close-dialog="project-dialog"]').click()
                    page.reload()
                    expect(page.locator('#context-project')).to_contain_text(str(first))
                    expect(page.locator('#message')).to_have_value('')
                    page.locator('#show-exports').click()
                    expect(page.locator('#export-list')).to_contain_text(str(first/'manual.md'))
                    assert not errors, errors
                    checks.append('390px responsive layout, folder dialog, refresh retains project/receipts and archived chat text but not unsent drafts; no JS errors')
                    browser.close()
                finally:
                    job.close()
            result = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
                      'scope': 'temporary core, real Edge/HTTP/filesystem, synthetic model and injected picker; no paid requests or native picker interaction',
                      'checks': checks, 'model_fixture_calls': chat.calls, 'errors': errors,
                      'screenshots': ['desktop.png', 'mobile.png', 'folder-dialog-mobile.png']}
            (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False))
        finally:
            server.shutdown();server.server_close();thread.join(5)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()

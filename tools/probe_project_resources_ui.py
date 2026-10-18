"""Real Edge/HTTP/filesystem acceptance in temporary projects; no model billing."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from tools.probe_workspace_ui import SyntheticChat
from playwright.sync_api import sync_playwright, expect


def main():
    output=Path('H:/JarvisData/research/project-resources-ui');output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('resources_ui_web',ROOT/'apps/web/server.py')
    web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
    errors=[];checks=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-resources-ui-') as directory:
        base=Path(directory);folder=base/'星核项目';folder.mkdir();(folder/'src').mkdir()
        source=folder/'src'/'main.py';source.write_bytes(b'\xef\xbb\xbfprint("Hello Jarvis")\r\n')
        (folder/'README.md').write_text('# 星核项目\n\n项目资料可直接查看，不要求登记 README。',encoding='utf-8')
        (folder/'.env').write_text('SECRET');(folder/'node_modules').mkdir();(folder/'image.png').write_bytes(b'png')
        skill=base/'my-skill';skill.mkdir();skill_source=skill/'SKILL.md';skill_source.write_text('---\nname: my-skill\ndescription: Test skill\n---\n\n# 示例技能\n仅用于验证管理入口。\n<script>plain text</script>',encoding='utf-8')
        core=CoreService(base/'data');core.initialize(folder);chat=SyntheticChat()
        server=web.create_server(core=core,chat=chat,port=0)
        threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True).start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with sync_playwright() as playwright:
                job=DriverJob(playwright)
                try:
                    browser=playwright.chromium.launch(channel='msedge',headless=True,chromium_sandbox=True)
                    context=browser.new_context(viewport={'width':1440,'height':1000},color_scheme='dark')
                    context.on('page',lambda p:p.on('pageerror',lambda e:errors.append(str(e))))
                    page=context.new_page();page.goto(origin);expect(page.locator('#send')).to_be_enabled()
                    page.locator('#open-project').click();page.locator('#folder-path').fill(str(folder));page.locator('#project-open').click()
                    expect(page.locator('#explorer-panel')).to_be_visible();expect(page.locator('#explorer-tree')).to_contain_text('README.md')
                    expect(page.locator('#explorer-tree')).not_to_contain_text('node_modules');expect(page.locator('#explorer-tree')).not_to_contain_text('.env')
                    page.locator('#explorer-tree summary').filter(has_text='src').click();page.get_by_role('button',name='main.py',exact=True).click()
                    expect(page.locator('#explorer-text')).to_have_value('print("Hello Jarvis")\n')
                    page.locator('#explorer-text').fill('print("edited")\n');page.keyboard.press('Control+s');expect(page.locator('#explorer-status')).to_contain_text('已保存')
                    assert source.read_bytes()==b'\xef\xbb\xbfprint("edited")\r\n'
                    checks.append('Open folder automatically shows lazy file tree; code read/edit/save preserves UTF-8 BOM and CRLF; excluded paths hidden')
                    page.locator('#explorer-text').fill('print("draft")\n');source.write_text('external edit',encoding='utf-8');page.locator('#explorer-save').click()
                    expect(page.locator('#explorer-status')).to_contain_text('已经变化');expect(page.locator('#explorer-text')).to_have_value('print("draft")\n');assert source.read_text()=='external edit'
                    page.once('dialog',lambda d:d.accept());page.locator('#explorer-reload').click();expect(page.locator('#explorer-text')).to_have_value('external edit')
                    checks.append('External editor change yields conflict, preserves disk and draft, explicit reload uses current content')
                    page.locator('#explorer-directory').click();page.locator('#explorer-new').click();page.locator('#explorer-new-path').fill('src/new.py');page.get_by_role('button',name='开始编辑',exact=True).click()
                    page.locator('#explorer-text').fill('# 新脚本\nprint(42)\n');page.locator('#explorer-save').click();expect(page.locator('#explorer-status')).to_contain_text('已保存')
                    assert (folder/'src/new.py').read_text(encoding='utf-8')=='# 新脚本\nprint(42)\n'
                    page.locator('#explorer-directory').click();page.locator('.explorer-options summary').click();page.locator('#explorer-engineering').click();page.locator('#engineering-exclude').fill('logs\n*.log');page.locator('#engineering-save').click();expect(page.locator('#engineering-status')).to_contain_text('工程已保存');page.locator('#engineering-close').click()
                    engineering=folder/'project.jarvis-workspace';doc=json.loads(engineering.read_text(encoding='utf-8'))
                    assert doc['folders']==[{'path':'.'}] and doc['view']['active_file']=='src/new.py' and 'content' not in doc
                    page.reload();expect(page.locator('#send')).to_be_enabled();page.locator('#open-project').click();page.locator('#folder-path').fill(str(engineering));page.locator('#project-open').click()
                    expect(page.locator('#explorer-panel')).to_be_visible();expect(page.locator('#explorer-text')).to_have_value('# 新脚本\nprint(42)\n')
                    expect(page.locator('#explorer-tabs [role=tab]')).to_have_count(2)
                    checks.append('New script creation and portable engineering file round trip restore tabs, active file and excludes after page reload')
                    page.screenshot(path=str(output/'explorer-dark.png'),full_page=True)
                    page.locator('#explorer-chat').click();page.locator('#message').fill('你好');page.locator('#send').click();expect(page.locator('#conversation-status')).to_have_attribute('data-state','saved')
                    page.locator('#open-explorer').click();expect(page.locator('#explorer-text')).to_have_value('# 新脚本\nprint(42)\n')
                    checks.append('Resource/chat switching preserves editor and conversation; file browsing makes zero model calls')
                    settings=context.new_page();settings.goto(origin+'/settings#mcp');expect(settings.locator('#mcp-view')).to_be_visible()
                    settings.locator('#mcp-extension-name').fill('本地工具服务');settings.locator('#mcp-command').fill('not-installed-test-program');settings.locator('#mcp-args').fill('["server.py"]');settings.locator('#mcp-extension-submit').click()
                    expect(settings.locator('#mcp-extension-status')).to_contain_text('已保存到本机');expect(settings.locator('#mcp-extension-list .extension-card')).to_have_count(1)
                    settings.locator('#mcp-extension-list').get_by_role('button',name='检查',exact=True).click();expect(settings.locator('#mcp-extension-status')).to_contain_text('尚未连接服务器')
                    settings.locator('#mcp-extension-new').click();settings.locator('#mcp-extension-name').fill('远端工具服务');settings.locator('#mcp-transport').select_option('streamable-http');settings.locator('#mcp-url').fill('https://example.com/mcp');settings.locator('#mcp-extension-submit').click();expect(settings.locator('#mcp-extension-list .extension-card')).to_have_count(2)
                    settings.reload();expect(settings.locator('#mcp-extension-list .extension-card')).to_have_count(2)
                    settings.screenshot(path=str(output/'mcp-dark.png'),full_page=True)
                    checks.append('MCP stdio/HTTP configuration add, format check and refresh persistence; uninstalled command is never executed or downloaded')
                    settings.locator('[data-view=skill]').click();settings.locator('#skill-extension-name').fill('项目助理技能');settings.locator('#skill-path').fill(str(skill));settings.locator('#skill-extension-submit').click();expect(settings.locator('#skill-extension-status')).to_contain_text('已保存到本机')
                    settings.locator('#skill-extension-list').get_by_role('button',name='检查',exact=True).click();expect(settings.locator('#extension-preview-text')).to_contain_text('<script>plain text</script>');expect(settings.locator('#extension-preview-status')).to_contain_text('摘要与登记一致');settings.locator('#extension-preview-close').click()
                    skill_source.write_text('# 新版本',encoding='utf-8');settings.locator('#skill-extension-list').get_by_role('button',name='检查',exact=True).click();expect(settings.locator('#extension-preview-status')).to_contain_text('已变化');settings.locator('#extension-preview-close').click()
                    settings.locator('#skill-extension-list').get_by_role('button',name='移除',exact=True).click();expect(settings.locator('#skill-extension-list .extension-card')).to_have_count(0);assert skill_source.is_file()
                    checks.append('Skill registration, literal source preview, change detection and remove preserve original folder; no instruction injection')
                    page.set_viewport_size({'width':390,'height':844});page.emulate_media(color_scheme='light');page.screenshot(path=str(output/'explorer-mobile.png'),full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    settings.set_viewport_size({'width':390,'height':844});settings.emulate_media(color_scheme='light');settings.screenshot(path=str(output/'skills-mobile.png'),full_page=True)
                    assert settings.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert not errors,errors;assert chat.calls==1
                    checks.append('Dark desktop and light narrow layout checked; zero page errors; only one synthetic chat call')
                    browser.close()
                finally:job.close()
            report={'version':__version__,'captured_at':datetime.now(timezone.utc).isoformat(),'status':'passed','checks':checks,'page_errors':errors,'model_calls':'one synthetic, zero paid',
                    'screenshots':[str(output/x) for x in ['explorer-dark.png','mcp-dark.png','explorer-mobile.png','skills-mobile.png']],
                    'limits':['UTF-8 text editor, no language server/debugger/terminal or execution.','Single-root engineering file; no full VS Code workspace compatibility.','MCP/skills are registration only; no live MCP protocol or skill execution validated.']}
            (ROOT/'evals/reports/project-resources-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
        finally:server.shutdown();server.server_close()


if __name__=='__main__':main()

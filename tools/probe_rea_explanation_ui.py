"""Exercise REA's real parser through the browser and shared task ledger."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tests'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.service import CoreService
from jarvis_computer.browser import DriverJob
from probe_workspace_ui import SyntheticChat
from rea_fixtures import pack
from test_rea_explanation import Model
from test_conversations import document
from jarvis_core.conversations import ConversationStore
from playwright.sync_api import sync_playwright, expect


def main():
    spec = importlib.util.spec_from_file_location('rea_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    output = ROOT/'artifacts/rea-explanation'; output.mkdir(parents=True, exist_ok=True)
    checks, errors, chat = [], [], SyntheticChat()
    with tempfile.TemporaryDirectory(prefix='jarvis-rea-ui-') as temporary:
        root = Path(temporary); project = root/'project'; project.mkdir()
        pack(root/'pack-source',project/'app.asar',channels=20,unpack='preload.js')
        (project/'notes.txt').write_text('original draft',encoding='utf-8')
        core = CoreService(root/'data'); core.initialize(project)
        server = web.create_server(core=core, chat=chat, port=0)
        model=Model();model.models=chat.models;server.computer.skills.chat_factory=lambda *a,**kw:model
        assert server.ui_assets.snapshot()['status']=='ready', server.ui_assets.snapshot()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_address[1])
        try:
            with sync_playwright() as p:
                job = DriverJob(p)
                try:
                    browser = p.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width':1440, 'height':1050}); page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(origin); expect(page.locator('#send')).to_be_enabled(timeout=15000)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    page.locator('#open-project').click(); page.locator('#folder-path').fill(str(project)); page.locator('#project-open').click()
                    expect(page.locator('#context-project')).to_contain_text(str(project), timeout=15000)
                    page.locator('#composer-mode').select_option('skill'); page.locator('#skill-explicit').select_option('rea.software-analysis')
                    expect(page.locator('#skill-target')).to_be_visible(); expect(page.locator('#skill-paths')).not_to_be_visible()
                    page.locator('#skill-target').fill('app.asar'); page.locator('#skill-focus').fill('fixture:op1'); page.locator('#message').fill('分析 ASAR 中指定通道的模块结构和 IPC 调用链')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#conversation-task-list')).to_contain_text('本地静态解析与证据交付完成', timeout=45000)
                    task = page.locator('.conversation-task-card').first.get_attribute('data-task-id')
                    cid = page.evaluate('Workspace.currentConversation().id')
                    detail = server.conversation_tasks.detail(cid, task); report = detail['report']
                    assert detail['action_status'] == 'CONFIRMED'
                    assert report['analysis']['summary']['ipc']['paired_renderer_transmissions'] == 20
                    assert 'evidence' not in report and report['evidence_ref']['size_bytes'] > 1000000
                    assert report['checks']['model_calls'] == 0 and chat.calls == 0
                    assert report['input_manifest']['format']=='asar' and report['analysis']['focus']['query']=='fixture:op1'
                    checks.append('real ASAR -> shared FIFO -> pinned REA -> source recheck -> confirmed report, zero model calls')
                    if not page.locator('#explorer-panel').is_visible():page.locator('#open-explorer').click()
                    page.locator('#explorer-directory').click();page.get_by_role('button',name='notes.txt',exact=True).click();page.locator('#explorer-text').fill('unsaved draft preserved')
                    page.get_by_role('button', name='查看分析报告', exact=True).click()
                    expect(page.locator('#skill-report-preview')).to_contain_text('fixture:op')
                    assert not page.locator('dialog#skill-report-preview').count()
                    page.get_by_role('tab',name='来源证据',exact=True).click()
                    pager = page.locator('#rea-evidence-browser')
                    expect(pager).to_contain_text('匹配 ', timeout=15000)
                    expect(pager.get_by_role('searchbox',name='证据标识符筛选')).to_have_value('fixture:op1')
                    assert 'fixture:op10' not in pager.inner_text()
                    page.screenshot(path=str(output/'focus.png'))
                    pager.get_by_role('searchbox',name='证据标识符筛选').fill('missing:channel')
                    pager.get_by_role('button',name='筛选证据',exact=True).click()
                    expect(pager).to_contain_text('匹配 0 /', timeout=15000)
                    pager.get_by_role('button',name='显示全部',exact=True).click()
                    expect(pager).to_contain_text('当前 1—20', timeout=15000)
                    pager.get_by_role('button',name='下一页',exact=True).click()
                    expect(pager).to_contain_text('当前 21—40', timeout=15000)
                    pager.get_by_role('button',name='上一页',exact=True).click()
                    expect(pager).to_contain_text('当前 1—20', timeout=15000)
                    pager.get_by_role('combobox',name='证据类型').select_option('files')
                    expect(pager).to_contain_text('main.js', timeout=15000)
                    page.screenshot(path=str(output/'report.png'))
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.locator('#skill-report-preview').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                    page.screenshot(path=str(output/'report-mobile.png'))
                    page.set_viewport_size({'width':1440,'height':1050})
                    page.get_by_role('button', name='关闭软件解析结果', exact=True).click()
                    with page.expect_download() as download: page.get_by_role('button', name='下载产物', exact=True).click()
                    download.value.save_as(str(output/'analysis.txt'))
                    assert (output/'analysis.txt').read_text(encoding='utf-8') == report['text']
                    with page.expect_download() as download: page.get_by_role('button', name='下载完整证据', exact=True).click()
                    download.value.save_as(str(output/'evidence.json'))
                    assert json.loads((output/'evidence.json').read_text(encoding='utf-8')) == server.conversation_tasks.skill_evidence(cid,task)
                    checks.append('ASAR unpacked source and literal focus: 20 pairs, small receipt, verified separate evidence download and next/previous/file pages')
                    api_url=origin+'/api/skills/evidence/'+cid+'/'+task
                    assert page.request.get(api_url).status != 200
                    token=server.nonce
                    assert page.request.get(api_url+'?section=links&limit=51',headers={'X-Jarvis-Nonce':token}).status != 200
                    assert page.request.get(origin+'/api/skills/evidence/'+'0'*32+'/'+task,headers={'X-Jarvis-Nonce':token}).status != 200
                    assert page.request.get(api_url+'?section=links&query='+('x'*257),headers={'X-Jarvis-Nonce':token}).status != 200
                    checks.append('evidence route rejects missing nonce, invalid page size and wrong conversation')
                    # A separate explicit explanation task, with a synthetic one-shot model.
                    page.locator('#skill-explain').check()
                    page.locator('#message').fill('解释 fixture:op1 的静态调用关系')
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#message')).to_have_value('解释 fixture:op1 的静态调用关系')
                    expect(page.locator('#toast')).to_contain_text('需要明确选择模型')
                    assert len(model.calls)==0
                    page.locator('#model-trigger').click();page.get_by_role('option',name='离线验证模型',exact=True).click()
                    page.locator('#composer').evaluate('e=>e.requestSubmit()')
                    expect(page.locator('#conversation-task-list')).to_contain_text('静态解析与中文解释已交付',timeout=60000)
                    task=page.locator('.conversation-task-card').first.get_attribute('data-task-id')
                    detail=server.conversation_tasks.detail(cid,task);report=detail['report']
                    assert report['explanation']['model_calls']==1 and len(model.calls)==1
                    page.get_by_role('button',name='查看分析报告',exact=True).first.click()
                    page.get_by_role('tab',name='中文解释',exact=True).click()
                    expect(page.locator('#rea-pane-explanation')).to_contain_text('模型解释尚未独立核实')
                    page.locator('#rea-pane-explanation').get_by_role('button',name='E1',exact=True).click()
                    expect(page.locator('#rea-citation-source')).to_contain_text(report['explanation']['sources'][0]['edge_id'])
                    page.get_by_role('tab',name='中文解释',exact=True).click()
                    page.screenshot(path=str(output/'explanation.png'))
                    page.locator('#explorer-directory').click()
                    expect(page.locator('#skill-report-preview')).not_to_be_visible()
                    page.get_by_role('tab',name='notes.txt ●',exact=True).click();expect(page.locator('#explorer-text')).to_have_value('unsaved draft preserved')
                    page.get_by_role('tab',name='软件解析',exact=True).click()
                    expect(page.locator('#skill-report-preview')).to_be_visible()
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(output/'explanation-mobile.png'))
                    page.set_viewport_size({'width':1440,'height':1050})
                    checks.append('explicit one-shot model, bounded cited explanation, citation jump, read-only workspace tabs and mobile layout')
                    doc=document('引用验证');doc['title']='有名字的验证会话';doc['project_id']=detail['action']['arguments']['project_id'] if 'action' in detail else page.evaluate('Workspace.currentProject().id')
                    selected_project=doc['project_id'];archive=ConversationStore(core)
                    # The UI may already have saved this archive, use its current revision.
                    saved=archive.get(cid);doc=saved['document'];doc['title']='有名字的验证会话';archive.put(cid,{'revision':saved['revision'],'document':doc})
                    settings = browser.new_page(viewport={'width':1440, 'height':1050}); settings.on('pageerror', lambda e: errors.append(str(e)))
                    settings.goto(origin+'/settings#skill'); expect(settings.locator('.skill-card')).to_have_count(11, timeout=15000)
                    card = settings.locator('[data-skill-id="rea.software-analysis"]'); expect(card).to_contain_text('按条件启用')
                    settings.get_by_role('button', name='管理软件结构与行为解析', exact=True).click()
                    settings.get_by_role('tab',name='使用条件',exact=True).click()
                    expect(settings.locator('#skill-detail')).to_contain_text('EXE、APK')
                    expect(settings.locator('#skill-detail')).to_contain_text('静态解析')
                    settings.screenshot(path=str(output/'skill-detail.png'))
                    settings.locator('#skill-detail select').select_option('disabled'); settings.get_by_role('button', name='保存设置', exact=True).click()
                    expect(card).to_contain_text('已停用', timeout=10000)
                    settings.reload(); expect(card).to_contain_text('已停用', timeout=15000)
                    # A named conversation inherits its project's policy, then can override and restore it.
                    from jarvis_core.skills import SkillManager
                    SkillManager(core).put_policy({'skill_id':'rea.software-analysis','scope':'project','scope_id':selected_project,'revision':0,'mode':'manual'})
                    settings.locator('#skill-policy-scope').select_option('conversation')
                    expect(settings.locator('#skill-policy-conversation option')).to_contain_text(['有名字的验证会话'])
                    expect(card).to_contain_text('仅手动使用',timeout=15000)
                    expect(card).to_contain_text('本地流程就绪')
                    settings.get_by_role('button',name='管理软件结构与行为解析',exact=True).click()
                    expect(settings.locator('#skill-detail footer')).to_contain_text('来自项目')
                    settings.locator('#skill-detail select').select_option('auto');settings.get_by_role('button',name='保存设置',exact=True).click()
                    expect(card).to_contain_text('按条件启用')
                    settings.get_by_role('button',name='管理软件结构与行为解析',exact=True).click()
                    settings.locator('#skill-detail select').select_option('');settings.get_by_role('button',name='保存设置',exact=True).click()
                    expect(card).to_contain_text('仅手动使用')
                    settings.locator('#capability-navigation').get_by_role('link',name='MCP 工具',exact=True).click()
                    expect(settings.locator('#mcp-view')).to_be_visible()
                    expect(settings.locator('[data-view=skill]')).to_have_attribute('aria-current','page')
                    settings.locator('#capability-navigation').get_by_role('link',name='技能',exact=True).click()
                    expect(card).to_be_visible()
                    checks.append('unified settings, named conversation selection, project inheritance, explicit override and restore, policy distinct from readiness')

                    settings.set_viewport_size({'width':390,'height':844})
                    assert settings.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                    settings.screenshot(path=str(output/'skills-mobile.png'), full_page=True)
                    settings.set_viewport_size({'width':1440,'height':1050}); settings.screenshot(path=str(output/'skills.png'), full_page=True)
                    checks.append('one combined REA card; icon, conditions, format boundaries, persistent disable and mobile layout')
                    # Switching conversation closes task-specific views, but preserves file drafts.
                    page.get_by_role('button',name='新对话',exact=True).click()
                    expect(page.locator('#skill-report-preview')).to_have_count(0)
                    assert (project/'notes.txt').read_text(encoding='utf-8')=='original draft'
                    checks.append('unsaved file draft survives result tabs; changing conversations closes the previous task result')
                    assert errors == [], errors
                    browser.close()
                finally: job.close()
        finally: server.shutdown(); server.server_close(); thread.join(5)
    record = {'version':__version__, 'observed_at':datetime.now(timezone.utc).isoformat(), 'status':'passed',
              'checks':checks, 'page_errors':errors, 'model_calls':0, 'synthetic_explanation_calls':len(model.calls), 'target':'self_owned_fixture', 'report':report,
              'screenshots':['artifacts/rea-explanation/skills.png','artifacts/rea-explanation/skill-detail.png','artifacts/rea-explanation/report.png']}
    (ROOT/'evals/reports/rea-explanation-ui-2026-10-18.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status':'passed','checks':len(checks),'model_calls':0,'synthetic_explanation_calls':len(model.calls),'runtime':report['runtime']}))


if __name__ == '__main__': main()

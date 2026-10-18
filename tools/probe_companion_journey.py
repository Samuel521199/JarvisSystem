"""Joint personal-core acceptance: real UI/stores/LPAC, bounded synthetic models.

All records and files are synthetic and isolated from the user's live data.
--live adds exactly one cloud chat using the configured acceptance route.
Restart recreates the Host and its services; it is not an OS reboot/crash test.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'tools'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.chat import ChatService, gateway
from jarvis_core.continuity import ContinuityStore
from jarvis_core.evolution import EvolutionManager, recipes
from jarvis_core.evolution.demand import ConversationGrowth
from jarvis_core.persona import PersonaStore
from jarvis_core.process_memory import process_memory
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_computer.browser import DriverJob
from probe_sample_tasks_ui import Planner
from test_evolution import Provider
from playwright.sync_api import sync_playwright, expect


def run(output, use_live, report):
    spec = importlib.util.spec_from_file_location('companion_journey_web', ROOT/'apps/web/server.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    original_probe = gateway.probe
    calls, errors, timings = [], [], []
    provider, planner = Provider(), Planner()
    provider.release = threading.Event()
    report.update(checks=[], page_errors=errors, timings=timings, paid_calls=0)
    def passed(name):
        report['checks'].append(name)
        print(name, flush=True)
    def probe(config, selected, message, *args, **kwargs):
        calls.append({'provider': selected, 'message': message, 'history': kwargs['history'], 'instructions': kwargs['instructions']})
        return {'status': 'SUCCEEDED', 'text': '本轮上下文已核对。', 'provider': selected, 'model': config['providers'][selected]['model']}
    with tempfile.TemporaryDirectory(prefix='jarvis-companion-journey-') as temporary:
        base = Path(temporary); source = base/'sample'; source.mkdir()
        (source/'a.txt').write_bytes(b'abc'); (source/'学习.md').write_bytes(b'x')
        data = base/'data'; CoreService(data).initialize(source)
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex', automatic_fallback=False)
        path = base/'providers.json'; path.write_text(json.dumps(config), encoding='utf-8')
        def start():
            core = CoreService(data); chat = ChatService(core, path)
            server = web.create_server(core=core, chat=chat, port=0)
            server.evolution.close(); server.evolution = EvolutionManager(core, provider=provider, monitor=False)
            server.computer.sample.chat_factory = lambda *a, **kw: planner
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); thread.start()
            return server, thread
        def stop():
            server.shutdown(); server.server_close(); thread.join(3)
        server, thread = start()
        report['host_memory_before'] = process_memory()
        try:
            with patch('jarvis_core.chat.gateway.probe', side_effect=probe), sync_playwright() as p:
                driver = DriverJob(p)
                try:
                    browser = p.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1050})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    def visit(cid=None, count=None):
                        page.goto('http://127.0.0.1:'+str(server.server_port)+'/'+('#chat='+cid if cid else ''))
                        expect(page.locator('#send')).to_be_enabled()
                        expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                        if count is not None: expect(page.locator('.message.assistant')).to_have_count(count)
                    def send(text, expected=None):
                        before = page.locator('.message.assistant').count(); started = time.perf_counter()
                        page.locator('#message').fill(text); page.locator('#composer').evaluate('e=>e.requestSubmit()')
                        if expected:
                            expect(page.locator('.message.assistant')).to_have_count(before+1)
                            expect(page.locator('.message.assistant').last).to_contain_text(expected)
                            expect(page.locator('#send')).to_have_attribute('aria-label', '发送消息')
                            expect(page.locator('#conversation-status')).to_have_attribute('data-state', 'saved')
                        timings.append({'input': text, 'until_reply_and_archive_ms': round((time.perf_counter()-started)*1000, 2), 'awaited_reply': bool(expected), 'growth_busy': server.evolution.busy})
                    def panel():
                        page.locator('#open-memory').click(); page.get_by_role('button', name='接续', exact=True).click()
                        expect(page.locator('.continuity-card')).to_have_count(1)
                    def link(ids, prior=0):
                        panel(); page.get_by_role('button', name='关联任务与实际进展'+(' · '+str(prior) if prior else ''), exact=True).click()
                        for ident in ids: page.locator('[data-work-id="'+ident+'"]').check()
                        page.get_by_role('button', name='保存任务关联', exact=True).click()
                        expect(page.locator('#continuity-status')).to_contain_text('任务关联已保存')
                        page.locator('#memory-close').click()
                    visit()
                    send('今天只聊聊学习安排，不执行任务。', '本轮上下文已核对')
                    assert page.evaluate('Workspace.currentConversation().project_id') is None
                    send('请解释这句示例：“记住：测试秘密=不要保存”', '本轮上下文已核对')
                    assert server.chat.memory.list()['facts'] == [] and planner.calls == 0 and not provider.calls
                    passed('PAL-J01: no-project conversation and quoted memory instruction cause no memory/task/growth side effects')
                    send('设置交流风格：温暖', '已保存交流设置'); send('设置相处方式：伙伴', '已保存交流设置')
                    send('记住：学习节奏=每天十五分钟_JOURNEY_OLD', '已记住')
                    send('请按我的学习节奏建议', '本轮上下文已核对')
                    assert 'JOURNEY_OLD' not in str(calls[-1])
                    page.locator('#open-memory').click(); page.get_by_role('button', name='修改', exact=True).click()
                    page.locator('#memory-providers input[value="vertex"]').check(); page.locator('#memory-save').click()
                    expect(page.locator('#memory-status')).to_contain_text('已存入'); page.locator('#memory-close').click()
                    send('现在按允许的学习节奏建议', '本轮上下文已核对')
                    assert 'JOURNEY_OLD' in calls[-1]['message'] and 'companion tone' in calls[-1]['instructions']
                    passed('PAL-J02: explicit profile and fact persist; cloud fact omitted until permission set through UI')
                    cid = page.evaluate('Workspace.currentConversation().id')
                    server.computer.queue.set_paused(True)
                    send('/任务 列出样例目录文件并保存报告')
                    expect(page.locator('.conversation-task-card')).to_have_count(1)
                    tid = page.locator('.conversation-task-card').get_attribute('data-task-id')
                    send('保存接续：学习材料=目录报告还未完成｜整理学习资料后决定下一步', '已保存接续')
                    link([tid])
                    panel(); page.locator('.continuity-card input[value="vertex"]').check()
                    page.get_by_role('button', name='保存许可', exact=True).click()
                    expect(page.locator('#continuity-status')).to_contain_text('接续已更新'); page.locator('#memory-close').click()
                    send('继续话题：学习材料', '待办'); send('先核对现在的真实进展', '本轮上下文已核对')
                    assert '"state":"pending"' in calls[-1]['message'] and planner.calls == 0
                    server.computer.queue.set_paused(False)
                    expect(page.locator('#conversation-task-list')).to_contain_text('已核验：2 个文件', timeout=20000)
                    send('/改进 把最近的目录报告导出为 TSV')
                    expect(page.locator('#growth-dialog')).to_be_visible(); expect(page.locator('.growth-card')).to_have_count(1)
                    gid = page.locator('.growth-card').get_attribute('data-growth-id')
                    assert not provider.calls
                    page.get_by_role('button', name='补齐能力并导出', exact=True).click(); assert provider.entered.wait(5)
                    page.locator('#growth-close').click()
                    send('你在整理资料时，陪我讨论一下明天的学习计划', '本轮上下文已核对')
                    assert server.evolution.busy and '"state":"completed"' in calls[-1]['message']
                    assert '先核对现在的真实进展' not in str(calls[-1]['history'])
                    assert '今天只聊聊学习安排' in str(calls[-1]['history'])
                    send('修改记忆：学习节奏=每天二十分钟_JOURNEY_CURRENT', '已纠正')
                    send('按纠正后的安排继续讨论', '本轮上下文已核对')
                    assert 'JOURNEY_CURRENT' in calls[-1]['message'] and 'JOURNEY_OLD' not in str(calls[-1])
                    assert server.evolution.busy
                    report['host_memory_during_growth'] = process_memory()
                    passed('PAL-J03: actual queued/completed task plus blocked coding; chat and memory correction remain responsive, obsolete context removed')
                    provider.release.set(); send('/成长进度')
                    expect(page.locator('.growth-card')).to_contain_text('已完成', timeout=45000)
                    job = server.evolution.store.job(gid)
                    assert job['result']['benefit']['verified_on_user_input'] and len(provider.calls) == 1
                    assert job['attempts'][0]['validation']['isolation']['backend'] != 'test-double'
                    with page.expect_download() as download: page.get_by_role('button', name='下载已核验结果', exact=True).click()
                    download.value.save_as(str(output/'learning-materials.tsv'))
                    assert (output/'learning-materials.tsv').read_text(encoding='utf-8') == recipes.expected(job['request']['input'])
                    page.locator('#growth-close').click(); link([gid], 1)
                    page.locator('#clear').click(); send('继续话题：学习材料', '已完成且交付核验通过')
                    send('新会话一起核对我的偏好和两项实际交付', '本轮上下文已核对')
                    assert calls[-1]['message'].count('"state":"completed"') == 2 and 'JOURNEY_CURRENT' in calls[-1]['message']
                    assert 'companion tone' in calls[-1]['instructions'] and calls[-1]['history'] == []
                    note = ContinuityStore(server.core).list()['records'][0]
                    passed('PAL-J04: verified LPAC export/download and new chat join profile, corrected fact, source note and both completed work records')
                    if use_live:
                        report['paid_calls'] += 1
                        # Playwright's sync API owns an event loop on this thread.
                        # Match real HTTP handling: run the synchronous gateway in a worker.
                        with patch('jarvis_core.chat.gateway.probe', side_effect=original_probe), ThreadPoolExecutor(max_workers=1) as pool:
                            result = pool.submit(server.chat.reply, '只按本轮允许的资料返回 JSON 对象：daily_minutes 为学习节奏的分钟数整数；work_states 为关联的 kind 到 state 映射。忽略主人旧进展的推断，不执行工作。', provider='vertex', model='gemini-3.1-pro-preview', personal_context={'temporary': False}, memory_context={'enabled': True, 'project_id': None}, continuity_context={'enabled': True, 'ids': [note['id']]}, _route_attempt_limit=1).result()
                        (output/'live-response.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                        assert result['status'] == 'SUCCEEDED', result
                        answer = result.get('text', '').strip()
                        if answer.startswith('```'): answer = answer.split('\n', 1)[1].rsplit('```', 1)[0].strip()
                        value = json.loads(answer)
                        assert result['status'] == 'SUCCEEDED' and value == {'daily_minutes': 20, 'work_states': {'task': 'completed', 'growth': 'completed'}}, result
                        report['live'] = {'route': 'vertex::gemini-3.1-pro-preview', 'usage': result.get('usage'), 'answer': value, 'history_info': result.get('history_info')}
                        passed('PAL-J05: one real Google reply uses corrected personal fact and both verified work states, despite stale owner progress')
                    # Frozen queued record models an interrupted dispatch; no arbitrary ledger rewrite.
                    bridge = ConversationGrowth(server.core, server.evolution, server.conversation_tasks)
                    interrupted = bridge.propose(cid, {'request_id': uuid.uuid4().hex, 'prompt': '导出 CSV'})
                    link([interrupted['id']], 2)
                    server.evolution.store.queue_proposal(interrupted['id'])
                    current_cid = page.evaluate('Workspace.currentConversation().id'); count = page.locator('.message.assistant').count()
                    before_profile = PersonaStore(server.core).snapshot()
                    stop(); server, thread = start(); visit(current_cid, count)
                    assert PersonaStore(server.core).snapshot() == before_profile
                    assert len(provider.calls) == 1 and server.evolution.store.job(interrupted['id'])['status'] == 'INTERRUPTED'
                    send('重开后按真实状态接续', '本轮上下文已核对')
                    assert '"state":"interrupted"' in calls[-1]['message'] and calls[-1]['message'].count('"state":"completed"') == 2
                    assert 'JOURNEY_CURRENT' in calls[-1]['message'] and 'companion tone' in calls[-1]['instructions']
                    assert calls[-1]['history'] == []
                    passed('PAL-J06: fresh Host retains profile/fact/notes/work, pending dispatch becomes interrupted without model replay; old work-derived history removed')
                    panel(); page.get_by_role('button', name='关联任务与实际进展 · 3', exact=True).click()
                    expect(page.locator('.continuity-work')).to_contain_text('中断，未自动重试')
                    page.locator('.continuity-work').scroll_into_view_if_needed(); page.screenshot(path=str(output/'desktop.png'))
                    page.set_viewport_size({'width': 390, 'height': 844}); page.locator('.continuity-work').scroll_into_view_if_needed()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'); page.screenshot(path=str(output/'mobile.png'))
                    source_count = sum(m['role'] == 'assistant' for m in server.conversations.get(cid)['document']['messages'])
                    with page.expect_popup() as popup: page.locator('.continuity-work a').last.click()
                    original_page = page; page = popup.value
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    expect(page.locator('.message.assistant')).to_have_count(source_count)
                    expect(page.locator('.jarvis-cinema')).not_to_be_visible(timeout=15000)
                    assert page.evaluate('Workspace.currentConversation().id') == cid
                    send('/成长进度')
                    expect(page.locator('.growth-card[data-growth-id="'+interrupted['id']+'"]').first).to_contain_text('运行中断')
                    page.locator('#growth-close').click(); send('/改进 导出 CSV')
                    expect(page.get_by_role('button', name='使用现有能力导出', exact=True)).to_be_visible()
                    fresh_id = page.locator('.growth-card').first.get_attribute('data-growth-id')
                    assert fresh_id not in (gid, interrupted['id'])
                    page.get_by_role('button', name='使用现有能力导出', exact=True).click()
                    expect(page.locator('.growth-card[data-growth-id="'+fresh_id+'"]').first).to_contain_text('已完成', timeout=20000)
                    assert len(provider.calls) == 1 and server.evolution.store.job(interrupted['id'])['status'] == 'INTERRUPTED'
                    fresh = server.evolution.store.job(fresh_id)
                    assert fresh['result']['text'] == recipes.expected(fresh['request']['input'])
                    page.screenshot(path=str(output/'explicit-recovery.png'))
                    page.close(); page = original_page; page.locator('#memory-close').click()
                    passed('PAL-J09: return to source conversation and explicitly reanalyse; fresh proposal reuses verified ability and completes, old interrupted receipt remains unchanged, zero new coding calls')
                    # Scope and route assembly use the same current stores, with synthetic replies.
                    folder = base/'work-project'; folder.mkdir()
                    project = WorkspaceService(server.core).open_project({'path': str(folder)})['id']
                    common = {'personal_context': {'temporary': False}, 'continuity_context': {'enabled': True, 'ids': [note['id']]}}
                    before_calls = len(calls)
                    blocked = server.chat.reply('工作项目里讨论', provider='vertex', memory_context={'enabled': True, 'project_id': project}, **common)
                    assert blocked['error'] == 'continuity_not_available' and len(calls) == before_calls
                    server.chat.reply('工作项目里讨论', provider='vertex', personal_context={'temporary': False}, memory_context={'enabled': True, 'project_id': project})
                    assert 'JOURNEY_CURRENT' in calls[-1]['message'] and '"linked_work"' not in calls[-1]['message']
                    before_calls = len(calls)
                    blocked = server.chat.reply('换供应商继续', provider='openai', memory_context={'enabled': True, 'project_id': None}, **common)
                    assert blocked['error'] == 'continuity_not_available' and len(calls) == before_calls
                    server.chat.reply('换供应商继续', provider='openai', personal_context={'temporary': False}, memory_context={'enabled': True, 'project_id': None})
                    assert 'JOURNEY_CURRENT' not in str(calls[-1]) and '"linked_work"' not in calls[-1]['message'] and 'companion tone' in calls[-1]['instructions']
                    passed('PAL-J07: invalid selected note blocks dispatch; deselection restores chat; project/provider scope respected while expression persists (synthetic routes)')
                    send('忘记：学习节奏', '已忘记'); send('忘记接续：学习材料', '已忘记')
                    send('忘记以后，只聊聊新的学习问题', '本轮上下文已核对')
                    assert 'JOURNEY_' not in str(calls[-1]) and '"linked_work"' not in calls[-1]['message'] and calls[-1]['history'] == []
                    assert not server.chat.memory.list()['facts'] and not ContinuityStore(server.core).list()['records']
                    assert server.core.ledger.record(task_id=tid)['task']['status'] == 'SUCCEEDED'
                    assert server.evolution.store.job(gid)['status'] == 'SUCCEEDED'
                    # Model config unavailable: deterministic query still responds locally.
                    previous = server.chat.config_path; server.chat.config_path = base/'missing.json'
                    before_calls = len(calls); send('查看交流设置', '温暖'); assert len(calls) == before_calls
                    server.chat.config_path = previous
                    page.locator('#conversation-status').click(); page.locator('#conversation-temporary').click()
                    send('记住：临时=不应留下')
                    expect(page.locator('.message.error')).to_contain_text('临时会话')
                    assert not server.chat.memory.list()['facts'] and len(calls) == before_calls
                    assert not errors, errors
                    passed('PAL-J08: forget invalidates dependent history without deleting work; absent model config preserves local profile query; temporary write blocked')
                    report.update(synthetic_chat_calls=len(calls), synthetic_coding_calls=len(provider.calls), planner_calls=planner.calls, host_memory_after=process_memory())
                    browser.close()
                except Exception:
                    if 'page' in locals(): page.screenshot(path=str(output/'failure.png'))
                    raise
                finally: driver.close()
        finally:
            provider.release.set(); stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True); parser.add_argument('--live', action='store_true')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    report = {'version': __version__, 'captured_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
              'scope': 'Synthetic owner/files; real Edge/HTTP/archives/LPAC/ledger/download; synthetic planner/coder/chat except optional one real cloud reply. Host restart, not process crash or OS reboot. Host RSS includes probe+Playwright client, excludes browser/model processes. Timings include UI polling/archive flush, synthetic chat latency.'}
    try:
        run(args.output, args.live, report); report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'; report['failure'] = traceback.format_exc(); print(report['failure'])
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False)); return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())

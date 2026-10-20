"""Disposable two-Agent UI, concurrency and optional bounded live model probe."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests'), str(ROOT/'apps/web'), str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__
from jarvis_core.team_tasks import TeamTaskService
from jarvis_core.team_protocol import CAPABILITY
from jarvis_core.dialogue_process import DialogueProcesses
from jarvis_computer.browser import DriverJob
from tools.probe_parallel_runtime import fixture, serve, wait, request
from tools.probe_workspace_ui import SyntheticChat
from test_team_tasks import Calls, Provider
from playwright.sync_api import sync_playwright, expect
from server import create_server

OUT = Path('H:/JarvisData/diagnostics/k6-team-20261020')


def ui_probe():
    checks, errors = {}, []
    with tempfile.TemporaryDirectory(prefix='jarvis-team-ui-') as directory:
        core = fixture(Path(directory)); calls = Calls(); release = threading.Event()
        def hold(guard, options):
            while not release.wait(.02): guard()
        calls.hook = hold
        class Chat(SyntheticChat):
            text = '后台协作时也可以继续和你聊天。'
            def models(self):
                return {'providers': [{'provider': 'local'}], 'models': [
                    {'provider': 'local', 'model': name, 'label': name, 'reasoning_levels': ['low'],
                     'reasoning_default': 'low', 'last_probe_status': 'NOT_TESTED'}
                    for name in ('planner', 'reviewer')]}
        chat = Chat(); server = create_server(core=core, chat=chat, port=0)
        server.computer.team = TeamTaskService(core, model_calls=calls, provider=Provider())
        thread = serve(server)
        try:
            with sync_playwright() as pw, closing(DriverJob(pw)):
                browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                try:
                    page = browser.new_page(viewport={'width': 1280, 'height': 950})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.wait_for_function('()=>window.TeamWorkbench&&window.Workspace&&!Workspace.isBusy()')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    page.locator('#composer-mode').select_option('team')
                    page.locator('#team-controls summary').click()
                    page.locator('#team-reviewer').select_option('local::reviewer')
                    page.locator('#message').fill('帮我规划每周学习和休息时间。')
                    page.locator('#send').click()
                    expect(page.locator('#message')).to_have_value('帮我规划每周学习和休息时间。')
                    assert not calls.requests
                    checks['empty_criteria_keeps_draft_no_call'] = True
                    page.locator('#team-criteria').fill('资源占用有实测')
                    page.locator('#send').click()
                    wait(lambda: len(calls.requests) == 1)
                    cid = page.evaluate('Workspace.currentConversation().id')
                    listing = request(server, '/api/conversation-tasks/'+cid)[1]
                    tid = listing['tasks'][0]['task_id']
                    page.locator('#composer-mode').select_option('chat')
                    page.locator('#message').fill('聊聊今天')
                    page.locator('#send').click()
                    expect(page.locator('#messages')).to_contain_text(Chat.text)
                    assert server.computer.detail(tid, all_tasks=True)['action_status'] == 'DISPATCHING'
                    checks['foreground_chat_while_team_waits'] = True
                    release.set()
                    wait(lambda: server.computer.detail(tid, all_tasks=True)['action_status'] == 'CONFIRMED')
                    page.locator('#conversation-task-refresh').click()
                    page.get_by_role('button', name='查看协作报告', exact=True).click()
                    expect(page.locator('#team-result-dialog')).to_contain_text('需要修改')
                    expect(page.locator('#team-result-dialog')).to_contain_text('事实正确性尚未验收')
                    page.screenshot(path=str(OUT/'desktop.png'))
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#team-result-dialog').evaluate('el=>el.scrollWidth<=el.clientWidth+1')
                    page.screenshot(path=str(OUT/'mobile.png'))
                    page.locator('#team-result-dialog').get_by_role('button', name='关闭', exact=True).click()
                    page.reload(); page.wait_for_function('()=>window.ConversationTasks&&window.Workspace&&!Workspace.isBusy()')
                    page.wait_for_function('()=>!document.documentElement.hasAttribute("data-brand-cinema")')
                    page.locator('#conversation-tasks-toggle').click()
                    expect(page.locator('#conversation-task-list')).to_contain_text(tid)
                    assert len(calls.requests) == 2
                    report = server.computer.detail(tid, all_tasks=True)['report']
                    report['proposal']['summary'] = '<img src=x onerror="window.__teamInjected=true">'
                    page.evaluate('report=>TeamWorkbench.preview(report)', report)
                    assert page.locator('#team-result-dialog img').count() == 0
                    assert page.evaluate('window.__teamInjected===undefined')
                    page.locator('#team-result-dialog').get_by_role('button', name='关闭', exact=True).click()
                    checks.update(report_rendered_without_html_execution=True, mobile_fits=True, reload_no_replay=True)
                    # A second explicit task; cancellation during call conserves uncertainty.
                    calls.requests.clear(); release.clear()
                    payload = {'mode': 'team', 'request_id': 'web-'+uuid.uuid4().hex, 'prompt': '取消测试',
                               'criteria': ['检查取消'], 'planner_model': 'local::planner', 'reviewer_model': 'local::reviewer'}
                    code, row, _ = request(server, '/api/conversation-tasks/'+cid, 'POST', payload)
                    assert code == 202, (code, row)
                    wait(lambda: len(calls.requests) == 1)
                    code, _, _ = request(server, '/api/conversation-tasks/'+cid+'/'+row['task_id']+'/cancel', 'POST', {})
                    assert code == 200
                    wait(lambda: server.computer.detail(row['task_id'], all_tasks=True)['action_status'] == 'UNKNOWN')
                    wait(lambda: server.computer.queue.snapshot()['paused'])
                    checks['cancel_inflight_no_review_unknown_pauses_queue'] = True
                    page.set_viewport_size({'width': 1280, 'height': 950})
                    page.locator('#composer-mode').select_option('team')
                    page.locator('#team-controls summary').click()
                    page.locator('#team-criteria').fill('仅属于旧会话的检查要求')
                    page.locator('#clear').click()
                    page.wait_for_function('old=>Workspace.currentConversation().id!==old', arg=cid)
                    expect(page.locator('#team-criteria')).to_have_value('')
                    checks['conversation_change_clears_criteria_draft'] = True
                    assert not errors, errors
                finally: browser.close()
            return {'status': 'passed', 'checks': checks, 'page_errors': errors,
                    'screenshots': [str(OUT/'desktop.png'), str(OUT/'mobile.png')],
                    'limits': ['Models are fixtures; HTTP, SQLite, FIFO and Edge are real.',
                               'No owner files, memory or microphone used.']}
        finally:
            release.set(); server.shutdown(); server.server_close(); thread.join(3); time.sleep(2)


def live_probe():
    with tempfile.TemporaryDirectory(prefix='jarvis-team-live-') as directory:
        core = fixture(Path(directory)); pool = DialogueProcesses(core, capacity=1)
        try:
            team = TeamTaskService(core, model_calls=pool)
            args = team.admit({'prompt': '为白天工作的成年人设计七天英语练习安排，每天只有20分钟，并留出休息日。不假定他的英语水平。',
                               'criteria': ['每个练习日总时长不超过20分钟', '包含休息日且未知英语水平明确标为假设'],
                               'planner_model': 'vertex::gemini-3.8-flash', 'planner_reasoning': 'low',
                               'reviewer_model': 'vertex::gemini-3.1-pro-preview', 'reviewer_reasoning': 'low'})
            record = core.ledger.prepare('team-live-'+uuid.uuid4().hex, args, capability=CAPABILITY, runtime_seconds=180)
            start = time.monotonic()
            result = team.run(record['action']['action_id'])
            report = json.loads((core.ledger.artifact_dir/result['artifact']['path']).read_bytes()) if result['artifact'] else None
            output = {'action_status': result['action']['status'], 'seconds': round(time.monotonic()-start, 2),
                      'report': report, 'calls': team.calls(record['task']['task_id']),
                      'error': result['action'].get('error'), 'processes': pool.snapshot(),
                      'limits': ['One new disposable task and at most two paid requests; no retries.',
                                 'A single successful sample does not establish general planning quality.']}
            (OUT/'live.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            return output
        finally: pool.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'version': __version__, 'at': datetime.now(timezone.utc).isoformat()}
    if '--live' in sys.argv:
        result['live'] = live_probe()
        print(json.dumps({'status': result['live']['action_status'], 'seconds': result['live']['seconds'],
                          'error': result['live']['error']}, ensure_ascii=False))
    else:
        result['ui'] = ui_probe()
        print(json.dumps(result['ui'], ensure_ascii=False))
    (OUT/('live-probe.json' if '--live' in sys.argv else 'ui-probe.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()

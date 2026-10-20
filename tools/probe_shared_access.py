"""Browser -> actual private model worker with synthetic local HTTP responses."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid
import statistics

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'runtime/node-host'),
               str(ROOT/'adapters/computer-use')]
from probe_parallel_runtime import fixture, web, serve, wait, request
from jarvis_core import __version__, federation_protocol as p
from jarvis_core.chat import ChatService
from jarvis_core.federation import Federation
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_core.memory import MemoryError
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


def ui(output):
    checks, errors, payloads = [], [], []
    with tempfile.TemporaryDirectory(prefix='jarvis-shared-access-') as directory:
        base = Path(directory)
        left, right = base/'left', base/'right'; left.mkdir(); right.mkdir()
        core, peer_core = fixture(left), fixture(right)
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='local', automatic_fallback=False, fallback_order=['local'])
        config_path = base/'models.json'; config_path.write_text(json.dumps(config), encoding='utf-8')
        chat = ChatService(core, config_path)
        server = web.create_server(core=core, chat=chat, port=0); thread = serve(server)
        chat.dialogue_models._command = [sys._base_executable, '-u', str(ROOT/'tests/shared_dialogue_fixture.py'), 'normal']
        local, peer = server.federation, Federation(peer_core)
        try:
            for service in (local, peer): service.initialize()
            local.listen('127.0.0.1', 0)
            invitation = local.invite('本轮共享用途测试'); sid = invitation['space']; peer.join(invitation['invitation'])
            item = uuid.uuid4().hex
            local.edit(sid, item, p.heads_token([]), '合成伙伴资料',
                       'SYNTHETIC_SHARED_DATA_85：他人的资料，不是主人偏好。<script>alert(1)</script>')
            with sync_playwright() as pw, closing(DriverJob(pw)):
                browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1050})
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: payloads.append(r.post_data_json)
                        if r.method == 'POST' and r.url.endswith('/api/dialogue/turns') else None)
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                wait(lambda: page.evaluate('!!(window.Workspace && !Workspace.isBusy() && window.Attachments)'))
                wait(lambda: page.evaluate("document.body.dataset.brandCinema !== 'active'"))
                page.locator('#shared-reference-open').click()
                choose = page.get_by_role('button', name='加入当前对话引用', exact=True)
                choose.click()
                expect(page.locator('.shared-reference-dialog [data-status]')).to_contain_text('尚未授权')
                assert page.evaluate('Attachments.shared().length') == 0
                assert page.locator('.shared-reference-dialog script').count() == 0
                checks.append('default_deny_and_html_is_text')
                page.get_by_role('button', name='关闭共享资料选择', exact=True).click()

                settings = context.new_page()
                settings.on('pageerror', lambda e: errors.append(str(e)))
                settings.goto(f'http://127.0.0.1:{server.server_port}/settings#federation')
                panel = settings.locator('#shared-access-root')
                expect(panel.locator('[data-form]')).to_be_visible()
                panel.locator(f'[data-cards] input[value="{item}"]').check()
                panel.locator('[data-providers] input[value="local"]').check()
                panel.get_by_role('button', name='保存用途授权', exact=True).click()
                wait(lambda: local.access.options(sid)['policy']['revision'] == 1)
                expect(panel.locator('[data-providers] input[value="local"]')).to_be_checked()
                checks.append('settings_grants_one_card_and_one_destination')
                page.locator('#shared-reference-open').click(); choose.click()
                wait(lambda: page.evaluate('Attachments.shared().length === 1'))
                assert page.evaluate('Attachments.wire().length') == 0
                assert 'SYNTHETIC_SHARED_DATA_85' not in page.evaluate('JSON.stringify(Attachments.snapshot())')
                page.get_by_role('button', name='关闭共享资料选择', exact=True).click()

                def send(message, text):
                    page.locator('#message').fill(message); page.locator('#send').click()
                    expect(page.locator('#messages')).to_contain_text(text, timeout=20000)
                    wait(lambda: page.evaluate('!Workspace.isBusy()'))

                send('请说明这张共享资料', '共享资料测试回答')
                assert len(payloads) == 1 and payloads[0]['chat']['shared_context']['references']
                assert 'SYNTHETIC_SHARED_DATA_85' not in json.dumps(payloads[0])
                conversation = page.evaluate('Workspace.currentConversation().id')
                wait(lambda: len(server.conversations.get(conversation)['document']['messages']) >= 2)
                doc = server.conversations.get(conversation)['document']
                user_index = next(i for i, row in enumerate(doc['messages']) if row['role'] == 'user')
                assert all(row.get('attachments_omitted') for row in doc['messages'][user_index:user_index+2])
                try:
                    PersonalCandidates(core).source({'conversation_id': conversation, 'message_index': user_index}, None)
                except MemoryError as exc:
                    assert exc.code == 'candidate_source_invalid'
                else:
                    raise AssertionError('Shared source became personal memory candidate')
                checks.extend(['real_child_resolves_reference', 'shared_turn_excluded_from_personal_candidates'])
                send('继续解释上一轮', '普通测试回答')
                # The second answer carries the live dependencies even though raw card text is not resent.
                assert page.evaluate('history.at(-1)._shared_refs.length') == 1
                checks.append('derived_answer_keeps_reference_dependency')
                panel.get_by_role('button', name='撤销全部模型使用', exact=True).click()
                wait(lambda: not local.access.options(sid)['policy']['providers'])
                page.locator('#message').fill('现在再聊一件事')
                page.locator('#send').click()
                wait(lambda: page.evaluate('!Workspace.isBusy() && history.length >= 6'))
                assert page.evaluate('history.at(-1)._shared_refs.length') == 0
                expect(page.locator('#toast')).to_contain_text('共享')
                checks.append('revoked_dependency_turns_excluded_before_followup_dispatch')
                page.evaluate("""async () => {
                    document.querySelector('#messages .assistant').remove();
                    Workspace.remember(); await Workspace.flushConversation();
                }""")
                page.reload()
                wait(lambda: page.evaluate('!!(window.Workspace && !Workspace.isBusy())'))
                assert page.evaluate('history.every(r=>!r.content.includes("共享资料测试回答"))')
                checks.append('reload_does_not_resurrect_shared_model_history')
                recover = page.get_by_role('button', name='取回回复', exact=True)
                expect(recover).to_be_visible(timeout=15000); recover.click()
                wait(lambda: page.evaluate('!Workspace.isBusy()'))
                assert page.evaluate("document.querySelector('#messages .assistant:last-child').dataset.attachmentsOmitted === 'true'")
                assert page.evaluate('history.every(r=>!r.content.includes("共享资料测试回答"))')
                checks.append('recovered_answer_visible_but_excluded_from_personal_source_and_model_history')
                page.locator('#clear').click(); wait(lambda: page.evaluate('!Workspace.isBusy()'))
                assert page.evaluate('history.length') == 0
                checks.append('new_conversation_starts_without_shared_context')

                # HTTP validation rejects forged context/scope before dispatch.
                bad = request(server, '/api/chat', 'POST', {'message':'test','shared_context':{'scope':None,'references':[{}]}})
                assert bad[0] == 400
                checks.append('http_rejects_malformed_references')
                output.mkdir(parents=True, exist_ok=True)
                settings.screenshot(path=str(output/'access-desktop.png'), full_page=True)
                panel.screenshot(path=str(output/'access-panel.png'))
                settings.emulate_media(color_scheme='dark')
                settings.screenshot(path=str(output/'access-dark.png'), full_page=True)
                settings.set_viewport_size({'width':390,'height':844})
                settings.screenshot(path=str(output/'access-mobile.png'), full_page=True)
                assert settings.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                page.locator('#shared-reference-open').click()
                page.screenshot(path=str(output/'reference-desktop.png'))
                browser.close()
            assert not errors, errors
            return {'status':'passed', 'checks':checks, 'page_errors':errors,
                    'model_processes_completed':chat.dialogue_models.snapshot()['completed'],
                    'screenshots':[str(p) for p in sorted(output.glob('*.png'))],
                    'limits':['Synthetic model responses; real browser, HTTP, isolated worker, admission, SQLite, TLS and DPAPI.',
                              'No real second PC, no cloud model quality assessment.']}
        finally:
            peer.close(); server.shutdown(); server.server_close(); thread.join(timeout=5); time.sleep(2)


def bounded_use():
    # Eight maximum-sized cards exercise the reference ceiling, not a long-running PC benchmark.
    sys.path.insert(0, str(ROOT/'tests'))
    from test_federation_access import AccessTests
    probe = AccessTests(); probe.setUp()
    try:
        ctx = probe.ready(('local',)); cards = [probe.item]
        for index in range(7):
            cards.append(probe.edit(probe.a, text='x'*3900))
        probe.grant(('local',), cards=cards)
        ctx['references'] = [probe.a.access.issue(
            probe.sid, item, p.heads_token(probe.card(probe.a,item)), probe.scope)['reference'] for item in cards]
        samples = []
        for _ in range(20):
            start = time.perf_counter()
            values, _, _, refs = probe.a.access.prepare(ctx, [], [], probe.config, 'local')
            probe.a.access.recheck(probe.scope, refs, probe.config, 'local')
            assert len(values) == 8
            samples.append((time.perf_counter()-start)*1000)
        return {'references':8, 'samples':20, 'prepare_plus_recheck_median_ms':round(statistics.median(samples),3),
                'prepare_plus_recheck_max_ms':round(max(samples),3), 'sqlite_bytes':probe.a.store.path.stat().st_size,
                'limits':'Short same-PC synthetic sample; not peak-memory, low-spec PC or long-run proof.'}
    finally:
        probe.doCleanups()


def main():
    report = {'version':__version__, 'captured_at':datetime.now(timezone.utc).isoformat(),
              'ui':ui(Path('H:/JarvisData/diagnostics/k6-shared-access-20261020')),
              'bounded_use':bounded_use(), 'cloud_model_calls':0, 'scope':'Local scoped grants and revocable shared references'}
    path = ROOT/'evals/reports/k6-shared-access-2026-10-20.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','report':str(path)}))


if __name__ == '__main__':
    main()

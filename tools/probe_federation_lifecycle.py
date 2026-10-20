"""Settings retirement/recovery and explicit chat-copy integration in disposable cores."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'runtime/node-host'),
               str(ROOT/'adapters/models/provider-native'), str(ROOT/'adapters/computer-use')]
from probe_parallel_runtime import fixture, web, serve, wait
from probe_workspace_ui import SyntheticChat
from probe_federation import processes
from jarvis_core import __version__, federation_protocol as protocol
from jarvis_core.federation import Federation
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_core.memory import MemoryError
from jarvis_core.federation_lifecycle import validate_export
from jarvis_computer.browser import DriverJob
from playwright.sync_api import sync_playwright, expect


class CapturedChat(SyntheticChat):
    text = '这是基于本轮明确附件的测试回答。'

    def __init__(self):
        self.inputs = []

    def reply(self, message, **kwargs):
        self.inputs.append({'message': message, 'attachments': deepcopy(kwargs.get('attachments', [])),
                            'history': deepcopy(kwargs.get('history', []))})
        return super().reply(message, **kwargs)


def ui(output):
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='jarvis-shared-lifecycle-') as directory:
        base = Path(directory)
        left, right = base/'left', base/'right'; left.mkdir(); right.mkdir()
        core, peer_core = fixture(left), fixture(right)
        chat = CapturedChat()
        server = web.create_server(core=core, chat=chat, port=0); thread = serve(server)
        local, peer = server.federation, Federation(peer_core)
        gate = threading.Event()
        try:
            for service in (local, peer): service.initialize()
            local.listen('127.0.0.1', 0)
            invitation = local.invite('共同计划'); sid = invitation['space']; peer.join(invitation['invitation'])
            item = uuid.uuid4().hex
            local.edit(sid, item, protocol.heads_token([]), '伙伴资料', '其他人的偏好：我喜欢咖啡。<script>alert(1)</script>')
            peer.sync(sid)
            with sync_playwright() as pw, closing(DriverJob(pw)):
                browser = pw.chromium.launch(channel='msedge', headless=True, chromium_sandbox=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1050}, accept_downloads=True)
                page = context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                wait(lambda: page.evaluate('!!(window.Workspace && !Workspace.isBusy() && window.Attachments)'))
                wait(lambda: page.evaluate("document.body.dataset.brandCinema !== 'active'"))
                page.locator('#shared-reference-open').click()
                choose = page.get_by_role('button', name='加入当前对话附件')
                expect(choose).to_be_visible()
                assert page.locator('.shared-reference-dialog script').count() == 0
                original = local.lifecycle.reference
                entered = threading.Event()
                def delayed(*args):
                    entered.set(); gate.wait(5)
                    return original(*args)
                local.lifecycle.reference = delayed
                choose.click(); wait(entered.is_set)
                page.get_by_role('button', name='关闭共享资料选择', exact=True).click()
                old_scope = page.evaluate('Workspace.currentConversation().id')
                page.locator('#clear').click()
                wait(lambda: page.evaluate('(old) => Workspace.currentConversation().id !== old && !Workspace.isBusy()', old_scope))
                gate.set()
                page.wait_for_timeout(150)
                assert page.evaluate('Attachments.wire().length') == 0
                local.lifecycle.reference = original
                checks.append('late_reference_does_not_cross_conversation')
                page.locator('#shared-reference-open').click()
                choose.click()
                expect(page.locator('#attachment-list .attachment-card')).to_have_count(1)
                page.get_by_role('button', name='关闭共享资料选择', exact=True).click()
                assert not chat.inputs
                page.locator('#message').fill('请概括附件资料，不要当成我的偏好。')
                page.locator('#send').click()
                wait(lambda: bool(chat.inputs))
                wait(lambda: page.evaluate('!Workspace.isBusy()'))
                assert len(chat.inputs[0]['attachments']) == 1
                assert '来源空间/卡：'+sid+'/'+item in chat.inputs[0]['attachments'][0]['text']
                conversation = page.evaluate('Workspace.currentConversation().id')
                archive = wait(lambda: next((row for row in server.conversations.list()['conversations']
                                            if row['id'] == conversation), None))
                doc = server.conversations.get(archive['id'])['document']
                user_index = next(i for i,row in enumerate(doc['messages']) if row['role']=='user')
                assert doc['messages'][user_index]['attachments_omitted']
                assert '其他人的偏好' not in json.dumps(doc, ensure_ascii=False)
                try:
                    PersonalCandidates(core).source({'conversation_id':conversation,'message_index':user_index}, None)
                except MemoryError as exc:
                    assert exc.code == 'candidate_source_invalid'
                else: raise AssertionError('Attachment turn was eligible as personal preference')
                checks.extend(['explicit_send_contains_source_copy', 'selection_no_model_call',
                               'attachment_body_not_in_chat_archive', 'personal_candidates_exclude_attachment_turn'])
                page.locator('#clear').click()
                wait(lambda: page.evaluate('!Workspace.isBusy()'))
                page.locator('#message').fill('新的普通聊天')
                page.locator('#send').click()
                wait(lambda: len(chat.inputs) == 2)
                wait(lambda: page.evaluate('!Workspace.isBusy()'))
                assert not chat.inputs[1]['attachments'] and not chat.inputs[1]['history']
                checks.append('new_conversation_has_no_shared_copy_or_history')
                page.locator('#shared-reference-open').click()
                expect(choose).to_be_visible()
                output.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output/'reference-desktop.png'))
                page.emulate_media(color_scheme='dark')
                page.screenshot(path=str(output/'reference-dark.png'))
                page.emulate_media(color_scheme='light')
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(output/'reference-mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                page.get_by_role('button', name='关闭共享资料选择', exact=True).click()

                settings = context.new_page()
                settings.on('pageerror', lambda e: errors.append(str(e)))
                settings.goto(f'http://127.0.0.1:{server.server_port}/settings#federation')
                expect(settings.locator('#shared-export')).to_be_enabled()
                with settings.expect_download() as pending:
                    settings.locator('#shared-export').click()
                saved = pending.value.path()
                bundle = json.loads(Path(saved).read_text(encoding='utf-8'))
                assert validate_export(bundle)['space']['id'] == sid
                settings.locator('#shared-archive-preview').click()
                expect(settings.locator('#shared-archive')).to_be_visible()
                assert local.status()['spaces'][0]['state'] == 'active'
                settings.locator('#shared-archive').click()
                expect(settings.locator('#shared-archives')).to_contain_text('共同计划')
                assert not local.status()['spaces']
                settings.get_by_role('button', name='恢复为只读', exact=True).click()
                expect(settings.locator('#shared-space-info')).to_contain_text('连接已撤销')
                expect(settings.locator('#shared-save')).to_be_disabled()
                expect(settings.locator('#shared-text')).to_have_value('其他人的偏好：我喜欢咖啡。<script>alert(1)</script>')
                expect(settings.locator('#shared-text')).to_have_attribute('readonly', '')
                checks.extend(['browser_download_verifies', 'preview_has_no_side_effects',
                               'archive_frees_slot', 'restore_does_not_restore_grant'])
                settings.screenshot(path=str(output/'lifecycle-desktop.png'), full_page=True)
                # Keep the original independent marker, then restore only an old database.
                prior = local.store.path.read_bytes()
                local.invite('恢复故障注入后的空间')
                local.close()
                local.store.path.write_bytes(prior)
                settings.locator('#shared-refresh').click()
                expect(settings.locator('#shared-recovery')).to_be_visible()
                settings.locator('#shared-recovery-preview').click()
                expect(settings.locator('#shared-recover')).to_be_visible()
                settings.locator('#shared-recover').click()
                expect(settings.locator('#shared-recovery')).to_be_hidden()
                assert all(s['state']=='revoked' for s in local.status()['spaces'])
                assert local.status()['endpoint'] is None
                assert list((core.data_dir/'federation/recovery').glob('*/before.sqlite'))
                checks.append('settings_recovery_keeps_backups_and_connections_revoked')
                browser.close()
            assert not errors, errors
            return {'status':'passed','checks':checks,'page_errors':errors,'synthetic_model_calls':len(chat.inputs),
                    'screenshots':[str(p) for p in sorted(output.glob('*.png'))],
                    'limits':['Model replies are fixtures; HTTP, browser, SQLite, TLS and DPAPI are real.',
                              'Reference is an explicit attachment copy, not live revocation of already sent content.']}
        finally:
            gate.set(); peer.close(); server.shutdown(); server.server_close(); thread.join(timeout=5); time.sleep(2)


def main():
    output = Path('H:/JarvisData/diagnostics/k6-shared-lifecycle-20261020')
    report = {'version':__version__, 'captured_at':datetime.now(timezone.utc).isoformat(),
              'processes':processes(), 'ui':ui(output), 'cloud_model_calls':0,
              'scope':'K6 shared-space lifecycle, data-only recovery and explicit chat copies'}
    path = ROOT/'evals/reports/k6-shared-lifecycle-2026-10-20.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'passed','report':str(path)}))


if __name__ == '__main__':
    main()

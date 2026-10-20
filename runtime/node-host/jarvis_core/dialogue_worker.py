"""One private stdin/stdout request; no server, task queue or personal writes."""
import json
from pathlib import Path
import sys


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from jarvis_core.dialogue_process import MAX_INPUT, MAX_OUTPUT
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if not raw or len(raw) > MAX_INPUT: return 2
    request = json.loads(raw)
    from jarvis_core.network_policy import activate_process
    activate_process(request['data_dir'])
    from jarvis_core.service import CoreService
    from jarvis_core.chat import gateway
    core = CoreService(request['data_dir'])
    # Carry the parent's authorization epoch. Never initialize/recover the core.
    core._security_epoch = request['epoch']
    core.assert_running()
    if request.get('task_id'):
        from jarvis_core.sample_tasks import ScopedCore
        original = core
        core = ScopedCore(original, lambda: original.ledger.assert_admitted(request['task_id']), task_id=request['task_id'])
    if request.get('action','probe') == 'reply':
        from jarvis_core.chat import ChatService
        from jarvis_core.personal import parse
        # Personal commands always execute in the Host, never a killable child.
        if parse(request['message']): return 5
        chat = ChatService(core, request['config_path'])
        def phase(value):
            sys.stdout.buffer.write(json.dumps({'id':request['id'],'phase':value}).encode()+b'\n')
            sys.stdout.buffer.flush()
        chat.phase_hook = phase
        result = chat.reply(request['message'], **request['options'])
    else:
        guard, admission = core.assert_running, core.effect_guard
        shared = request['options'].pop('shared_dispatch', None)
        if shared:
            from jarvis_core.federation import Federation
            from jarvis_core.federation_access import context
            validated, _ = context({'scope':shared['scope'],'references':shared['references']})
            guard, admission = Federation(core, shared['config_path']).access.gate(
                validated['scope'], validated['references'], request['config'], request['provider'])
        result = gateway.probe(request['config'], request['provider'], request['prompt'], core.data_dir,
            guard, admission_context=admission,
            deadline_seconds=request['deadline_seconds'], **request['options'])
    packet = json.dumps({'id': request['id'], 'result': result}, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(packet) > MAX_OUTPUT: return 3
    sys.stdout.buffer.write(packet+b'\n'); sys.stdout.buffer.flush()
    return 0


if __name__ == '__main__':
    try: code = main()
    except Exception: code = 4  # Never expose exceptions/credentials through IPC.
    sys.exit(code)

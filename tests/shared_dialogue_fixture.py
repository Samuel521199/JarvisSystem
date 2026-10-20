"""Real worker/gateway with a synthetic local transport; never loads cloud keys."""
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.chat import gateway
from jarvis_core.federation import Federation
from jarvis_core.service import CoreService
import httpx

mode = sys.argv[1]
original_probe, original_client = gateway.probe, httpx.AsyncClient


def probe(config, provider, prompt, data_dir, guard, **options):
    assert provider == 'local', 'Fixture accepts local transport only'
    core = CoreService(data_dir)
    service = Federation(core)

    def revoke():
        def update(state):
            for space in state['spaces'].values():
                policy = space.get('model_access')
                if policy:
                    policy.update(revision=policy['revision']+1, providers={})
        service.store.change(service.node, update)

    if mode == 'before':
        revoke()

    async def transport(request):
        body = json.loads(request.content)
        contains = 'SYNTHETIC_SHARED_DATA_85' in json.dumps(body, ensure_ascii=False)
        if mode == 'inflight':
            revoke()
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '共享资料测试回答' if contains else '普通测试回答'},
                         'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 3}})

    def client(**kwargs):
        kwargs['transport'] = httpx.MockTransport(transport)
        return original_client(**kwargs)
    gateway.httpx.AsyncClient = client
    return original_probe(config, provider, prompt, data_dir, guard, **options)


gateway.probe = probe
from jarvis_core.dialogue_worker import main
sys.exit(main())

"""Disposable Mem0 public-SDK experiment; never imports the Jarvis runtime.

Only this process's loopback protocol endpoint is permitted by the Python audit
hook. This is an accidental-I/O guard, NOT an OS security sandbox. Embeddings
are deterministic character n-grams, not a learned semantic encoder.
"""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.metadata
import json
import math
import os
from pathlib import Path
import secrets
import sys
import threading
import time

# Local, stdlib-only helpers; no LangMem dependency is imported.
sys.path.insert(0, str(Path(__file__).parent))
from langmem_worker import counters, unique

LIMIT = 65536
INPUT, OUTPUT = sys.stdin.buffer, sys.stdout.buffer
START = time.perf_counter()
DIMS = 256


def read():
    raw = INPUT.readline(LIMIT + 1)
    if len(raw) > LIMIT or not raw.endswith(b'\n'):
        raise ValueError('invalid_frame')
    return json.loads(raw, object_pairs_hook=unique)


def emit(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n'
    if len(raw) > LIMIT:
        raise ValueError('oversized_frame')
    OUTPUT.write(raw); OUTPUT.flush()


def lexical_vector(text):
    """Stable normalized signed character 1/2-gram hash; no model download."""
    text = ''.join(text.lower().split())
    vector = [0.0] * DIMS
    for width in (1, 2):
        for i in range(max(0, len(text) - width + 1)):
            digest = hashlib.sha256(text[i:i + width].encode()).digest()
            vector[int.from_bytes(digest[:2], 'big') % DIMS] += 1 if digest[2] & 1 else -1
    length = math.sqrt(sum(x*x for x in vector))
    if not length:
        vector[0] = 1.0; length = 1.0
    return [x/length for x in vector]


def validate_native(text):
    value = json.loads(text, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {'memory'} or not isinstance(value['memory'], list):
        raise ValueError('invalid_native_schema')
    if len(value['memory']) > 6:
        raise ValueError('native_fact_limit')
    for item in value['memory']:
        if (not isinstance(item, dict) or not set(item) <= {'id', 'text', 'attributed_to', 'linked_memory_ids'} or
                not isinstance(item.get('text'), str) or not 1 <= len(item['text']) <= 2048 or
                ('attributed_to' in item and item['attributed_to'] is not None and
                 not isinstance(item['attributed_to'], str)) or
                ('id' in item and not isinstance(item['id'], str)) or
                ('linked_memory_ids' in item and (not isinstance(item['linked_memory_ids'], list) or
                 not all(isinstance(v, str) for v in item['linked_memory_ids'])))):
            raise ValueError('invalid_native_fact')
    return value


def main():
    request = read()
    root = Path(request['root']).resolve(strict=True)
    if request.get('mode') not in {'candidate', 'sequence'} or not 1 <= len(request['steps']) <= 12:
        raise ValueError('invalid_experiment')
    if any(root.iterdir()):
        raise ValueError('scratch_must_be_empty')
    for line in Path(__file__).with_name('requirements-mem0.lock').read_text().splitlines():
        if not line or line.startswith('#'): continue
        name, version = line.split(' ', 1)[0].split('==')
        if importlib.metadata.version(name) != version:
            raise ValueError('unreviewed_dependency')
    os.environ.update(MEM0_DIR=str(root/'mem0'), MEM0_TELEMETRY='false')
    stats = {'embedding_requests': 0, 'embedded_texts': 0, 'embedding_ms': 0,
             'denied_io': [], 'generate_requests': 0}
    state = {'port': None, 'binding': True, 'step': -1, 'error': None, 'used_steps': set()}

    def audit(event, args):
        if event == 'socket.bind' and state['binding'] and args[1] == ('127.0.0.1', 0):
            return
        if event in {'socket.connect', 'socket.connect_ex'} and args[1] == ('127.0.0.1', state['port']):
            return
        if event == 'socket.getaddrinfo' and args[:2] == ('127.0.0.1', state['port']):
            return
        if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.sendto',
                     'socket.bind', 'subprocess.Popen', 'os.system'}:
            frame = sys._getframe(1)
            stats['denied_io'].append({'event': event, 'file': Path(frame.f_code.co_filename).name,
                                      'function': frame.f_code.co_name})
            raise PermissionError('lab_external_io_disabled')
    sys.addaudithook(audit)
    token = secrets.token_hex(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, status, value):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def do_POST(self):
            try:
                if self.headers.get('Authorization') != 'Bearer ' + token:
                    self.reply(401, {'error': {'message': 'local authentication required'}}); return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= LIMIT: raise ValueError('http_frame_limit')
                body = json.loads(self.rfile.read(size), object_pairs_hook=unique)
                if self.path == '/v1/embeddings':
                    texts = body.get('input')
                    if (not isinstance(texts, list) or not 1 <= len(texts) <= 12 or
                            not all(isinstance(t, str) and len(t) <= 8192 for t in texts)):
                        raise ValueError('invalid_embedding_input')
                    start = time.perf_counter()
                    rows = [{'object': 'embedding', 'index': i, 'embedding': lexical_vector(t)}
                            for i, t in enumerate(texts)]
                    stats['embedding_requests'] += 1; stats['embedded_texts'] += len(texts)
                    stats['embedding_ms'] += (time.perf_counter()-start)*1000
                    self.reply(200, {'object': 'list', 'model': 'jarvis-char-ngram-256', 'data': rows,
                                     'usage': {'prompt_tokens': 0, 'total_tokens': 0}})
                elif self.path == '/v1/chat/completions':
                    step = state['step']
                    if step in state['used_steps'] or step < 0: raise ValueError('step_call_budget')
                    state['used_steps'].add(step); stats['generate_requests'] += 1
                    messages = body.get('messages')
                    if (not isinstance(messages, list) or len(messages) != 2 or
                            [m.get('role') for m in messages] != ['system', 'user'] or
                            not all(isinstance(m.get('content'), str) for m in messages) or body.get('tools')):
                        raise ValueError('unsupported_model_request')
                    emit({'type': 'generate', 'step': step, 'messages': messages})
                    reply = read()
                    if reply.get('status') != 'SUCCEEDED' or reply.get('output_incomplete'):
                        raise ValueError('model_not_complete')
                    # Mem0 otherwise converts malformed JSON into an empty fact list.
                    # Such failures must not be scored as correct abstentions.
                    validate_native(reply['text'])
                    self.reply(200, {'id': 'lab-'+str(step), 'object': 'chat.completion',
                        'created': 0, 'model': 'jarvis-gateway', 'choices': [{'index': 0,
                        'message': {'role': 'assistant', 'content': reply['text']}, 'finish_reason': 'stop'}]})
                else:
                    raise ValueError('unsupported_endpoint')
            except Exception as exc:
                state['error'] = type(exc).__name__
                self.reply(400, {'error': {'message': 'lab request failed', 'type': 'lab_failure'}})

    server = HTTPServer(('127.0.0.1', 0), Handler)
    state['port'] = server.server_address[1]; state['binding'] = False
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start(); memory = None
    try:
        from mem0 import Memory
        url = f'http://127.0.0.1:{state["port"]}/v1'
        config = {
            'llm': {'provider': 'openai', 'config': {'api_key': token, 'openai_base_url': url,
                     'model': 'jarvis-gateway', 'temperature': 0, 'max_tokens': 1024}},
            'embedder': {'provider': 'openai', 'config': {'api_key': token, 'openai_base_url': url,
                         'model': 'jarvis-char-ngram-256', 'embedding_dims': DIMS}},
            'vector_store': {'provider': 'qdrant', 'config': {'path': str(root/'vectors'),
                             'collection_name': 'synthetic', 'embedding_model_dims': DIMS}},
            'history_db_path': str(root/'history.sqlite')}
        if request['mode'] == 'candidate':
            policy = request['instructions'].split('At most 3 candidates,', 1)[1]
            config['custom_instructions'] = (
                'Return the native {"memory": [...]} format. Each memory item text MUST be a JSON-encoded '
                'string containing exactly segment (integer), title, content, category, subject_label. '
                'Extract review-only claims from the source segments, not from their JSON metadata. '
                'At most 3 candidates,' + policy.replace('Empty candidates is valid.', 'An empty memory list is valid.'))
        memory = Memory.from_config(config)
        # Public SDK client option: no automatic HTTP retries or alternate route.
        for client in (memory.llm.client, memory.embedding_model.client):
            client.max_retries = 0; client.timeout = 65.0
        imported = counters(); aliases = {}; rows = []
        for index, step in enumerate(request['steps']):
            state['step'] = index
            op = step['op']; scope = step.get('scope', 'personal')
            if scope not in {'personal', 'project-a', 'project-b'}: raise ValueError('invalid_scope')
            if op == 'add':
                if not isinstance(step['text'], str) or not 1 <= len(step['text']) <= 8192:
                    raise ValueError('invalid_source')
                value = memory.add([{'role': 'user', 'content': step['text']}],
                                   user_id='synthetic-owner', agent_id=scope, infer=True)
                if index not in state['used_steps']: raise ValueError('missing_inference')
                if step.get('alias') and value['results']:
                    aliases[step['alias']] = value['results'][0]['id']
            elif op == 'update':
                value = memory.update(aliases[step['ref']], step['text'])
            elif op == 'delete':
                value = memory.delete(aliases[step['ref']])
            elif op == 'history':
                value = memory.history(aliases[step['ref']])
            else:
                raise ValueError('unsupported_operation')
            if state['error']: raise ValueError('endpoint_failed')
            snapshot = {s: memory.get_all(filters={'user_id': 'synthetic-owner', 'agent_id': s}, top_k=20)
                        for s in ('personal', 'project-a', 'project-b')}
            # Keep retrieval exhaustive in these tiny characterization scenes.
            if any(len(v['results']) > 10 for v in snapshot.values()): raise ValueError('scene_store_limit')
            rows.append({'step': index, 'op': op, 'scope': scope, 'result': value, 'stores': snapshot})
        candidates = None
        if request['mode'] == 'candidate':
            candidates = [json.loads(r['memory'], object_pairs_hook=unique) for r in rows[0]['result']['results']]
            if len(candidates) > 3: raise ValueError('candidate_limit')
        value = {'candidates': candidates} if candidates is not None else {'steps': rows}
        disk = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        emit({'type': 'result', 'value': value, 'resources': {'after_import': imported,
              'after_extract': counters(), 'scratch_bytes': disk, 'process_ms': (time.perf_counter()-START)*1000,
              **stats}, 'versions': {n: importlib.metadata.version(n) for n in ('mem0ai', 'qdrant-client', 'openai')}})
    finally:
        if memory is not None:
            memory.close(); memory.vector_store.client.close()
            memory.llm.client.close(); memory.embedding_model.client.close()
        server.shutdown(); thread.join(timeout=2); server.server_close()


if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(sys.stderr): main()
    except Exception as exc:
        emit({'type': 'error', 'error': type(exc).__name__, 'resources': counters()})
        sys.exit(1)

"""Bounded lab-only subprocess adapter. No LangMem import in the host process."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

LIMIT = 65536
WORKER = Path(__file__).with_name('langmem_worker.py')
WIRE_INSTRUCTIONS = (
    'You are the model in a tool-call transport. The JSON payload contains the actual model messages '
    'and available tool schemas. Follow the system messages, use the human/user messages as source data, '
    'and return only this JSON: {"tool_calls":[{"name":"CandidateBatch","args":{"candidates":[]}}]}. '
    'Call CandidateBatch exactly once. Supply its complete arguments according to its schema. '
    'Never execute any tools. Do not include Markdown or prose.'
)


def worker_environment():
    # An allowlist avoids inheriting provider keys, proxies, LangSmith tracing,
    # Python import paths and user-site packages. DPAPI is still accessible to
    # this OS account: this is dependency/process separation, not a security VM.
    env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
    return env


class LabFailure(Exception):
    pass


def run_worker(python, prompt, instructions, transport, *, cancel_event=None, timeout=90, command=None):
    """At most one transport invocation, even if upstream attempts a repair."""
    started = time.monotonic(); trace = []; diagnostics = {'generate_requests': 0}
    result = None; proc = None; reader = None
    def send(value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')+b'\n'
        if len(raw) > LIMIT:
            raise LabFailure('lab_frame_limit')
        proc.stdin.write(raw); proc.stdin.flush()
    def receive():
        def offer(value):
            try:
                inbox.put_nowait(value)
                return True
            except queue.Full:
                return False
        try:
            while True:
                line = proc.stdout.readline(LIMIT+1)
                if not line:
                    offer(None); return
                if not line.endswith(b'\n') or len(line) > LIMIT:
                    offer({'type': 'protocol_error'}); return
                if not offer(json.loads(line)): return
        except (ValueError, OSError):
            offer({'type': 'protocol_error'})
    try:
        proc = subprocess.Popen(command or [str(python), '-I', '-B', str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=WORKER.parent, env=worker_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        inbox = queue.Queue(maxsize=16)
        reader = threading.Thread(target=receive, daemon=True); reader.start()
        send({'prompt': prompt, 'instructions': instructions})
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise LabFailure('lab_cancelled')
            if time.monotonic()-started > timeout:
                raise LabFailure('lab_worker_timeout')
            try:
                message = inbox.get(timeout=.05)
            except queue.Empty:
                continue
            if not isinstance(message, dict):
                raise LabFailure('lab_worker_eof')
            if message.get('type') == 'generate':
                diagnostics['generate_requests'] += 1
                if trace:
                    raise LabFailure('lab_call_budget_exceeded')
                if set(message) != {'type', 'messages', 'tools', 'tool_choice'}:
                    raise LabFailure('lab_invalid_generate')
                wire = json.dumps({k: v for k, v in message.items() if k != 'type'}, ensure_ascii=False)
                entry = {'prompt_sha256': hashlib.sha256(wire.encode()).hexdigest(), 'prompt_bytes': len(wire.encode())}
                trace.append(entry)
                try:
                    result = transport(wire, WIRE_INSTRUCTIONS)
                except Exception as exc:
                    # A thrown transport exception has no reliable dispatch
                    # receipt. Do not call it free, successful or retryable.
                    result = {'status': 'UNKNOWN', 'outcome_uncertain': True,
                              'error_category': 'lab_transport_exception', 'exception_type': type(exc).__name__}
                entry['result'] = result
                if result.get('status') != 'SUCCEEDED' or result.get('output_incomplete'):
                    break
                send({k: result[k] for k in ('status', 'text', 'output_incomplete') if k in result})
            elif message.get('type') == 'result':
                if not trace or result is None:
                    raise LabFailure('lab_result_without_generation')
                diagnostics.update(resources=message.get('resources'), versions=message.get('versions'))
                value = message.get('value')
                if not isinstance(value, dict) or set(value) != {'candidates'}:
                    raise LabFailure('lab_invalid_result')
                proc.wait(timeout=3)
                if proc.returncode:
                    raise LabFailure('lab_worker_failed_after_result')
                result = {**result, 'text': json.dumps(value, ensure_ascii=False)}
                break
            else:
                diagnostics['worker_error_type'] = message.get('error')
                if 'resources' in message: diagnostics['resources'] = message['resources']
                raise LabFailure('lab_worker_error')
    except (LabFailure, OSError, subprocess.TimeoutExpired) as exc:
        code = str(exc) if isinstance(exc, LabFailure) else 'lab_worker_unavailable'
        result = {**(result or {}), 'status': 'CANCELLED' if code == 'lab_cancelled' else 'FAILED',
                  'error_category': code}
        result.pop('text', None)
    finally:
        if proc is not None:
            if proc.poll() is None: proc.kill()
            proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout): stream.close()
            if reader: reader.join(timeout=2)
            diagnostics['worker_exited'] = proc.poll() is not None
        diagnostics['elapsed_ms'] = round((time.monotonic()-started)*1000, 3)
    return result, {'gateway': trace, **diagnostics}


class LangMemChat:
    """Duck-typed reply for the existing source and candidate validation path."""
    def __init__(self, core, python):
        self.core, self.python = core, Path(python)
        self.diagnostics = {}

    def reply(self, prompt, *, provider, model, reasoning, cancel_event=None, **kwargs):
        from jarvis_core.chat import ROOT, effective_config, gateway, select_model
        from jarvis_core.semantic_candidates import INSTRUCTIONS
        if provider == 'auto' or kwargs != {'_purpose': 'memory_candidates', '_route_attempt_limit': 1}:
            raise ValueError('lab_requires_explicit_memory_route')
        config = select_model(effective_config(ROOT/'config/model-profiles/providers.json', self.core.data_dir),
                              provider, model, reasoning)
        if not config['providers'][provider].get('enabled', True):
            raise ValueError('disabled_provider')
        ceiling = 256 if config['providers'][provider].get('adapter', provider) == 'local' else 1024
        config['providers'][provider]['max_output_tokens'] = min(
            config['providers'][provider].get('max_output_tokens', ceiling), ceiling)
        def transport(wire, instructions):
            self.core.assert_running()
            return gateway.probe(config, provider, wire, self.core.data_dir, self.core.assert_running,
                admission_context=self.core.effect_guard, deadline_seconds=60, cancel_event=cancel_event,
                instructions=instructions)
        result, self.diagnostics = run_worker(self.python, prompt, INSTRUCTIONS, transport, cancel_event=cancel_event)
        return {**result, 'reasoning': reasoning}
